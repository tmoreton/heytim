from __future__ import annotations

import logging
import os

import boto3
from botocore.config import Config
from shared.catalog import CatalogService

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
AGENT_RUNTIME_QUALIFIER = os.environ.get("AGENT_RUNTIME_QUALIFIER", "DEFAULT")
QUEUE_URL = os.environ["QUEUE_URL"]
FILES_BUCKET_NAME = os.environ["FILES_BUCKET_NAME"]
WORK_LEASE_SECONDS = 7 * 60

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"

table = boto3.resource("dynamodb").Table(TABLE_NAME)
catalog = CatalogService(table)
agentcore = boto3.client(
    "bedrock-agentcore",
    config=Config(
        retries={"total_max_attempts": 5, "mode": "adaptive"},
        connect_timeout=5,
        read_timeout=260,
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


def _bot_key(user_id: str, bot_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"BOT#{bot_id}"}


def _turn_pk(user_id: str, bot_id: str) -> str:
    return f"CHAT#{user_id}#{bot_id}"


def _schedule_key(user_id: str, schedule_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"SCHEDULE#{schedule_id}"}


def _group_pk(group_id: str) -> str:
    return f"GROUP#{group_id}"


def _push_token_key(user_id: str, token_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"PUSH#{token_id}"}


def _push_owner_key(token_id: str) -> dict:
    return {"pk": f"PUSH_TOKEN#{token_id}", "sk": "OWNER"}


def _account_is_active(user_id: str) -> bool:
    state = table.get_item(
        Key={"pk": f"USER#{user_id}", "sk": "STATE"}, ConsistentRead=True
    ).get("Item")
    return not state or state.get("accountStatus") not in {"DELETING", "DELETED"}
