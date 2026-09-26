"""Group reply state transitions and notification dispatch."""
from __future__ import annotations

from shared.job_envelope import send_job
from shared.time import utc_now_iso

from .support import QUEUE_URL, _group_pk, sqs, table


def _finish_group_admission_denial(
    reply_key: dict, lease_owner: str, answer: str
) -> str | None:
    completed_at = utc_now_iso()
    try:
        table.update_item(
            Key=reply_key,
            UpdateExpression=(
                "SET #status = :error, #text = :answer, completedAt = :now, "
                "usageAdmissionDenied = :denied REMOVE leaseOwner, leaseExpiresAt, "
                "pendingWork, backgroundResults, runtimeResult"
            ),
            ConditionExpression="#status = :running AND leaseOwner = :owner",
            ExpressionAttributeNames={"#status": "status", "#text": "text"},
            ExpressionAttributeValues={
                ":error": "ERROR",
                ":running": "RUNNING",
                ":owner": lease_owner,
                ":answer": answer,
                ":now": completed_at,
                ":denied": True,
            },
        )
        return completed_at
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def _finalize_remaining_group_denials(
    group_id: str, replies: list[dict], start_index: int, answer: str
) -> None:
    completed_at = utc_now_iso()
    for entry in replies[start_index:]:
        key = {"pk": _group_pk(group_id), "sk": entry["replyKey"]}
        try:
            table.update_item(
                Key=key,
                UpdateExpression=(
                    "SET #status = :error, #text = :answer, completedAt = :now, "
                    "usageAdmissionDenied = :denied REMOVE leaseOwner, "
                    "leaseExpiresAt, pendingWork, backgroundResults, runtimeResult"
                ),
                ConditionExpression="#status = :waiting OR #status = :pending",
                ExpressionAttributeNames={"#status": "status", "#text": "text"},
                ExpressionAttributeValues={
                    ":error": "ERROR",
                    ":waiting": "WAITING",
                    ":pending": "PENDING",
                    ":answer": answer,
                    ":now": completed_at,
                    ":denied": True,
                },
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            item = table.get_item(Key=key, ConsistentRead=True).get("Item")
            if not item or item.get("status") not in {"COMPLETE", "ERROR"}:
                raise


def _queue_group_reply_notifications(
    group_id: str, reply_key: dict, reply: dict, bot: dict, answer: str
) -> None:
    request = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {
            ":pk": _group_pk(group_id),
            ":prefix": "USER#",
        },
    }
    members = []
    while True:
        response = table.query(**request)
        members.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        request["ExclusiveStartKey"] = last_key
    for member in members:
        user_id = member.get("userId")
        if not isinstance(user_id, str):
            continue
        send_job(
            sqs,
            QUEUE_URL,
            {
                "type": "PUSH_NOTIFICATION",
                "userId": user_id,
                "groupId": group_id,
                "botId": bot["id"],
                "botName": bot["name"],
                "messageId": reply["id"],
                "answer": answer,
                **({"scheduleId": reply["scheduleId"], "scheduleName": reply.get("scheduleName", "Group report")} if reply.get("source") == "schedule" else {}),
                "notificationId": f"group:{group_id}:{reply['id']}:{user_id}",
            },
        )
    table.update_item(
        Key=reply_key,
        UpdateExpression="SET notificationQueued = :queued",
        ExpressionAttributeValues={":queued": True},
    )


def _activate_group_reply(group_id: str, reply_key: str) -> None:
    """Move a queued team contribution into the visible working state."""
    try:
        table.update_item(
            Key={"pk": _group_pk(group_id), "sk": reply_key},
            UpdateExpression="SET #status = :pending",
            ConditionExpression="#status = :waiting",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":pending": "PENDING", ":waiting": "WAITING"},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        # The first reply starts as pending, and retried jobs may already be complete.
        return


def _cancel_queued_reply(group_id: str, reply_key: str) -> None:
    try:
        table.update_item(
            Key={"pk": _group_pk(group_id), "sk": reply_key},
            UpdateExpression="SET #status = :cancelled, completedAt = :now",
            ConditionExpression="#status = :pending OR #status = :waiting",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":cancelled": "CANCELLED", ":now": utc_now_iso(),
                ":pending": "PENDING", ":waiting": "WAITING",
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return
