"""Expire paused proposals without ever resuming an unapproved tool call."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from shared.approval_storage import approval_snapshot_key
from shared.time import utc_now_iso

from .support import FILES_BUCKET_NAME, QUEUE_URL, _bot_key, s3, sqs, table


def delete_approval_snapshot(scope: str, scope_id: str, turn_id: str,
                             bot_id: str | None = None) -> None:
    s3.delete_object(Bucket=FILES_BUCKET_NAME,
                     Key=approval_snapshot_key(scope, scope_id, turn_id, bot_id))


def queue_approval_expiry(item_key: dict, proposal: dict, scope: str) -> None:
    sqs.send_message(
        QueueUrl=QUEUE_URL, DelaySeconds=900,
        MessageBody=json.dumps({"type": "APPROVAL_EXPIRY", "scope": scope,
                                "itemKey": item_key, "proposalId": proposal["id"]}),
    )


def process_approval_expiry(request: dict) -> None:
    key = request.get("itemKey")
    if (not isinstance(key, dict) or set(key) != {"pk", "sk"}
            or not all(isinstance(value, str) for value in key.values())):
        raise ValueError("Approval expiry identity is invalid")
    scope = request.get("scope")
    if scope not in {"direct", "group"}:
        raise ValueError("Approval expiry scope is invalid")
    item = table.get_item(Key=key, ConsistentRead=True).get("Item")
    proposal = item.get("approvalRequest") if item else None
    if (not isinstance(proposal, dict) or proposal.get("id") != request.get("proposalId")
            or item.get("status") != "AWAITING_APPROVAL"):
        return
    expires = datetime.fromisoformat(proposal["expiresAt"].replace("Z", "+00:00"))
    if expires > datetime.now(UTC):
        remaining = max(1, min(900, int((expires - datetime.now(UTC)).total_seconds()) + 1))
        sqs.send_message(QueueUrl=QUEUE_URL, DelaySeconds=remaining,
                         MessageBody=json.dumps(request))
        return
    message = "The proposed action expired without approval. No action was taken."
    request_to_resume = item.get("resumeRequest") if scope == "group" else None
    if isinstance(request_to_resume, dict):
        sqs.send_message(QueueUrl=QUEUE_URL, DelaySeconds=10,
                         MessageBody=json.dumps(request_to_resume))
    try:
        table.update_item(
            Key=key,
            UpdateExpression=(
                "SET #status = :error, #answer = :message, completedAt = :now "
                "REMOVE approvalRequest, approvalDecision, approvalConsumedAt"
            ),
            ConditionExpression="#status = :awaiting AND approvalRequest = :proposal",
            ExpressionAttributeNames={"#status": "status", "#answer": "assistantText" if scope == "direct" else "text"},
            ExpressionAttributeValues={
                ":error": "ERROR", ":awaiting": "AWAITING_APPROVAL",
                ":message": message, ":now": utc_now_iso(), ":proposal": proposal,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return
    if scope == "direct":
        from .notifications import _queue_reply_notification, _update_schedule_result
        bot = table.get_item(Key=_bot_key(item["userId"], item["botId"]), ConsistentRead=True).get("Item")
        _update_schedule_result(item, "error", utc_now_iso())
        if bot:
            _queue_reply_notification(item["userId"], item["botId"], key, item, bot, message)
        delete_approval_snapshot("direct", item["userId"], item["id"], item["botId"])
    else:
        delete_approval_snapshot("group", item["pk"].removeprefix("GROUP#"), item["id"])
        if isinstance(request_to_resume, dict):
            sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(request_to_resume))
