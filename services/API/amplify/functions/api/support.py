from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.config import Config
from shared.catalog import CatalogService
from shared.cleanup import delete_share_record
from shared.invites import (
    active_invite_access,
    invite_token_hash,
    revoke_invite_access,
)
from shared.keys import bot_sk as _bot_sk
from shared.keys import group_pk as _group_pk
from shared.keys import push_owner_key as _push_owner_key
from shared.keys import push_token_key as _push_token_key
from shared.keys import schedule_key as _schedule_key
from shared.keys import turn_pk as _turn_pk
from shared.keys import user_pk as _user_pk
from shared.keys import user_state_key as _user_state_key
from shared.time import utc_now_iso as _now

from .bot_roles import (
    CHIEF_COLOR,
    CHIEF_SYSTEM_ROLE,
    DEFAULT_BOT_COLOR,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

__all__ = [
    "_bot_sk",
    "_group_pk",
    "_now",
    "_push_owner_key",
    "_push_token_key",
    "_recent_partition_items",
    "_schedule_key",
    "_turn_pk",
    "_user_pk",
    "_user_state_key",
]

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
HEYTIM_MEMORY_ID = os.environ.get("HEYTIM_MEMORY_ID")
FILES_BUCKET_NAME = os.environ.get("FILES_BUCKET_NAME")
PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://heytim.ai")

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
sns = boto3.client(
    "sns",
    config=Config(
        retries={"total_max_attempts": 4, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=10,
    ),
)
catalog = CatalogService(table, refresh_on_read=False)
SCHEDULE_LIMIT = 25
MAX_REQUEST_BODY_BYTES = 256_000
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
_DEFAULT_ERROR_CODES = {
    400: "bad_request",
    401: "authentication_required",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    429: "rate_limited",
    501: "not_implemented",
    502: "upstream_error",
    503: "service_unavailable",
}


class ApiError(Exception):
    def __init__(self, status_code: int, message: str, *, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code or _DEFAULT_ERROR_CODES.get(status_code, "request_failed")


def _encode_page_cursor(last_key: dict | None) -> str | None:
    if not last_key:
        return None
    sort_key = last_key.get("sk")
    if not isinstance(sort_key, str):
        return None
    raw = json.dumps({"sk": sort_key}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_page_cursor(cursor: object, partition_key: str, prefix: str) -> dict | None:
    if cursor in (None, ""):
        return None
    if not isinstance(cursor, str) or len(cursor) > 512:
        raise ApiError(400, "The message cursor is invalid")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(
            base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        )
    except (ValueError, UnicodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ApiError(400, "The message cursor is invalid") from exc
    sort_key = value.get("sk") if isinstance(value, dict) else None
    if not isinstance(sort_key, str) or not sort_key.startswith(prefix):
        raise ApiError(400, "The message cursor is invalid")
    return {"pk": partition_key, "sk": sort_key}


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
    raw = event.get("body")
    if raw is None or raw == "":
        raw = "{}"
    if not isinstance(raw, str):
        raise ApiError(400, "Request body must be valid JSON")
    if len(raw) > MAX_REQUEST_BODY_BYTES or len(raw.encode("utf-8")) > MAX_REQUEST_BODY_BYTES:
        raise ApiError(413, "Request body is too large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "Request body must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ApiError(400, "Request body must be an object")
    return value


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
    return "HeyTim user"


def _verified_email(event: dict) -> str | None:
    claims = _claims(event)
    verified = claims.get("email_verified")
    if verified not in {True, "true", "True", "1"}:
        return None
    value = claims.get("email")
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    if (
        not email
        or len(email) > 320
        or email.count("@") != 1
        or any(character in email for character in "\r\n\x00")
    ):
        return None
    local, domain = email.rsplit("@", 1)
    return email if local and "." in domain and not domain.startswith(".") else None


def _push_token_id(token: str, provider: str = "expo") -> str:
    identity = token if provider == "expo" else f"{provider}:{token}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


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


def _recent_partition_items(
    partition_key: str, sort_prefix: str, limit: int
) -> list[dict]:
    return table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": partition_key, ":prefix": sort_prefix},
        ScanIndexForward=False,
        Limit=limit,
        ConsistentRead=True,
    ).get("Items", [])


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
    revoke_invite_access(invite_access_table, token)


def _active_access_invite(kind: str, token: str) -> dict:
    invite = active_invite_access(invite_access_table, kind, token)
    if not invite:
        raise ApiError(404, "This invite is invalid, expired, or revoked")
    return invite


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
    delete_share_record(table, invite_access_table, user_id, item)


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


def _bot_color(item: dict) -> str:
    color = item.get("color", DEFAULT_BOT_COLOR)
    if item.get("systemRole") == CHIEF_SYSTEM_ROLE:
        return CHIEF_COLOR
    return DEFAULT_BOT_COLOR if color == CHIEF_COLOR else color


def _public_bot(item: dict) -> dict:
    bot = {
        key: value for key, value in item.items()
        if key not in {
            "pk", "sk", "entity", "emailToken", "emailInboxClosing",
            "emailOwnerAddress",
        }
    }
    bot["emailEnabled"] = bool(item.get("emailToken"))
    bot["color"] = _bot_color(item)
    bot["allowedActions"] = [
        "edit",
        "documents",
        "browser",
        "schedule",
        "share",
        "clear",
        *([] if item.get("systemRole") == CHIEF_SYSTEM_ROLE else ["delete"]),
    ]
    return bot


def _public_schedule(item: dict) -> dict:
    return {
        key: item[key]
        for key in (
            "id",
            "botId",
            "groupId",
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


def _validate_push_registration(
    value: Any, *, require_native_details: bool = True
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ApiError(400, "Push registration must be an object")
    provider = value.get("provider", "expo")
    if provider == "expo":
        return {"provider": "expo", "token": _validate_push_token(value.get("token"))}
    if provider != "apns":
        raise ApiError(400, "provider must be expo or apns")
    token = _validate_string(value.get("token"), "token", 200).lower()
    if not 64 <= len(token) <= 200 or any(
        character not in "0123456789abcdef" for character in token
    ):
        raise ApiError(400, "token must be a valid APNs device token")
    if not require_native_details:
        return {"provider": "apns", "token": token}
    platform = value.get("platform")
    if platform not in {"ios", "macos"}:
        raise ApiError(400, "platform must be ios or macos")
    environment = value.get("environment")
    if environment not in {"sandbox", "production"}:
        raise ApiError(400, "environment must be sandbox or production")
    return {
        "provider": "apns",
        "token": token,
        "platform": platform,
        "environment": environment,
    }
