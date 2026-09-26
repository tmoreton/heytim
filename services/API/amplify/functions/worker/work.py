from __future__ import annotations

from datetime import UTC, datetime

from shared.time import utc_now_iso

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
                ":started": utc_now_iso(),
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
    configuration_changed: bool = False,
) -> str | None:
    completed_at = utc_now_iso()
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
    if configuration_changed:
        update_expression += ", configurationChanged = :configurationChanged"
        values[":configurationChanged"] = True
    update_expression += (
        " REMOVE leaseOwner, leaseExpiresAt, pendingWork, backgroundResults, "
        "runtimeResult, deviceRequest, deviceResult, deviceResultReceivedAt, "
        "deviceResultConsumedAt"
    )
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


def _pause_work(
    item_key: dict, lease_owner: str, pending_work: list[dict]
) -> bool:
    """Release a model invocation while external background work continues."""
    try:
        table.update_item(
            Key=item_key,
            UpdateExpression=(
                "SET #status = :pending, pendingWork = :work, activity = :activity, "
                "activityUpdatedAt = :updated REMOVE leaseOwner, leaseExpiresAt, "
                "backgroundResults, runtimeResult"
            ),
            ConditionExpression="#status = :running AND leaseOwner = :owner",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":running": "RUNNING",
                ":owner": lease_owner,
                ":work": pending_work,
                ":activity": ["Running background work"],
                ":updated": utc_now_iso(),
            },
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def _restore_paused_work(
    item_key: dict,
    lease_owner: str,
    pending_work: list[dict],
) -> bool:
    """Restore the active lease when a background dispatch never started."""
    now = int(datetime.now(UTC).timestamp())
    try:
        table.update_item(
            Key=item_key,
            UpdateExpression=(
                "SET #status = :running, leaseOwner = :owner, "
                "leaseExpiresAt = :expires REMOVE pendingWork"
            ),
            ConditionExpression="#status = :pending AND pendingWork = :work",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":running": "RUNNING",
                ":owner": lease_owner,
                ":expires": now + WORK_LEASE_SECONDS,
                ":work": pending_work,
            },
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def _release_work(item_key: dict, lease_owner: str) -> bool:
    """Return a failed attempt to the queue without waiting for its lease to expire."""
    try:
        table.update_item(
            Key=item_key,
            UpdateExpression=(
                "SET #status = :pending REMOVE leaseOwner, leaseExpiresAt"
            ),
            ConditionExpression="#status = :running AND leaseOwner = :owner",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":running": "RUNNING",
                ":owner": lease_owner,
            },
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
