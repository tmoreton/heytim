from __future__ import annotations

from datetime import UTC, datetime

from .support import WORK_LEASE_SECONDS, table


def _claim_work(item_key: dict, record: dict) -> str | None:
    owner = record.get("messageId")
    if not isinstance(owner, str) or not owner or len(owner) > 128:
        raise ValueError("Queue message is missing a valid messageId")
    now = int(datetime.now(UTC).timestamp())
    try:
        table.update_item(
            Key=item_key,
            UpdateExpression=(
                "SET #status = :running, leaseOwner = :owner, "
                "leaseExpiresAt = :expires, startedAt = if_not_exists(startedAt, :started)"
            ),
            ConditionExpression=(
                "#status = :pending OR (#status = :running AND leaseExpiresAt < :now)"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":running": "RUNNING",
                ":owner": owner,
                ":now": now,
                ":expires": now + WORK_LEASE_SECONDS,
                ":started": datetime.now(UTC).isoformat(timespec="milliseconds"),
            },
        )
        return owner
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def _finish_work(
    item_key: dict,
    lease_owner: str,
    status: str,
    answer_field: str,
    answer: str,
    artifacts: list[dict] | None = None,
) -> str | None:
    completed_at = datetime.now(UTC).isoformat(timespec="milliseconds")
    update_expression = "SET #status = :status, #answer = :answer, completedAt = :now"
    values = {
        ":status": status,
        ":running": "RUNNING",
        ":owner": lease_owner,
        ":answer": answer,
        ":now": completed_at,
    }
    if artifacts:
        update_expression += ", artifacts = :artifacts"
        values[":artifacts"] = artifacts
    update_expression += " REMOVE leaseOwner, leaseExpiresAt"
    try:
        table.update_item(
            Key=item_key,
            UpdateExpression=update_expression,
            ConditionExpression="#status = :running AND leaseOwner = :owner",
            ExpressionAttributeNames={"#status": "status", "#answer": answer_field},
            ExpressionAttributeValues=values,
        )
        return completed_at
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None
