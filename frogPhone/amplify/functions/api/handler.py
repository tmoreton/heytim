from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
QUEUE_URL = os.environ["QUEUE_URL"]
SHARE_BASE_URL = os.environ.get("SHARE_BASE_URL", "frogbot://share")

table = boto3.resource("dynamodb").Table(TABLE_NAME)
sqs = boto3.client("sqs")

TOOL_CATALOG = [
    {"id": "web", "name": "Web reader", "description": "Open and summarize links."},
    {"id": "calculator", "name": "Calculator", "description": "Do exact arithmetic."},
    {"id": "current_time", "name": "World clock", "description": "Check time by timezone."},
]
SKILL_CATALOG = [
    {"id": "researcher", "name": "Researcher", "description": "Investigate and synthesize evidence."},
    {"id": "writer", "name": "Writer", "description": "Draft polished, audience-aware copy."},
    {"id": "planner", "name": "Planner", "description": "Turn goals into practical next steps."},
]
ALLOWED_TOOL_IDS = {item["id"] for item in TOOL_CATALOG}
ALLOWED_SKILL_IDS = {item["id"] for item in SKILL_CATALOG}
ALLOWED_COLORS = {"#58BEAA", "#FFAA34", "#6C5CE7", "#3984F6", "#F46A27", "#E95383"}

DEFAULT_BOTS = [
    {
        "name": "Chief",
        "tagline": "Keeps the work moving and connects the dots.",
        "color": "#58BEAA",
        "prompt": "Act as my chief of staff. Clarify priorities, keep answers concise, and always end with the best next action.",
        "toolIds": ["current_time", "calculator"],
        "skillIds": ["planner"],
    },
    {
        "name": "Research Scout",
        "tagline": "Finds the signal and brings back the evidence.",
        "color": "#6C5CE7",
        "prompt": "Research questions carefully. Separate facts from inference and call out uncertainty instead of guessing.",
        "toolIds": ["web", "calculator"],
        "skillIds": ["researcher"],
    },
    {
        "name": "Draft Partner",
        "tagline": "Turns rough thinking into clear words.",
        "color": "#FFAA34",
        "prompt": "Help me write in a direct, warm voice. Return usable drafts and preserve the facts I provide.",
        "toolIds": [],
        "skillIds": ["writer"],
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
    return event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})


def _user_id(event: dict) -> str:
    subject = _claims(event).get("sub")
    if not isinstance(subject, str) or not subject:
        raise ApiError(401, "Sign in is required")
    return subject


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


def _push_token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _push_token_key(user_id: str, token_id: str) -> dict:
    return {"pk": _user_pk(user_id), "sk": f"PUSH#{token_id}"}


def _push_owner_key(token_id: str) -> dict:
    return {"pk": f"PUSH_TOKEN#{token_id}", "sk": "OWNER"}


def _public_bot(item: dict) -> dict:
    return {key: value for key, value in item.items() if key not in {"pk", "sk", "entity"}}


def _validate_string(value: Any, field: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ApiError(400, f"{field} must be text")
    clean = value.strip()
    if required and not clean:
        raise ApiError(400, f"{field} is required")
    if len(clean) > maximum:
        raise ApiError(400, f"{field} must be at most {maximum} characters")
    return clean


def _validate_ids(value: Any, field: str, allowed: set[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ApiError(400, f"{field} must be a list")
    unique = list(dict.fromkeys(value))
    unknown = set(unique) - allowed
    if unknown:
        raise ApiError(400, f"Unknown {field}: {', '.join(sorted(unknown))}")
    return unique


def _validate_push_token(value: Any) -> str:
    token = _validate_string(value, "token", 256)
    valid_prefix = token.startswith("ExpoPushToken[") or token.startswith("ExponentPushToken[")
    if not valid_prefix or not token.endswith("]"):
        raise ApiError(400, "token must be a valid Expo push token")
    token_value = token[token.index("[") + 1 : -1]
    if not token_value or not all(character.isalnum() or character in "-_" for character in token_value):
        raise ApiError(400, "token must be a valid Expo push token")
    return token


def _bot_values(value: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    color = value.get("color", previous.get("color", "#58BEAA"))
    if color not in ALLOWED_COLORS:
        raise ApiError(400, "Choose one of the available bot colors")
    return {
        "name": _validate_string(value.get("name", previous.get("name", "")), "name", 48),
        "tagline": _validate_string(value.get("tagline", previous.get("tagline", "")), "tagline", 120, required=False),
        "prompt": _validate_string(value.get("prompt", previous.get("prompt", "")), "prompt", 12_000),
        "color": color,
        "toolIds": _validate_ids(value.get("toolIds", previous.get("toolIds", [])), "toolIds", ALLOWED_TOOL_IDS),
        "skillIds": _validate_ids(value.get("skillIds", previous.get("skillIds", [])), "skillIds", ALLOWED_SKILL_IDS),
    }


def _get_bot(user_id: str, bot_id: str) -> dict:
    item = table.get_item(Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)}, ConsistentRead=True).get("Item")
    if not item:
        raise ApiError(404, "Bot not found")
    return item


def _put_bot(user_id: str, values: dict, bot_id: str | None = None) -> dict:
    bot_id = bot_id or str(uuid.uuid4())
    current = _now()
    item = {
        "pk": _user_pk(user_id),
        "sk": _bot_sk(bot_id),
        "entity": "BOT",
        "id": bot_id,
        "createdAt": values.get("createdAt", current),
        "updatedAt": current,
        "lastMessage": values.get("lastMessage", "Ready when you are."),
        "lastMessageAt": values.get("lastMessageAt", current),
        **{key: values[key] for key in ("name", "tagline", "prompt", "color", "toolIds", "skillIds")},
    }
    table.put_item(Item=item)
    return _public_bot(item)


def _list_bots(user_id: str) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _user_pk(user_id), ":prefix": "BOT#"},
    ).get("Items", [])
    return sorted((_public_bot(item) for item in items), key=lambda item: item["lastMessageAt"], reverse=True)


