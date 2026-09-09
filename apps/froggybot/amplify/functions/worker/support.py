from __future__ import annotations

import logging
import os

import boto3
from botocore.config import Config
from shared.catalog import CatalogService
from shared.keys import bot_key as _bot_key
from shared.keys import group_pk as _group_pk
from shared.keys import push_owner_key as _push_owner_key
from shared.keys import push_token_key as _push_token_key
from shared.keys import schedule_key as _schedule_key
from shared.keys import turn_pk as _turn_pk

logger = logging.getLogger()
logger.setLevel(logging.INFO)

__all__ = [
    "_bot_key",
    "_group_pk",
    "_push_owner_key",
    "_push_token_key",
    "_schedule_key",
    "_turn_pk",
]

TABLE_NAME = os.environ["TABLE_NAME"]
INVITE_TABLE_NAME = os.environ.get("INVITE_TABLE_NAME", TABLE_NAME)
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
AGENT_RUNTIME_QUALIFIER = os.environ.get("AGENT_RUNTIME_QUALIFIER", "DEFAULT")
QUEUE_URL = os.environ["QUEUE_URL"]
FILES_BUCKET_NAME = os.environ["FILES_BUCKET_NAME"]
SCHEDULE_GROUP_NAME = os.environ.get("SCHEDULE_GROUP_NAME", "")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
FROGBOT_MEMORY_ID = os.environ.get("FROGBOT_MEMORY_ID")
# Keep the lease and message visibility beyond six times the 14-minute Lambda
# timeout, as recommended for SQS event sources. The runtime has a five-minute
# wall-clock budget, leaving enough time to durably finish or release the work.
ACTIVE_VISIBILITY_SECONDS = 85 * 60
WORK_LEASE_SECONDS = ACTIVE_VISIBILITY_SECONDS

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
invite_access_table = dynamodb.Table(INVITE_TABLE_NAME)
catalog = CatalogService(table, refresh_on_read=False)
agentcore = boto3.client(
    "bedrock-agentcore",
    config=Config(
        # SQS owns retries for an invocation. Hidden SDK retries can outlive the
        # Lambda and strand its durable lease after the runtime has already failed.
        retries={"total_max_attempts": 1, "mode": "standard"},
        connect_timeout=5,
        read_timeout=6 * 60,
    ),
)
sqs = boto3.client(
    "sqs",
    config=Config(
        retries={"total_max_attempts": 5, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=10,
    ),
)
s3 = boto3.client(
    "s3",
    config=Config(
        retries={"total_max_attempts": 4, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=15,
    ),
)
cognito = boto3.client(
    "cognito-idp",
    config=Config(
        retries={"total_max_attempts": 4, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=10,
    ),
)
scheduler = boto3.client(
    "scheduler",
    config=Config(
        retries={"total_max_attempts": 4, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=10,
    ),
)
GENERATED_ARTIFACT_FORMATS = {
    ".txt": ("document", "txt", "text/plain"),
    ".md": ("document", "md", "text/markdown"),
    ".csv": ("document", "csv", "text/csv"),
    ".json": ("document", "txt", "application/json"),
    ".html": ("document", "html", "text/html"),
    ".pdf": ("document", "pdf", "application/pdf"),
    ".docx": (
        "document",
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".xlsx": (
        "document",
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ".pptx": (
        "document",
        "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    ".png": ("image", "png", "image/png"),
}
MAX_GENERATED_ARTIFACTS = 20
MAX_GENERATED_ARTIFACT_BYTES = 8_000_000


def _account_is_active(user_id: str) -> bool:
    state = table.get_item(
        Key={"pk": f"USER#{user_id}", "sk": "STATE"}, ConsistentRead=True
    ).get("Item")
    return not state or state.get("accountStatus") not in {"DELETING", "DELETED"}
