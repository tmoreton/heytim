from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .runtime_jobs import poll_runtime_work, stop_runtime_work
from .support import QUEUE_URL, agentcore, sqs, table

POLL_DELAY_SECONDS = 30
IN_PROGRESS_STATUSES = {"submitted", "working"}
MAX_TASKS = 3
MAX_OUTPUT_CHARS = 5_000
MAX_POLL_ATTEMPTS = 120
MAX_BACKGROUND_AGE_SECONDS = 60 * 60
REQUIRED_FIELDS = {
    "provider",
    "resourceId",
    "sessionId",
    "taskId",
    "label",
    "startedAt",
}


def _validate_pending_work(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_TASKS:
        raise ValueError("pendingWork is invalid")
    validated = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != REQUIRED_FIELDS:
            raise ValueError("pendingWork item is invalid")
        if not all(isinstance(raw[field], str) and raw[field] for field in REQUIRED_FIELDS):
            raise ValueError("pendingWork item is invalid")
        if raw["provider"] not in {"agentcore_code_interpreter", "agentcore_runtime"}:
            raise ValueError("pendingWork provider is unsupported")
        validated.append({field: raw[field] for field in REQUIRED_FIELDS})
    return validated


def _structured_result(response: dict) -> dict:
    stream = response.get("stream")
    if stream is None:
        return response
    for event in stream:
        result = event.get("result") if isinstance(event, dict) else None
        structured = result.get("structuredContent") if isinstance(result, dict) else None
        if isinstance(structured, dict):
            return structured
    raise RuntimeError("AgentCore did not return a background task status")


def _task_result(work: dict[str, str]) -> tuple[bool, dict]:
    try:
        result = _structured_result(
            agentcore.invoke_code_interpreter(
                codeInterpreterIdentifier=work["resourceId"],
                sessionId=work["sessionId"],
                name="getTask",
                arguments={"taskId": work["taskId"]},
            )
        )
    except agentcore.exceptions.ResourceNotFoundException:
        return True, {
            "label": work["label"],
            "status": "expired",
            "stderr": "The secure sandbox session expired before the result was collected.",
            "stdout": "",
        }
    status = result.get("taskStatus")
    if not isinstance(status, str) or not status:
        raise RuntimeError("AgentCore returned an invalid background task status")
    normalized_status = status.lower()
    if normalized_status in IN_PROGRESS_STATUSES:
        return False, {}
    output = {
        "label": work["label"],
        "status": normalized_status,
        "stdout": str(result.get("stdout", ""))[-MAX_OUTPUT_CHARS:],
        "stderr": str(result.get("stderr", ""))[-MAX_OUTPUT_CHARS:],
    }
    exit_code = result.get("exitCode")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        output["exitCode"] = exit_code
    return True, output


def _poll_message(item_key: dict, resume_request: dict, poll_count: int = 1) -> dict:
    return {
        "type": "BACKGROUND_WORK_POLL",
        "itemKey": item_key,
        "resumeRequest": resume_request,
        "pollCount": poll_count,
    }


def _queue_background_poll(
    item_key: dict,
    resume_request: dict,
    *,
    delay_seconds: int = POLL_DELAY_SECONDS,
    poll_count: int = 1,
) -> None:
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        DelaySeconds=delay_seconds,
        MessageBody=json.dumps(_poll_message(item_key, resume_request, poll_count)),
    )


def _work_age_seconds(work: dict[str, str]) -> float:
    try:
        started_at = datetime.fromisoformat(work["startedAt"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("pendingWork startedAt is invalid") from exc
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - started_at.astimezone(UTC)).total_seconds())


def _expired_result(work: dict[str, str]) -> dict:
    try:
        agentcore.stop_code_interpreter_session(
            codeInterpreterIdentifier=work["resourceId"],
            sessionId=work["sessionId"],
        )
    except agentcore.exceptions.ResourceNotFoundException:
        pass
    return {
        "label": work["label"],
        "status": "expired",
        "stderr": "The background task exceeded its one-hour execution limit.",
        "stdout": "",
    }


def _process_background_work(_record: dict, request: dict) -> None:
    item_key = request.get("itemKey")
    resume_request = request.get("resumeRequest")
    if (
        not isinstance(item_key, dict)
        or set(item_key) != {"pk", "sk"}
        or not all(isinstance(value, str) and value for value in item_key.values())
        or not isinstance(resume_request, dict)
    ):
        raise ValueError("Background work poll is invalid")

    item = table.get_item(Key=item_key, ConsistentRead=True).get("Item")
    if not item:
        return
    if item.get("status") in {"CANCELLED", "COMPLETE", "ERROR"}:
        if item.get("status") == "CANCELLED":
            for work in item.get("pendingWork", []):
                if work.get("provider") == "agentcore_runtime":
                    stop_runtime_work(work)
        return
    raw_work = item.get("pendingWork")
    if raw_work is None:
        if item.get("status") == "PENDING" and (item.get("backgroundResults") or item.get("runtimeResult")):
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(resume_request),
            )
        return

    pending_work = _validate_pending_work(raw_work)
    if any(work["provider"] == "agentcore_runtime" for work in pending_work):
        if len(pending_work) != 1:
            raise ValueError("A runtime job must run on its own")
        poll_runtime_work(item_key, item, pending_work[0], resume_request)
        return
    poll_count = request.get("pollCount", 1)
    if (
        not isinstance(poll_count, int)
        or isinstance(poll_count, bool)
        or poll_count < 1
    ):
        raise ValueError("Background work poll count is invalid")
    results = []
    for work in pending_work:
        if (
            poll_count >= MAX_POLL_ATTEMPTS
            or _work_age_seconds(work) >= MAX_BACKGROUND_AGE_SECONDS
        ):
            complete, result = True, _expired_result(work)
        else:
            complete, result = _task_result(work)
        if not complete:
            _queue_background_poll(
                item_key, resume_request, poll_count=poll_count + 1
            )
            return
        results.append(result)

    try:
        table.update_item(
            Key=item_key,
            UpdateExpression=(
                "SET #status = :pending, backgroundResults = :results, "
                "activity = :activity, activityUpdatedAt = :updated REMOVE pendingWork"
            ),
            ConditionExpression="#status = :pending AND pendingWork = :work",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":work": pending_work,
                ":results": results,
                ":activity": ["Finishing response"],
                ":updated": datetime.now(UTC).isoformat(timespec="milliseconds"),
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return
    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(resume_request))