def _list_turns(user_id: str, bot_id: str, limit: int = 100) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _turn_pk(user_id, bot_id), ":prefix": "TURN#"},
        ScanIndexForward=False,
        Limit=limit,
    ).get("Items", [])
    return sorted(items, key=lambda item: item["createdAt"])


def _messages_from_turns(turns: list[dict]) -> list[dict]:
    messages = []
    for turn in turns:
        messages.append(
            {
                "id": f"{turn['id']}-user",
                "role": "user",
                "text": turn["userText"],
                "createdAt": turn["createdAt"],
                "status": "complete",
            }
        )
        if turn.get("assistantText"):
            messages.append(
                {
                    "id": f"{turn['id']}-assistant",
                    "role": "assistant",
                    "text": turn["assistantText"],
                    "createdAt": turn.get("completedAt", turn["createdAt"]),
                    "status": turn.get("status", "complete").lower(),
                }
            )
        elif turn.get("status") == "PENDING":
            messages.append(
                {
                    "id": f"{turn['id']}-assistant",
                    "role": "assistant",
                    "text": "",
                    "createdAt": turn["createdAt"],
                    "status": "pending",
                }
            )
    return messages


def _bootstrap(user_id: str) -> dict:
    bots = _list_bots(user_id)
    if not bots:
        bots = [_put_bot(user_id, _bot_values(seed)) for seed in DEFAULT_BOTS]
    return {"bots": bots, "tools": TOOL_CATALOG, "skills": SKILL_CATALOG}


def _create_bot(user_id: str, value: dict) -> dict:
    return _put_bot(user_id, _bot_values(value))


def _update_bot(user_id: str, bot_id: str, value: dict) -> dict:
    previous = _get_bot(user_id, bot_id)
    values = _bot_values(value, previous)
    values.update(
        {
            "createdAt": previous["createdAt"],
            "lastMessage": previous.get("lastMessage", "Ready when you are."),
            "lastMessageAt": previous.get("lastMessageAt", previous["createdAt"]),
        }
    )
    return _put_bot(user_id, values, bot_id)


def _send_message(user_id: str, bot_id: str, value: dict) -> dict:
    _get_bot(user_id, bot_id)
    text = _validate_string(value.get("text"), "text", 8_000)
    turn_id = str(uuid.uuid4())
    current = _now()
    item = {
        "pk": _turn_pk(user_id, bot_id),
        "sk": f"TURN#{current}#{turn_id}",
        "entity": "TURN",
        "id": turn_id,
        "botId": bot_id,
        "userId": user_id,
        "userText": text,
        "createdAt": current,
        "status": "PENDING",
    }
    table.put_item(Item=item)
    table.update_item(
        Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
        UpdateExpression="SET lastMessage = :message, lastMessageAt = :now, updatedAt = :now",
        ExpressionAttributeValues={":message": text, ":now": current},
    )
    try:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(
                {"type": "AGENT_REPLY", "userId": user_id, "botId": bot_id, "turnKey": item["sk"]}
            ),
        )
    except Exception:
        table.update_item(
            Key={"pk": item["pk"], "sk": item["sk"]},
            UpdateExpression="SET #status = :status, assistantText = :text, completedAt = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "ERROR",
                ":text": "I could not start that request. Please try again.",
                ":now": _now(),
            },
        )
        raise
    return {"turnId": turn_id, "status": "pending"}


def _register_push_token(user_id: str, value: dict) -> dict:
    token = _validate_push_token(value.get("token"))
    token_id = _push_token_id(token)
    owner_key = _push_owner_key(token_id)
    previous_owner = table.get_item(Key=owner_key, ConsistentRead=True).get("Item", {}).get("userId")
    current = _now()
    expires_at = int(datetime.now(UTC).timestamp()) + 180 * 24 * 60 * 60

    with table.batch_writer() as batch:
        if isinstance(previous_owner, str) and previous_owner and previous_owner != user_id:
            batch.delete_item(Key=_push_token_key(previous_owner, token_id))
        batch.put_item(
            Item={
                **_push_token_key(user_id, token_id),
                "entity": "PUSH_TOKEN",
                "tokenId": token_id,
                "expoPushToken": token,
                "updatedAt": current,
                "expiresAt": expires_at,
            }
        )
        batch.put_item(
            Item={
                **owner_key,
                "entity": "PUSH_TOKEN_OWNER",
                "userId": user_id,
                "updatedAt": current,
                "expiresAt": expires_at,
            }
        )
    return {"registered": True}


