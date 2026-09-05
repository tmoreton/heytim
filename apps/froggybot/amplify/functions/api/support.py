from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.config import Config
from shared.catalog import CatalogService
from shared.invites import invite_token_hash

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
INVITE_TABLE_NAME = os.environ.get("INVITE_TABLE_NAME", TABLE_NAME)
QUEUE_URL = os.environ["QUEUE_URL"]
QUEUE_ARN = os.environ["QUEUE_ARN"]
SCHEDULE_DLQ_ARN = os.environ["SCHEDULE_DLQ_ARN"]
SCHEDULE_GROUP_NAME = os.environ["SCHEDULE_GROUP_NAME"]
SCHEDULE_ROLE_ARN = os.environ["SCHEDULE_ROLE_ARN"]
USER_POOL_ID = os.environ["USER_POOL_ID"]
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN")
AGENT_RUNTIME_QUALIFIER = os.environ.get("AGENT_RUNTIME_QUALIFIER", "DEFAULT")
FROGBOT_MEMORY_ID = os.environ.get("FROGBOT_MEMORY_ID")
FILES_BUCKET_NAME = os.environ.get("FILES_BUCKET_NAME")
PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://froggybot.com")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
invite_access_table = dynamodb.Table(INVITE_TABLE_NAME)
sqs = boto3.client("sqs")
s3 = boto3.client("s3")
agentcore = boto3.client(
    "bedrock-agentcore",
    config=Config(
        retries={"total_max_attempts": 5, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=20,
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
catalog = CatalogService(table)
SCHEDULE_LIMIT = 25
MAX_ATTACHMENTS_PER_MESSAGE = 5
DOCUMENT_MAX_BYTES = 4_500_000
IMAGE_MAX_BYTES = 3_750_000
ATTACHMENT_FORMATS = {
    ".pdf": ("document", "pdf", "application/pdf"),
    ".csv": ("document", "csv", "text/csv"),
    ".doc": ("document", "doc", "application/msword"),
    ".docx": (
        "document",
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".xls": ("document", "xls", "application/vnd.ms-excel"),
    ".xlsx": (
        "document",
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ".html": ("document", "html", "text/html"),
    ".txt": ("document", "txt", "text/plain"),
    ".md": ("document", "md", "text/markdown"),
    ".png": ("image", "png", "image/png"),
    ".jpg": ("image", "jpeg", "image/jpeg"),
    ".jpeg": ("image", "jpeg", "image/jpeg"),
    ".gif": ("image", "gif", "image/gif"),
    ".webp": ("image", "webp", "image/webp"),
}
ALLOWED_COLORS = {
    "#007A3D",
    "#58BEAA",
    "#FFAA34",
    "#6C5CE7",
    "#3984F6",
    "#F46A27",
    "#E95383",
}

DEFAULT_BOTS = [
    {
        "name": "Chief",
        "tagline": "Keeps the work moving and connects the dots.",
        "color": "#58BEAA",
        "prompt": "Act as my chief of staff. Clarify priorities, keep answers concise, and always end with the best next action.",
        "toolIds": ["current_time", "calculator"],
        "skillIds": ["group-decision"],
    },
    {
        "name": "Research Scout",
        "tagline": "Finds the signal and brings back the evidence.",
        "color": "#6C5CE7",
        "prompt": "Research questions carefully. Separate facts from inference and call out uncertainty instead of guessing.",
        "toolIds": ["web", "calculator"],
        "skillIds": ["deep-research"],
    },
    {
        "name": "Draft Partner",
        "tagline": "Turns rough thinking into clear words.",
        "color": "#FFAA34",
        "prompt": "Help me write in a direct, warm voice. Return usable drafts and preserve the facts I provide.",
        "toolIds": [],
        "skillIds": [],
    },
]


class ApiError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _response(status_code: int, body: Any) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=_json_default, separators=(",", ":")),
    }


def _claims(event: dict) -> dict:
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )


def _user_id(event: dict) -> str:
    subject = _claims(event).get("sub")
    if not isinstance(subject, str) or not subject:
        raise ApiError(401, "Sign in is required")
    return subject


def _username(event: dict) -> str:
    username = _claims(event).get("cognito:username")
    if not isinstance(username, str) or not username:
        raise ApiError(401, "Your account identity is incomplete. Sign in again.")
    return username


def _body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "Request body must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ApiError(400, "Request body must be an object")
    return value


def _user_pk(user_id: str) -> str:
    return f"USER#{user_id}"


def _bot_sk(bot_id: str) -> str:
    return f"BOT#{bot_id}"


def _turn_pk(user_id: str, bot_id: str) -> str:
    return f"CHAT#{user_id}#{bot_id}"


def _user_state_key(user_id: str) -> dict:
    return {"pk": _user_pk(user_id), "sk": "STATE"}


def _schedule_key(user_id: str, schedule_id: str) -> dict:
    return {"pk": _user_pk(user_id), "sk": f"SCHEDULE#{schedule_id}"}


def _group_pk(group_id: str) -> str:
    return f"GROUP#{group_id}"


def _group_message_sk(created_at: str, message_id: str, order: int = 0) -> str:
    return f"MESSAGE#{created_at}#{order:02d}#{message_id}"


def _display_name(event: dict) -> str:
    claims = _claims(event)
    for key in ("name", "preferred_username", "email"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            clean = value.strip()
            if key == "email":
                clean = clean.split("@", 1)[0]
            return clean[:40]
    return "FroggyBot user"


def _push_token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _push_token_key(user_id: str, token_id: str) -> dict:
    return {"pk": _user_pk(user_id), "sk": f"PUSH#{token_id}"}


def _push_owner_key(token_id: str) -> dict:
    return {"pk": f"PUSH_TOKEN#{token_id}", "sk": "OWNER"}


def _file_key(user_id: str, file_id: str) -> dict:
    return {"pk": _user_pk(user_id), "sk": f"FILE#{file_id}"}


def _partition_items(partition_key: str, sort_prefix: str | None = None) -> list[dict]:
    expression = "pk = :pk"
    values = {":pk": partition_key}
    if sort_prefix is not None:
        expression += " AND begins_with(sk, :prefix)"
        values[":prefix"] = sort_prefix
    request: dict[str, Any] = {
        "KeyConditionExpression": expression,
        "ExpressionAttributeValues": values,
        "ConsistentRead": True,
    }
    items = []
    while True:
        response = table.query(**request)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        request["ExclusiveStartKey"] = last_key


def _scan_items(filter_expression: Any) -> list[dict]:
    items = []
    request: dict[str, Any] = {"FilterExpression": filter_expression}
    while True:
        response = table.scan(**request)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        request["ExclusiveStartKey"] = last_key


def _ensure_account_active(user_id: str) -> None:
    state = table.get_item(Key=_user_state_key(user_id), ConsistentRead=True).get(
        "Item"
    )
    status = state.get("accountStatus") if state else None
    if status == "DELETING":
        raise ApiError(409, "Account deletion is still in progress. Please try again.")
    if status == "DELETED":
        raise ApiError(410, "This account has been deleted.")


def _invite_access_delete(token: str) -> None:
    invite_access_table.delete_item(Key={"tokenHash": invite_token_hash(token)})


def _share_token(item: dict) -> str | None:
    pk = item.get("pk")
    if not isinstance(pk, str) or "#" not in pk:
        return None
    token = pk.split("#", 1)[1]
    return token if token else None


def _share_bot_id(item: dict) -> str | None:
    target_id = item.get("targetId")
    if isinstance(target_id, str):
        return target_id
    snapshot = item.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    bot = snapshot.get("bot")
    if not isinstance(bot, dict):
        return None
    bot_id = bot.get("id")
    return bot_id if isinstance(bot_id, str) else None


def _owned_share_records(user_id: str) -> list[dict]:
    return _scan_items(
        Attr("entity").is_in(["SHARE", "SKILL_SHARE", "GROUP_INVITE"])
        & (Attr("ownerId").eq(user_id) | Attr("createdBy").eq(user_id))
    )


def _delete_share_record(user_id: str, item: dict) -> None:
    token = _share_token(item)
    if not token:
        return
    entity = item.get("entity")
    with table.batch_writer() as batch:
        batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
        batch.delete_item(Key={"pk": _user_pk(user_id), "sk": f"SHARE#{token}"})
        batch.delete_item(Key={"pk": _user_pk(user_id), "sk": f"INVITE#{token}"})
        if entity == "GROUP_INVITE" and isinstance(item.get("groupId"), str):
            batch.delete_item(
                Key={"pk": _group_pk(item["groupId"]), "sk": f"INVITE#{token}"}
            )
    _invite_access_delete(token)


def _revoke_bot_shares(
    user_id: str, bot_id: str, *, scopes: set[str] | None = None
) -> int:
    shares = [
        item
        for item in _owned_share_records(user_id)
        if item.get("entity") == "SHARE"
        and _share_bot_id(item) == bot_id
        and (scopes is None or item.get("scope") in scopes)
    ]
    for share in shares:
        _delete_share_record(user_id, share)
    return len(shares)


def _register_access_invite(
    kind: str,
    token: str,
    created_by: str,
    expires_at: int,
    target_id: str,
) -> None:
    invite_access_table.put_item(
        Item={
            "tokenHash": invite_token_hash(token),
            "kind": kind,
            "targetId": target_id,
            "createdBy": created_by,
            "createdAt": _now(),
            "expiresAt": expires_at,
        }
    )


def _record_invite_join(kind: str, token: str) -> None:
    try:
        invite_access_table.update_item(
            Key={"tokenHash": invite_token_hash(token)},
            UpdateExpression="SET lastJoinedAt = :now, joinCount = if_not_exists(joinCount, :zero) + :one",
            ConditionExpression="kind = :kind",
            ExpressionAttributeValues={
                ":now": _now(),
                ":zero": 0,
                ":one": 1,
                ":kind": kind,
            },
        )
    except invite_access_table.meta.client.exceptions.ConditionalCheckFailedException:
        # Links created before invite-only access remain importable for existing users.
        return


def _public_bot(item: dict) -> dict:
    return {
        key: value for key, value in item.items() if key not in {"pk", "sk", "entity"}
    }


def _public_schedule(item: dict) -> dict:
    return {
        key: item[key]
        for key in (
            "id",
            "botId",
            "name",
            "prompt",
            "frequency",
            "dayOfWeek",
            "dayOfMonth",
            "time",
            "timezone",
            "enabled",
            "createdAt",
            "updatedAt",
            "lastRunAt",
            "lastStatus",
        )
        if key in item
    }


def _validate_string(
    value: Any, field: str, maximum: int, *, required: bool = True
) -> str:
    if not isinstance(value, str):
        raise ApiError(400, f"{field} must be text")
    clean = value.strip()
    if required and not clean:
        raise ApiError(400, f"{field} is required")
    if len(clean) > maximum:
        raise ApiError(400, f"{field} must be at most {maximum} characters")
    return clean


def _validate_push_token(value: Any) -> str:
    token = _validate_string(value, "token", 256)
    valid_prefix = token.startswith(("ExpoPushToken[", "ExponentPushToken["))
    if not valid_prefix or not token.endswith("]"):
        raise ApiError(400, "token must be a valid Expo push token")
    token_value = token[token.index("[") + 1 : -1]
    if not token_value or not all(
        character.isalnum() or character in "-_" for character in token_value
    ):
        raise ApiError(400, "token must be a valid Expo push token")
    return token
