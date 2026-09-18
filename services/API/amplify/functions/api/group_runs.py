"""User-initiated cancellation of queued room workflow steps."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from boto3.dynamodb.conditions import Attr
from shared.action_grants import approval_grant_digest
from shared.approval_storage import approval_snapshot_key
from shared.workflows import run_key

from .groups import _require_group_member
from .support import (
    FILES_BUCKET_NAME,
    QUEUE_URL,
    ApiError,
    _group_pk,
    _now,
    _partition_items,
    _validate_string,
    catalog,
    s3,
    sqs,
    table,
)


def _decide_group_action(user_id: str, group_id: str, run_id: str,
                         task_id: str, approved: bool) -> dict:
    _require_group_member(user_id, group_id)
    run_id = _validate_string(run_id, "runId", 64)
    task_id = _validate_string(task_id, "taskId", 64)
    run = table.get_item(Key=run_key(_group_pk(group_id), run_id), ConsistentRead=True).get("Item")
    if not run or run.get("entity") != "WORKFLOW_RUN":
        raise ApiError(404, "Run not found")
    if user_id != run.get("ownerId"):
        raise ApiError(403, "Only the requester can decide this action")
    if run.get("status") in {"COMPLETE", "ERROR", "CANCELLED"}:
        raise ApiError(409, "This run has already finished")
    try:
        position = run["taskIds"].index(task_id)
        task_key = run["taskKeys"][position]
    except (KeyError, IndexError, ValueError) as exc:
        raise ApiError(404, "Task not found") from exc
    key = {"pk": _group_pk(group_id), "sk": task_key}
    task = table.get_item(Key=key, ConsistentRead=True).get("Item")
    proposal = task.get("approvalRequest") if task else None
    if (not task or task.get("id") != task_id or task.get("runId") != run_id
            or task.get("status") != "AWAITING_APPROVAL" or not isinstance(proposal, dict)):
        raise ApiError(409, "This approval request is no longer active")
    try:
        expires = datetime.fromisoformat(proposal["expiresAt"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(409, "This approval request is invalid") from exc
    if expires.tzinfo is None or expires <= datetime.now(UTC):
        raise ApiError(409, "This approval request expired")
    bot_id = task.get("authorId")
    if task.get("botOwnerId") != user_id or not isinstance(bot_id, str):
        raise ApiError(409, "This action is not owned by the requester")
    bot = table.get_item(Key={"pk": f"USER#{user_id}", "sk": f"BOT#{bot_id}"}, ConsistentRead=True).get("Item")
    if not bot or not catalog.approval_tool_names(user_id, bot.get("toolIds", [])):
        raise ApiError(409, "The bot no longer has interactive tools")
    if task.get("approvalGrantDigest") != approval_grant_digest(catalog, user_id, bot):
        raise ApiError(409, "The bot's tool grants changed after this proposal")
    if run.get("source") == "event":
        routine = table.get_item(
            Key={"pk": _group_pk(group_id), "sk": f"ROUTINE#{run['routineId']}"},
            ConsistentRead=True,
        ).get("Item")
        if (not routine or routine.get("enabled") is not True
                or routine.get("updatedAt") != run.get("routineUpdatedAt")):
            raise ApiError(409, "The routine changed after this action was proposed")
    request = task.get("resumeRequest")
    if (not isinstance(request, dict) or request.get("groupId") != group_id
            or request.get("messageId") != run_id):
        raise ApiError(409, "This run cannot be resumed")
    now = _now()
    # A delayed duplicate gives the queue a recovery path if the immediate
    # dispatch fails after the conditional state transition.
    sqs.send_message(QueueUrl=QUEUE_URL, DelaySeconds=10, MessageBody=json.dumps(request))
    if approved:
        decision = {key: proposal[key] for key in ("id", "digest", "toolUseId")}
        decision["executionKey"] = str(uuid.uuid4())
        expression = "SET #status = :pending, approvalDecision = :decision, approvedAt = :now"
    else:
        decision = None
        expression = ("SET #status = :error, #text = :denied, completedAt = :now "
                      "REMOVE approvalRequest, approvalDecision, approvalConsumedAt")
    try:
        table.update_item(
            Key=key, UpdateExpression=expression,
            ConditionExpression="#status = :awaiting AND approvalRequest = :proposal",
            ExpressionAttributeNames={"#status": "status", **({"#text": "text"} if not approved else {})},
            ExpressionAttributeValues={
                ":awaiting": "AWAITING_APPROVAL", ":proposal": proposal,
                ":now": now, **({":pending": "PENDING", ":decision": decision}
                                if approved else {":error": "ERROR", ":denied": "Action denied by the requester."}),
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(409, "This approval request is no longer active") from exc
    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(request))
    if not approved:
        s3.delete_object(Bucket=FILES_BUCKET_NAME,
                         Key=approval_snapshot_key("group", group_id, task_id))
    return {"runId": run_id, "taskId": task_id,
            "status": "pending" if approved else "denied"}


def _cancel_group_run(user_id: str, group_id: str, run_id: str) -> dict:
    meta, _ = _require_group_member(user_id, group_id)
    run_id = _validate_string(run_id, "runId", 64)
    key = run_key(_group_pk(group_id), run_id)
    run = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not run or run.get("entity") != "WORKFLOW_RUN":
        raise ApiError(404, "Run not found")
    if user_id not in {run.get("ownerId"), meta.get("ownerId")}:
        raise ApiError(403, "Only the requester or group owner can cancel this run")
    if run.get("status") in {"COMPLETE", "ERROR"}:
        raise ApiError(409, "This run has already finished")
    if run.get("status") != "CANCELLED":
        try:
            table.update_item(
                Key=key,
                UpdateExpression="SET #status = :cancelled, cancelRequestedAt = :now, updatedAt = :now",
                ConditionExpression=Attr("status").is_in(["PENDING", "RUNNING", "WAITING", "AWAITING_APPROVAL"]),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":cancelled": "CANCELLED", ":now": _now()},
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise ApiError(409, "This run has already finished") from exc
    keys = run.get("taskKeys")
    if not isinstance(keys, list) or not all(isinstance(item, str) for item in keys):
        keys = [
            item["sk"] for item in _partition_items(_group_pk(group_id), "MESSAGE#")
            if item.get("roundId") == run_id
        ]
    for reply_key in keys:
        reply = table.get_item(Key={"pk": _group_pk(group_id), "sk": reply_key}, ConsistentRead=True).get("Item")
        try:
            table.update_item(
                Key={"pk": _group_pk(group_id), "sk": reply_key},
                UpdateExpression="SET #status = :cancelled, completedAt = :now",
                ConditionExpression=Attr("status").is_in(["PENDING", "WAITING", "AWAITING_APPROVAL"]),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":cancelled": "CANCELLED", ":now": _now()},
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            # A running step may finish. Workers check the run before dispatching
            # any later step, and the synthesis is suppressed.
            continue
        if reply and reply.get("status") == "AWAITING_APPROVAL":
            s3.delete_object(Bucket=FILES_BUCKET_NAME,
                             Key=approval_snapshot_key("group", group_id, reply["id"]))
    return {"runId": run_id, "status": "cancelled"}