def _unregister_push_token(user_id: str, value: dict) -> dict:
    token = _validate_push_token(value.get("token"))
    token_id = _push_token_id(token)
    owner_key = _push_owner_key(token_id)
    owner = table.get_item(Key=owner_key, ConsistentRead=True).get("Item", {}).get("userId")
    with table.batch_writer() as batch:
        batch.delete_item(Key=_push_token_key(user_id, token_id))
        if owner == user_id:
            batch.delete_item(Key=owner_key)
    return {"registered": False}


def _create_share(user_id: str, value: dict) -> dict:
    bot_id = _validate_string(value.get("botId"), "botId", 64)
    scope = value.get("scope", "bot")
    if scope not in {"bot", "chat"}:
        raise ApiError(400, "scope must be bot or chat")
    bot = _public_bot(_get_bot(user_id, bot_id))
    snapshot: dict[str, Any] = {"bot": bot}
    if scope == "chat":
        snapshot["turns"] = [
            {key: turn[key] for key in ("id", "userText", "assistantText", "createdAt", "completedAt", "status") if key in turn}
            for turn in _list_turns(user_id, bot_id)
        ]
    if len(json.dumps(snapshot, default=_json_default)) > 350_000:
        raise ApiError(413, "This conversation is too large to share")

    token = secrets.token_urlsafe(18)
    expires_at = int(datetime.now(UTC).timestamp()) + 30 * 24 * 60 * 60
    table.put_item(
        Item={
            "pk": f"SHARE#{token}",
            "sk": "META",
            "entity": "SHARE",
            "ownerId": user_id,
            "scope": scope,
            "snapshot": snapshot,
            "expiresAt": expires_at,
        }
    )
    return {"url": f"{SHARE_BASE_URL}/{token}", "expiresAt": expires_at}


def _import_share(user_id: str, token: str) -> dict:
    share = table.get_item(Key={"pk": f"SHARE#{token}", "sk": "META"}, ConsistentRead=True).get("Item")
    if not share or int(share.get("expiresAt", 0)) < int(datetime.now(UTC).timestamp()):
        raise ApiError(404, "This share link is invalid or expired")
    source = share["snapshot"]["bot"]
    values = _bot_values({**source, "name": f"{source['name'][:43]} copy"})
    bot = _put_bot(user_id, values)
    for source_turn in share["snapshot"].get("turns", []):
        current = source_turn.get("createdAt", _now())
        turn_id = str(uuid.uuid4())
        table.put_item(
            Item={
                "pk": _turn_pk(user_id, bot["id"]),
                "sk": f"TURN#{current}#{turn_id}",
                "entity": "TURN",
                "id": turn_id,
                "botId": bot["id"],
                "userId": user_id,
                "userText": source_turn.get("userText", ""),
                "assistantText": source_turn.get("assistantText", ""),
                "createdAt": current,
                "completedAt": source_turn.get("completedAt", current),
                "status": "COMPLETE",
            }
        )
    return bot


def handler(event: dict, _context: Any) -> dict:
    try:
        user_id = _user_id(event)
        method = event.get("requestContext", {}).get("http", {}).get("method", "")
        path = event.get("rawPath", "")
        params = event.get("pathParameters") or {}

        if method == "GET" and path == "/bootstrap":
            return _response(200, _bootstrap(user_id))
        if method == "POST" and path == "/bots":
            return _response(201, _create_bot(user_id, _body(event)))
        if method == "PUT" and path.startswith("/bots/"):
            return _response(200, _update_bot(user_id, params.get("botId", ""), _body(event)))
        if method == "GET" and path.endswith("/messages"):
            bot_id = params.get("botId", "")
            _get_bot(user_id, bot_id)
            return _response(200, {"messages": _messages_from_turns(_list_turns(user_id, bot_id))})
        if method == "POST" and path.endswith("/messages"):
            return _response(202, _send_message(user_id, params.get("botId", ""), _body(event)))
        if method == "PUT" and path == "/devices/push-token":
            return _response(200, _register_push_token(user_id, _body(event)))
        if method == "DELETE" and path == "/devices/push-token":
            return _response(200, _unregister_push_token(user_id, _body(event)))
        if method == "POST" and path == "/shares":
            return _response(201, _create_share(user_id, _body(event)))
        if method == "POST" and path.startswith("/shares/") and path.endswith("/import"):
            return _response(201, _import_share(user_id, params.get("token", "")))
        raise ApiError(404, "Route not found")
    except ApiError as exc:
        return _response(exc.status_code, {"message": exc.message})
    except Exception:
        logger.exception("Unhandled API error")
        return _response(500, {"message": "Something went wrong"})
