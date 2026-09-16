from __future__ import annotations

from shared.account_cleanup import AccountCleanupConfig, AccountCleanupService
from shared.time import utc_now_iso

from .support import (
    AGENT_RUNTIME_ARN,
    AGENT_RUNTIME_QUALIFIER,
    FILES_BUCKET_NAME,
    FROGBOT_MEMORY_ID,
    SCHEDULE_GROUP_NAME,
    USER_POOL_ID,
    agentcore,
    catalog,
    cognito,
    invite_access_table,
    s3,
    scheduler,
    sns,
    table,
)

cleanup_service = AccountCleanupService(
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
        memory_id=FROGBOT_MEMORY_ID,
        files_bucket_name=FILES_BUCKET_NAME,
    ),
    now=utc_now_iso,
)


def _delete_account(user_id: str, username: str) -> dict:
    return cleanup_service.delete_account(user_id, username)
