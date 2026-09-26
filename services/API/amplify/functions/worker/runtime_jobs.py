from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from shared.time import utc_now_iso

from .health_events import record_terminal_error
from .support import (
    AGENT_RUNTIME_ARN,
    AGENT_RUNTIME_QUALIFIER,
    FILES_BUCKET_NAME,
    QUEUE_URL,
    agentcore,
    s3,
    sqs,
    table,
)

RUNTIME_POLL_SECONDS = 10
RUNTIME_MAX_SECONDS = 8 * 60 * 60
RUNTIME_HEARTBEAT_GRACE_SECONDS = 180


def runtime_work(payload: dict, continuation: list[dict]) -> dict:
    prefix = payload["artifacts"]["prefix"].replace("/artifacts/", "/runs/")
    job_id = hashlib.sha256(
        json.dumps(
            {
                "continuation": continuation,
                "approval": payload.get("actionApproval"),
                "deviceResult": payload.get("deviceResult"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    key = f"{prefix}/{job_id}/state.json"
    payload["runtimeJob"] = {"id": job_id}
    return {
        "provider": "agentcore_runtime",
        "resourceId": AGENT_RUNTIME_ARN,
        "sessionId": hashlib.sha256(key.encode()).hexdigest(),
        "taskId": key,
        "startedAt": utc_now_iso(),
        "label": "Agent is working",
    }


def queue_runtime_poll(
    item_key: dict, resume_request: dict, delay: int = RUNTIME_POLL_SECONDS
) -> None:
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        DelaySeconds=delay,
        MessageBody=json.dumps(
            {
                "type": "BACKGROUND_WORK_POLL",
                "itemKey": item_key,
                "resumeRequest": resume_request,
            }
        ),
    )


def _age(value: str) -> float:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Runtime timestamp must have a timezone")
    return (datetime.now(UTC) - timestamp).total_seconds()


def _read_state(work: dict) -> dict | None:
    try:
        response = s3.get_object(Bucket=FILES_BUCKET_NAME, Key=work["taskId"])
    except s3.exceptions.NoSuchKey:
        return None
    with response["Body"] as body:
        raw = body.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Runtime state is too large")
    state = json.loads(raw, parse_float=Decimal)
    if not isinstance(state, dict) or state.get("status") not in {
        "RUNNING",
        "COMPLETE",
        "ERROR",
    }:
        raise ValueError("Runtime state is invalid")
    return state


def stop_runtime_work(work: dict) -> None:
    # The marker also covers cancellation between dispatch and runtime startup.
    s3.put_object(
        Bucket=FILES_BUCKET_NAME,
        Key=f"{work['taskId']}.cancel",
        Body=b'{"cancelled":true}',
        ContentType="application/json",
    )
    try:
        agentcore.stop_runtime_session(
            agentRuntimeArn=AGENT_RUNTIME_ARN,
            qualifier=AGENT_RUNTIME_QUALIFIER,
            runtimeSessionId=work["sessionId"],
        )
    except agentcore.exceptions.ResourceNotFoundException:
        pass


def poll_runtime_work(
    item_key: dict, item: dict, work: dict, resume_request: dict
) -> None:
    if (
        work["resourceId"] != AGENT_RUNTIME_ARN
        or hashlib.sha256(work["taskId"].encode()).hexdigest() != work["sessionId"]
    ):
        raise ValueError("Runtime work identity is invalid")
    state = _read_state(work)
    age = _age(work["startedAt"])
    stalled = _age(state.get("heartbeatAt", work["startedAt"])) if state else age
    if not state or state["status"] == "RUNNING":
        if age >= RUNTIME_MAX_SECONDS or stalled >= RUNTIME_HEARTBEAT_GRACE_SECONDS:
            stop_runtime_work(work)
            message = (
                "This run reached its eight-hour limit."
                if age >= RUNTIME_MAX_SECONDS
                else "This run stopped reporting its health and was interrupted."
            )
            record_terminal_error(message)
            state = {
                **(state or {}),
                "status": "ERROR",
                "terminalError": {
                    "message": message
                    + " Saved progress is available; verify completed external actions before continuing."
                },
            }
        else:
            if state:
                try:
                    table.update_item(
                        Key=item_key,
                        UpdateExpression="SET activity = :activity, activityUpdatedAt = :now",
                        ConditionExpression="#status = :pending AND pendingWork = :work",
                        ExpressionAttributeNames={"#status": "status"},
                        ExpressionAttributeValues={
                            ":activity": state.get("progress") or ["Agent is working"],
                            ":now": state["heartbeatAt"],
                            ":pending": "PENDING",
                            ":work": item["pendingWork"],
                        },
                    )
                except table.meta.client.exceptions.ConditionalCheckFailedException:
                    return
            queue_runtime_poll(item_key, resume_request)
            return
    result = {
        key: state[key]
        for key in (
            "text", "pendingWork", "pendingApproval", "pendingDeviceCall",
            "usage", "terminalError", "botMutations",
        )
        if key in state
    }
    result["usageEventId"] = f"runtime:{work['sessionId']}"
    try:
        table.update_item(
            Key=item_key,
            UpdateExpression="SET runtimeResult = :result, activity = :activity REMOVE pendingWork",
            ConditionExpression="#status = :pending AND pendingWork = :work",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":work": item["pendingWork"],
                ":result": result,
                ":activity": state.get("progress") or item.get("activity") or ["Finishing response"],
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return
    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(resume_request))
