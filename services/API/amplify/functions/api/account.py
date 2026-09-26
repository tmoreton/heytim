from __future__ import annotations

from shared.account_cleanup import AccountCleanupConfig, AccountCleanupService
from shared.job_envelope import send_job
from shared.memory_identity import memory_actor_id
from shared.storage import delete_object_versions

from .billing import cancel_stripe_subscription_for_account
from .memories import _delete_user_memory as _delete_memory
from .support import (
    AGENT_RUNTIME_ARN,
    AGENT_RUNTIME_QUALIFIER,
    FILES_BUCKET_NAME,
    HEYTIM_MEMORY_ID,
    QUEUE_URL,
    SCHEDULE_GROUP_NAME,
    USER_POOL_ID,
    _now,
    _user_state_key,
    agentcore,
    catalog,
    cognito,
    invite_access_table,
    s3,
    scheduler,
    sns,
    sqs,
    table,
)


def _delete_user_files(user_id: str) -> int:
    if not FILES_BUCKET_NAME:
        return 0
    return delete_object_versions(
        s3,
        FILES_BUCKET_NAME,
        f"users/{memory_actor_id(user_id)}/",
        resource_label="user file",
    )


def _delete_user_memory(user_id: str) -> dict[str, int]:
    return _delete_memory(user_id)


def _begin_account_deletion(user_id: str, username: str) -> dict:
    cancel_stripe_subscription_for_account(user_id)
    started_at = _now()
    try:
        table.update_item(
            Key=_user_state_key(user_id),
            UpdateExpression=(
                "SET entity = :entity, accountStatus = :status, "
                "deletionStartedAt = if_not_exists(deletionStartedAt, :now)"
            ),
            ConditionExpression=(
                "attribute_not_exists(accountStatus) OR accountStatus <> :status"
            ),
            ExpressionAttributeValues={
                ":entity": "USER_STATE",
                ":status": "DELETING",
                ":now": started_at,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return {"deletionStarted": True}
    try:
        send_job(
            sqs,
            QUEUE_URL,
            {
                "type": "DELETE_ACCOUNT",
                "userId": user_id,
                "username": username,
            },
        )
    except Exception:
        table.update_item(
            Key=_user_state_key(user_id),
            UpdateExpression="REMOVE accountStatus, deletionStartedAt",
        )
        raise
    return {"deletionStarted": True}


def _cleanup_service() -> AccountCleanupService:
    return AccountCleanupService(
        table=table,
        invite_access_table=invite_access_table,
        catalog=catalog,
        agentcore=agentcore,
        cognito=cognito,
        scheduler=scheduler,
        s3=s3,
        sns=sns,
        config=AccountCleanupConfig(
            user_pool_id=USER_POOL_ID,
            schedule_group_name=SCHEDULE_GROUP_NAME,
            agent_runtime_arn=AGENT_RUNTIME_ARN,
            agent_runtime_qualifier=AGENT_RUNTIME_QUALIFIER,
            memory_id=HEYTIM_MEMORY_ID,
            files_bucket_name=FILES_BUCKET_NAME,
        ),
        now=_now,
    )


def _delete_account(user_id: str, username: str) -> dict:
    return _cleanup_service().delete_account(user_id, username)
