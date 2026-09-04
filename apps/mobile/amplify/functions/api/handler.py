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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.config import Config
from shared.catalog import CatalogError, CatalogService
from shared.cleanup import group_invite_records, group_member_ids, has_pending_work
from shared.group_chat import ALL_BOTS_REPLY_TARGET, select_group_reply_targets
from shared.invites import invite_token_hash, invite_url
from shared.schedules import DAYS_OF_WEEK, schedule_expression, scheduler_name

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
INVITE_TABLE_NAME = os.environ.get("INVITE_TABLE_NAME", TABLE_NAME)
QUEUE_URL = os.environ["QUEUE_URL"]
QUEUE_ARN = os.environ["QUEUE_ARN"]
SCHEDULE_DLQ_ARN = os.environ["SCHEDULE_DLQ_ARN"]
SCHEDULE_GROUP_NAME = os.environ["SCHEDULE_GROUP_NAME"]
SCHEDULE_ROLE_ARN = os.environ["SCHEDULE_ROLE_ARN"]
PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://frogbot.expo.app")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
invite_access_table = dynamodb.Table(INVITE_TABLE_NAME)
sqs = boto3.client("sqs")
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
    return "FrogBot user"


def _push_token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _push_token_key(user_id: str, token_id: str) -> dict:
    return {"pk": _user_pk(user_id), "sk": f"PUSH#{token_id}"}


def _push_owner_key(token_id: str) -> dict:
    return {"pk": f"PUSH_TOKEN#{token_id}", "sk": "OWNER"}


def _partition_items(partition_key: str, sort_prefix: str | None = None) -> list[dict]:
    expression = "pk = :pk"
    values = {":pk": partition_key}
    if sort_prefix is not None:
        expression += " AND begins_with(sk, :prefix)"
        values[":prefix"] = sort_prefix
    paginator = table.meta.client.get_paginator("query")
    items = []
    for page in paginator.paginate(
        TableName=TABLE_NAME,
        KeyConditionExpression=expression,
        ExpressionAttributeValues=values,
        ConsistentRead=True,
    ):
        items.extend(page.get("Items", []))
    return items


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


def _bot_values(user_id: str, value: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    catalog.sync_official()
    color = value.get("color", previous.get("color", "#58BEAA"))
    if color not in ALLOWED_COLORS:
        raise ApiError(400, "Choose one of the available bot colors")
    try:
        skill_ids = value.get("skillIds", previous.get("skillIds", []))
        skill_versions = catalog.validate_and_pin(
            user_id, skill_ids, previous.get("skillVersions")
        )
        tool_ids = catalog.validate_tools(
            value.get("toolIds", previous.get("toolIds", []))
        )
        required_tools = []
        for skill_id, version in skill_versions.items():
            skill = catalog.get_version(skill_id, version)
            if skill:
                required_tools.extend(skill.get("requiredToolIds", []))
        tool_ids = catalog.validate_tools([*tool_ids, *required_tools])
    except CatalogError as exc:
        raise ApiError(400, str(exc)) from exc
    return {
        "name": _validate_string(
            value.get("name", previous.get("name", "")), "name", 48
        ),
        "tagline": _validate_string(
            value.get("tagline", previous.get("tagline", "")),
            "tagline",
            120,
            required=False,
        ),
        "prompt": _validate_string(
            value.get("prompt", previous.get("prompt", "")), "prompt", 12_000
        ),
        "color": color,
        "toolIds": tool_ids,
        "skillIds": list(skill_versions),
        "skillVersions": skill_versions,
    }


def _get_bot(user_id: str, bot_id: str) -> dict:
    item = table.get_item(
        Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)}, ConsistentRead=True
    ).get("Item")
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
        **{
            key: values[key]
            for key in (
                "name",
                "tagline",
                "prompt",
                "color",
                "toolIds",
                "skillIds",
                "skillVersions",
            )
        },
    }
    table.put_item(Item=item)
    return _public_bot(item)


def _list_bots(user_id: str) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _user_pk(user_id), ":prefix": "BOT#"},
    ).get("Items", [])
    return sorted(
        (_public_bot(item) for item in items),
        key=lambda item: item["lastMessageAt"],
        reverse=True,
    )


def _list_turns(user_id: str, bot_id: str, limit: int = 100) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": _turn_pk(user_id, bot_id),
            ":prefix": "TURN#",
        },
        ScanIndexForward=False,
        Limit=limit,
        ConsistentRead=True,
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
                **(
                    {
                        "source": "schedule",
                        "scheduleName": turn.get("scheduleName", "Scheduled task"),
                    }
                    if turn.get("source") == "schedule"
                    else {}
                ),
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
                    "activity": turn.get("activity", []),
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
                    "activity": turn.get("activity", []),
                }
            )
    return messages


def _group_items(group_id: str) -> list[dict]:
    meta = table.get_item(
        Key={"pk": _group_pk(group_id), "sk": "META"}, ConsistentRead=True
    ).get("Item")
    items = [meta] if meta else []
    for prefix in ("BOT#", "USER#"):
        items.extend(
            table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={
                    ":pk": _group_pk(group_id),
                    ":prefix": prefix,
                },
                ConsistentRead=True,
            ).get("Items", [])
        )
    return items


def _group_member(items: list[dict], user_id: str) -> dict | None:
    return next((item for item in items if item.get("sk") == f"USER#{user_id}"), None)


def _require_group_member(
    user_id: str, group_id: str, *, owner: bool = False
) -> tuple[dict, list[dict]]:
    items = _group_items(group_id)
    meta = next((item for item in items if item.get("sk") == "META"), None)
    member = _group_member(items, user_id)
    if not meta or not member:
        raise ApiError(404, "Group not found")
    if owner and meta.get("ownerId") != user_id:
        raise ApiError(403, "Only the group owner can make that change")
    return meta, items


def _public_group(user_id: str, group_id: str, items: list[dict] | None = None) -> dict:
    items = items or _group_items(group_id)
    meta = next((item for item in items if item.get("sk") == "META"), None)
    if not meta or not _group_member(items, user_id):
        raise ApiError(404, "Group not found")
    members = sorted(
        (
            {
                "id": item["userId"],
                "name": item.get("name", "FrogBot user"),
                "role": item.get("role", "member"),
            }
            for item in items
            if item.get("entity") == "GROUP_USER"
        ),
        key=lambda item: (item["role"] != "owner", item["name"].lower()),
    )
    bots = sorted(
        (
            {
                "id": item["botId"],
                "ownerId": item["botOwnerId"],
                "name": item["name"],
                "tagline": item.get("tagline", ""),
                "color": item.get("color", "#007A3D"),
            }
            for item in items
            if item.get("entity") == "GROUP_BOT"
        ),
        key=lambda item: item["name"].lower(),
    )
    return {
        "id": meta["id"],
        "name": meta["name"],
        "ownerId": meta["ownerId"],
        "currentUserId": user_id,
        "isOwner": meta["ownerId"] == user_id,
        "createdAt": meta["createdAt"],
        "updatedAt": meta["updatedAt"],
        "lastMessage": meta.get("lastMessage", "Start the conversation."),
        "lastMessageAt": meta.get("lastMessageAt", meta["createdAt"]),
        "members": members,
        "bots": bots,
    }


def _list_groups(user_id: str) -> list[dict]:
    pointers = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _user_pk(user_id), ":prefix": "GROUP#"},
    ).get("Items", [])
    groups = []
    for pointer in pointers:
        group_id = pointer.get("groupId")
        if not isinstance(group_id, str):
            continue
        try:
            groups.append(_public_group(user_id, group_id))
        except ApiError:
            logger.warning("Ignoring stale group membership for user")
    return sorted(groups, key=lambda item: item["lastMessageAt"], reverse=True)


def _validate_bot_ids(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ApiError(400, "botIds must be a list")
    bot_ids = list(dict.fromkeys(item for item in value if item))
    if len(bot_ids) > 12:
        raise ApiError(400, "A group can have up to 12 bots")
    return bot_ids


def _group_bot_item(group_id: str, owner_id: str, bot: dict) -> dict:
    return {
        "pk": _group_pk(group_id),
        "sk": f"BOT#{bot['id']}",
        "entity": "GROUP_BOT",
        "botId": bot["id"],
        "botOwnerId": owner_id,
        "name": bot["name"],
        "tagline": bot.get("tagline", ""),
        "color": bot.get("color", "#007A3D"),
        "addedAt": _now(),
    }


def _create_group(user_id: str, display_name: str, value: dict) -> dict:
    name = _validate_string(value.get("name"), "name", 64)
    bot_ids = _validate_bot_ids(value.get("botIds", []))
    selected_bots = [_public_bot(_get_bot(user_id, bot_id)) for bot_id in bot_ids]
    group_id = str(uuid.uuid4())
    current = _now()
    meta = {
        "pk": _group_pk(group_id),
        "sk": "META",
        "entity": "GROUP",
        "id": group_id,
        "name": name,
        "ownerId": user_id,
        "createdAt": current,
        "updatedAt": current,
        "lastMessage": "Start the conversation.",
        "lastMessageAt": current,
    }
    member = {
        "pk": _group_pk(group_id),
        "sk": f"USER#{user_id}",
        "entity": "GROUP_USER",
        "userId": user_id,
        "name": display_name,
        "role": "owner",
        "joinedAt": current,
    }
    pointer = {
        "pk": _user_pk(user_id),
        "sk": f"GROUP#{group_id}",
        "entity": "USER_GROUP",
        "groupId": group_id,
        "joinedAt": current,
    }
    with table.batch_writer() as batch:
        batch.put_item(Item=meta)
        batch.put_item(Item=member)
        batch.put_item(Item=pointer)
        for bot in selected_bots:
            batch.put_item(Item=_group_bot_item(group_id, user_id, bot))
    return _public_group(user_id, group_id)


def _update_group(user_id: str, group_id: str, value: dict) -> dict:
    meta, items = _require_group_member(user_id, group_id, owner=True)
    name = _validate_string(value.get("name", meta["name"]), "name", 64)
    current_bot_ids = {
        item["botId"] for item in items if item.get("entity") == "GROUP_BOT"
    }
    bot_ids = _validate_bot_ids(value.get("botIds", list(current_bot_ids)))
    selected_bots = [_public_bot(_get_bot(user_id, bot_id)) for bot_id in bot_ids]
    current = _now()
    with table.batch_writer() as batch:
        batch.put_item(Item={**meta, "name": name, "updatedAt": current})
        for bot_id in current_bot_ids - set(bot_ids):
            batch.delete_item(Key={"pk": _group_pk(group_id), "sk": f"BOT#{bot_id}"})
        for bot in selected_bots:
            batch.put_item(Item=_group_bot_item(group_id, user_id, bot))
    return _public_group(user_id, group_id)


def _create_group_invite(user_id: str, group_id: str) -> dict:
    _require_group_member(user_id, group_id)
    token = secrets.token_urlsafe(18)
    token_hash = invite_token_hash(token)
    expires_at = int(datetime.now(UTC).timestamp()) + 30 * 24 * 60 * 60
    created_at = _now()
    with table.batch_writer() as batch:
        batch.put_item(
            Item={
                "pk": f"GROUP_INVITE#{token}",
                "sk": "META",
                "entity": "GROUP_INVITE",
                "groupId": group_id,
                "createdBy": user_id,
                "createdAt": created_at,
                "expiresAt": expires_at,
            }
        )
        batch.put_item(
            Item={
                "pk": _group_pk(group_id),
                "sk": f"INVITE#{token}",
                "entity": "GROUP_INVITE_POINTER",
                "token": token,
                "tokenHash": token_hash,
                "createdAt": created_at,
                "expiresAt": expires_at,
            }
        )
    _register_access_invite("group", token, user_id, expires_at, group_id)
    return {
        "url": invite_url(PUBLIC_WEB_BASE_URL, "group", token),
        "expiresAt": expires_at,
    }


def _public_invite_preview(kind: str, token: str) -> dict:
    kind = _validate_string(kind, "kind", 16)
    token = _validate_string(token, "invite", 128)
    if kind == "group":
        invite = table.get_item(
            Key={"pk": f"GROUP_INVITE#{token}", "sk": "META"}, ConsistentRead=True
        ).get("Item")
        if not invite or int(invite.get("expiresAt", 0)) < int(
            datetime.now(UTC).timestamp()
        ):
            raise ApiError(404, "This group invite is invalid or expired")
        group_id = invite.get("groupId")
        if not isinstance(group_id, str):
            raise ApiError(404, "This group invite is invalid")
        items = _group_items(group_id)
        meta = next((item for item in items if item.get("sk") == "META"), None)
        if not meta:
            raise ApiError(404, "This group no longer exists")
        bots = [
            {
                "name": item["name"],
                "tagline": item.get("tagline", ""),
                "color": item.get("color", "#007A3D"),
            }
            for item in items
            if item.get("entity") == "GROUP_BOT"
        ]
        members = [item for item in items if item.get("entity") == "GROUP_USER"]
        inviter = next(
            (
                item.get("name")
                for item in members
                if item.get("userId") == invite.get("createdBy")
            ),
            "A friend",
        )
        return {
            "kind": "group",
            "title": meta["name"],
            "description": f"{inviter} invited you to chat with friends and FrogBots.",
            "inviterName": inviter,
            "peopleCount": len(members),
            "bots": sorted(bots, key=lambda item: item["name"].lower()),
            "expiresAt": invite["expiresAt"],
        }

    if kind in {"bot", "chat"}:
        share = table.get_item(
            Key={"pk": f"SHARE#{token}", "sk": "META"}, ConsistentRead=True
        ).get("Item")
        if not share or int(share.get("expiresAt", 0)) < int(
            datetime.now(UTC).timestamp()
        ):
            raise ApiError(404, "This FrogBot invite is invalid or expired")
        bot = share.get("snapshot", {}).get("bot")
        if not isinstance(bot, dict):
            raise ApiError(404, "This FrogBot invite is invalid")
        return {
            "kind": kind,
            "title": bot.get("name", "Shared FrogBot"),
            "description": bot.get("tagline", "Add this FrogBot to your team."),
            "bots": [
                {
                    "name": bot.get("name", "FrogBot"),
                    "tagline": bot.get("tagline", ""),
                    "color": bot.get("color", "#007A3D"),
                }
            ],
            "expiresAt": share["expiresAt"],
        }

    if kind == "skill":
        share = table.get_item(
            Key={"pk": f"SKILL_SHARE#{token}", "sk": "META"}, ConsistentRead=True
        ).get("Item")
        if not share or int(share.get("expiresAt", 0)) < int(
            datetime.now(UTC).timestamp()
        ):
            raise ApiError(404, "This skill invite is invalid or expired")
        skill = share.get("snapshot")
        if not isinstance(skill, dict):
            raise ApiError(404, "This skill invite is invalid")
        return {
            "kind": "skill",
            "title": skill.get("name", "Shared skill"),
            "description": skill.get(
                "description", "Add this skill to your FrogBot team."
            ),
            "bots": [],
            "expiresAt": share["expiresAt"],
        }

    raise ApiError(404, "Invite not found")


def _join_group(user_id: str, display_name: str, token: str) -> dict:
    token = _validate_string(token, "invite", 128)
    invite = table.get_item(
        Key={"pk": f"GROUP_INVITE#{token}", "sk": "META"}, ConsistentRead=True
    ).get("Item")
    if not invite or int(invite.get("expiresAt", 0)) < int(
        datetime.now(UTC).timestamp()
    ):
        raise ApiError(404, "This group invite is invalid or expired")
    group_id = invite.get("groupId")
    if not isinstance(group_id, str):
        raise ApiError(404, "This group invite is invalid")
    items = _group_items(group_id)
    if not next((item for item in items if item.get("sk") == "META"), None):
        raise ApiError(404, "This group no longer exists")
    if not _group_member(items, user_id):
        current = _now()
        with table.batch_writer() as batch:
            batch.put_item(
                Item={
                    "pk": _group_pk(group_id),
                    "sk": f"USER#{user_id}",
                    "entity": "GROUP_USER",
                    "userId": user_id,
                    "name": display_name,
                    "role": "member",
                    "joinedAt": current,
                }
            )
            batch.put_item(
                Item={
                    "pk": _user_pk(user_id),
                    "sk": f"GROUP#{group_id}",
                    "entity": "USER_GROUP",
                    "groupId": group_id,
                    "joinedAt": current,
                }
            )
        _record_invite_join("group", token)
    return _public_group(user_id, group_id)


def _list_group_messages(user_id: str, group_id: str, limit: int = 100) -> list[dict]:
    _require_group_member(user_id, group_id)
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _group_pk(group_id), ":prefix": "MESSAGE#"},
        ScanIndexForward=False,
        Limit=limit,
        ConsistentRead=True,
    ).get("Items", [])
    messages = []
    for item in reversed(items):
        messages.append(
            {
                key: value
                for key, value in {
                    "id": item.get("id"),
                    "role": "assistant" if item.get("authorType") == "bot" else "user",
                    "authorType": item.get("authorType"),
                    "authorId": item.get("authorId"),
                    "authorName": item.get("authorName"),
                    "authorColor": item.get("authorColor"),
                    "isMine": item.get("authorType") == "user"
                    and item.get("authorId") == user_id,
                    "text": item.get("text", ""),
                    "createdAt": item.get("createdAt"),
                    "status": str(item.get("status", "COMPLETE")).lower(),
                    "activity": item.get("activity", []),
                }.items()
                if value is not None
            }
        )
    return messages


def _send_group_message(
    user_id: str, display_name: str, group_id: str, value: dict
) -> dict:
    meta, items = _require_group_member(user_id, group_id)
    text = _validate_string(value.get("text"), "text", 8_000)
    reply_bot_id = value.get("replyBotId")
    if reply_bot_id is not None and (
        not isinstance(reply_bot_id, str) or not reply_bot_id
    ):
        raise ApiError(400, "replyBotId must identify a bot in this group")
    reply_bots = select_group_reply_targets(items, reply_bot_id)
    if reply_bot_id and not reply_bots:
        raise ApiError(400, "Choose a bot that belongs to this group")

    current = _now()
    message_id = str(uuid.uuid4())
    message = {
        "pk": _group_pk(group_id),
        "sk": _group_message_sk(current, message_id),
        "entity": "GROUP_MESSAGE",
        "id": message_id,
        "authorType": "user",
        "authorId": user_id,
        "authorName": display_name,
        "text": text,
        "createdAt": current,
        "status": "COMPLETE",
    }
    replies = []
    for order, group_bot in enumerate(reply_bots, start=1):
        reply_id = str(uuid.uuid4())
        replies.append(
            {
                "pk": _group_pk(group_id),
                "sk": _group_message_sk(current, reply_id, order),
                "entity": "GROUP_MESSAGE",
                "id": reply_id,
                "authorType": "bot",
                "authorId": group_bot["botId"],
                "authorName": group_bot["name"],
                "authorColor": group_bot.get("color", "#007A3D"),
                "botOwnerId": group_bot["botOwnerId"],
                "roundId": message_id,
                "roundPosition": order,
                "roundSize": len(reply_bots),
                "text": "",
                "createdAt": current,
                "status": "PENDING",
            }
        )
    with table.batch_writer() as batch:
        batch.put_item(Item=message)
        for reply in replies:
            batch.put_item(Item=reply)
        batch.put_item(
            Item={
                **meta,
                "lastMessage": text,
                "lastMessageAt": current,
                "updatedAt": current,
            }
        )

    if replies:
        try:
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(
                    {
                        "type": "GROUP_AGENT_ROUND",
                        "requestedBy": user_id,
                        "groupId": group_id,
                        "replyTarget": ALL_BOTS_REPLY_TARGET
                        if reply_bot_id == ALL_BOTS_REPLY_TARGET
                        else "bot",
                        "replies": [
                            {
                                "botId": reply["authorId"],
                                "botOwnerId": reply["botOwnerId"],
                                "replyKey": reply["sk"],
                            }
                            for reply in replies
                        ],
                    }
                ),
            )
        except Exception:
            with table.batch_writer() as batch:
                for reply in replies:
                    batch.put_item(
                        Item={
                            **reply,
                            "status": "ERROR",
                            "text": "I could not start that request. Please try again.",
                        }
                    )
            raise
    return {
        "messageId": message_id,
        "replyId": replies[0]["id"] if replies else None,
        "replyIds": [reply["id"] for reply in replies],
    }


def _remove_group_member(user_id: str, group_id: str, member_id: str) -> dict:
    meta, items = _require_group_member(user_id, group_id)
    if member_id != user_id and meta.get("ownerId") != user_id:
        raise ApiError(403, "Only the group owner can remove other people")
    if member_id == meta.get("ownerId"):
        raise ApiError(400, "The group owner cannot leave the group")
    if not _group_member(items, member_id):
        raise ApiError(404, "Group member not found")
    with table.batch_writer() as batch:
        batch.delete_item(Key={"pk": _group_pk(group_id), "sk": f"USER#{member_id}"})
        batch.delete_item(Key={"pk": _user_pk(member_id), "sk": f"GROUP#{group_id}"})
    return {"removed": True}


def _delete_group(user_id: str, group_id: str) -> dict:
    _require_group_member(user_id, group_id, owner=True)
    items = _partition_items(_group_pk(group_id))
    if has_pending_work(items):
        raise ApiError(
            409, "Wait for the FrogBots to finish before deleting this group"
        )
    members = group_member_ids(items)
    invites = group_invite_records(items)
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
        for member_id in members:
            batch.delete_item(
                Key={"pk": _user_pk(member_id), "sk": f"GROUP#{group_id}"}
            )
        for token, _token_hash in invites:
            batch.delete_item(Key={"pk": f"GROUP_INVITE#{token}", "sk": "META"})
    if invites:
        with invite_access_table.batch_writer() as batch:
            for _token, token_hash in invites:
                batch.delete_item(Key={"tokenHash": token_hash})
    return {"deleted": True}


def _bootstrap(user_id: str) -> dict:
    bots = _list_bots(user_id)
    initialized = table.get_item(Key=_user_state_key(user_id), ConsistentRead=True).get(
        "Item"
    )
    if not bots and not initialized:
        bots = [_put_bot(user_id, _bot_values(user_id, seed)) for seed in DEFAULT_BOTS]
    if not initialized:
        table.put_item(
            Item={
                **_user_state_key(user_id),
                "entity": "USER_STATE",
                "initializedAt": _now(),
            }
        )
    if bots:
        migrated = []
        for bot in bots:
            if isinstance(bot.get("skillVersions"), dict):
                migrated.append(bot)
                continue
            values = _bot_values(user_id, bot, bot)
            table.update_item(
                Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot["id"])},
                UpdateExpression="SET skillVersions = :versions, skillIds = :skills, toolIds = :tools",
                ExpressionAttributeValues={
                    ":versions": values["skillVersions"],
                    ":skills": values["skillIds"],
                    ":tools": values["toolIds"],
                },
            )
            migrated.append(
                {
                    **bot,
                    **{
                        key: values[key]
                        for key in ("skillVersions", "skillIds", "toolIds")
                    },
                }
            )
        bots = migrated
    return {
        "bots": bots,
        "groups": _list_groups(user_id),
        "tools": catalog.list_tools(),
        "skills": catalog.list_skills(user_id),
    }


def _create_bot(user_id: str, value: dict) -> dict:
    return _put_bot(user_id, _bot_values(user_id, value))


def _update_bot(user_id: str, bot_id: str, value: dict) -> dict:
    previous = _get_bot(user_id, bot_id)
    values = _bot_values(user_id, value, previous)
    values.update(
        {
            "createdAt": previous["createdAt"],
            "lastMessage": previous.get("lastMessage", "Ready when you are."),
            "lastMessageAt": previous.get("lastMessageAt", previous["createdAt"]),
        }
    )
    return _put_bot(user_id, values, bot_id)


def _schedule_items(user_id: str, bot_id: str | None = None) -> list[dict]:
    items = _partition_items(_user_pk(user_id), "SCHEDULE#")
    if bot_id is not None:
        items = [item for item in items if item.get("botId") == bot_id]
    return sorted(items, key=lambda item: item.get("createdAt", ""), reverse=True)


def _get_schedule(user_id: str, bot_id: str, schedule_id: str) -> dict:
    item = table.get_item(
        Key=_schedule_key(user_id, schedule_id), ConsistentRead=True
    ).get("Item")
    if not item or item.get("botId") != bot_id:
        raise ApiError(404, "Scheduled task not found")
    return item


def _schedule_values(value: dict, previous: dict | None = None) -> dict:
    prior = previous or {}
    frequency = value.get("frequency", prior.get("frequency", "daily"))
    if frequency not in {"daily", "weekly"}:
        raise ApiError(400, "frequency must be daily or weekly")

    time_value = _validate_string(value.get("time", prior.get("time", "09:00")), "time", 5)
    parts = time_value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ApiError(400, "Enter a valid time")
    hour, minute = (int(part) for part in parts)
    if hour > 23 or minute > 59:
        raise ApiError(400, "Enter a valid time")

    timezone = _validate_string(
        value.get("timezone", prior.get("timezone", "UTC")), "timezone", 64
    )
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ApiError(400, "Choose a valid timezone") from exc

    enabled = value.get("enabled", prior.get("enabled", True))
    if not isinstance(enabled, bool):
        raise ApiError(400, "enabled must be true or false")

    values = {
        "name": _validate_string(value.get("name", prior.get("name")), "name", 64),
        "prompt": _validate_string(
            value.get("prompt", prior.get("prompt")), "prompt", 8_000
        ),
        "frequency": frequency,
        "time": f"{hour:02d}:{minute:02d}",
        "timezone": timezone,
        "enabled": enabled,
    }
    if frequency == "weekly":
        day_of_week = value.get("dayOfWeek", prior.get("dayOfWeek", "MON"))
        if day_of_week not in DAYS_OF_WEEK:
            raise ApiError(400, "Choose a valid day of the week")
        values["dayOfWeek"] = day_of_week
    return values


def _schedule_target(item: dict) -> dict:
    return {
        "Arn": QUEUE_ARN,
        "RoleArn": SCHEDULE_ROLE_ARN,
        "Input": json.dumps(
            {
                "type": "SCHEDULED_AGENT_REPLY",
                "userId": item["userId"],
                "botId": item["botId"],
                "scheduleId": item["id"],
                "executionId": "<aws.scheduler.execution-id>",
                "scheduledTime": "<aws.scheduler.scheduled-time>",
            },
            separators=(",", ":"),
        ),
        "DeadLetterConfig": {"Arn": SCHEDULE_DLQ_ARN},
        "RetryPolicy": {
            "MaximumEventAgeInSeconds": 3_600,
            "MaximumRetryAttempts": 3,
        },
    }


def _remote_schedule_request(item: dict) -> dict:
    return {
        "Name": item["schedulerName"],
        "GroupName": SCHEDULE_GROUP_NAME,
        "Description": "Runs a recurring FrogBot task.",
        "ScheduleExpression": schedule_expression(
            item["frequency"], item["time"], item.get("dayOfWeek")
        ),
        "ScheduleExpressionTimezone": item["timezone"],
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "State": "ENABLED" if item["enabled"] else "DISABLED",
        "Target": _schedule_target(item),
    }


def _create_remote_schedule(item: dict) -> None:
    scheduler.create_schedule(**_remote_schedule_request(item))


def _update_remote_schedule(item: dict) -> None:
    try:
        scheduler.update_schedule(**_remote_schedule_request(item))
    except scheduler.exceptions.ResourceNotFoundException:
        _create_remote_schedule(item)


def _delete_remote_schedule(item: dict) -> None:
    try:
        scheduler.delete_schedule(
            Name=item["schedulerName"], GroupName=SCHEDULE_GROUP_NAME
        )
    except scheduler.exceptions.ResourceNotFoundException:
        return


def _list_schedules(user_id: str, bot_id: str) -> list[dict]:
    _get_bot(user_id, bot_id)
    return [_public_schedule(item) for item in _schedule_items(user_id, bot_id)]


def _create_schedule(user_id: str, bot_id: str, value: dict) -> dict:
    _get_bot(user_id, bot_id)
    if len(_schedule_items(user_id)) >= SCHEDULE_LIMIT:
        raise ApiError(400, f"You can create up to {SCHEDULE_LIMIT} scheduled tasks")
    schedule_id = str(uuid.uuid4())
    current = _now()
    item = {
        **_schedule_key(user_id, schedule_id),
        "entity": "SCHEDULE",
        "id": schedule_id,
        "userId": user_id,
        "botId": bot_id,
        "schedulerName": scheduler_name(user_id, schedule_id),
        "createdAt": current,
        "updatedAt": current,
        **_schedule_values(value),
    }
    table.put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
    try:
        _create_remote_schedule(item)
    except Exception:
        table.delete_item(Key=_schedule_key(user_id, schedule_id))
        raise
    return _public_schedule(item)


def _update_schedule(
    user_id: str, bot_id: str, schedule_id: str, value: dict
) -> dict:
    previous = _get_schedule(user_id, bot_id, schedule_id)
    item = {
        **previous,
        **_schedule_values(value, previous),
        "updatedAt": _now(),
    }
    if item["frequency"] == "daily":
        item.pop("dayOfWeek", None)
    table.put_item(Item=item)
    try:
        _update_remote_schedule(item)
    except Exception:
        table.put_item(Item=previous)
        raise
    return _public_schedule(item)


def _delete_schedule(user_id: str, bot_id: str, schedule_id: str) -> dict:
    item = _get_schedule(user_id, bot_id, schedule_id)
    _delete_remote_schedule(item)
    table.delete_item(Key=_schedule_key(user_id, schedule_id))
    return {"deleted": True}


def _clear_bot_chat(user_id: str, bot_id: str) -> dict:
    _get_bot(user_id, bot_id)
    turns = _partition_items(_turn_pk(user_id, bot_id))
    if has_pending_work(turns):
        raise ApiError(409, "Wait for this FrogBot to finish before clearing the chat")
    with table.batch_writer() as batch:
        for turn in turns:
            batch.delete_item(Key={"pk": turn["pk"], "sk": turn["sk"]})
    current = _now()
    table.update_item(
        Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
        UpdateExpression="SET lastMessage = :message, lastMessageAt = :now, updatedAt = :now",
        ExpressionAttributeValues={
            ":message": "Ready when you are.",
            ":now": current,
        },
    )
    return {"deleted": True, "deletedTurns": len(turns)}


def _delete_bot(user_id: str, bot_id: str) -> dict:
    _get_bot(user_id, bot_id)
    turns = _partition_items(_turn_pk(user_id, bot_id))
    schedules = _schedule_items(user_id, bot_id)
    if has_pending_work(turns):
        raise ApiError(409, "Wait for this FrogBot to finish before deleting it")

    group_bot_keys = []
    group_meta_updates = []
    for pointer in _partition_items(_user_pk(user_id), "GROUP#"):
        group_id = pointer.get("groupId")
        if not isinstance(group_id, str):
            continue
        group_items = _partition_items(_group_pk(group_id))
        group_bot = next(
            (
                item
                for item in group_items
                if item.get("entity") == "GROUP_BOT"
                and item.get("botId") == bot_id
                and item.get("botOwnerId") == user_id
            ),
            None,
        )
        if not group_bot:
            continue
        if has_pending_work(group_items, bot_id=bot_id):
            raise ApiError(
                409,
                "Wait for this FrogBot to finish its group reply before deleting it",
            )
        group_bot_keys.append({"pk": group_bot["pk"], "sk": group_bot["sk"]})
        meta = next(
            (item for item in group_items if item.get("entity") == "GROUP"), None
        )
        if meta:
            group_meta_updates.append({**meta, "updatedAt": _now()})

    for schedule_item in schedules:
        _delete_remote_schedule(schedule_item)

    with table.batch_writer() as batch:
        for turn in turns:
            batch.delete_item(Key={"pk": turn["pk"], "sk": turn["sk"]})
        for schedule_item in schedules:
            batch.delete_item(
                Key={"pk": schedule_item["pk"], "sk": schedule_item["sk"]}
            )
        for key in group_bot_keys:
            batch.delete_item(Key=key)
        for meta in group_meta_updates:
            batch.put_item(Item=meta)
        batch.delete_item(Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)})
        batch.put_item(
            Item={
                **_user_state_key(user_id),
                "entity": "USER_STATE",
                "initializedAt": _now(),
            }
        )
    return {"deleted": True, "deletedTurns": len(turns)}


def _start_bot_turn(
    user_id: str, bot_id: str, text: str, schedule_item: dict | None = None
) -> dict:
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
    if schedule_item:
        item.update(
            {
                "source": "schedule",
                "scheduleId": schedule_item["id"],
                "scheduleName": schedule_item["name"],
            }
        )
    table.put_item(Item=item)
    if schedule_item:
        try:
            table.update_item(
                Key=_schedule_key(user_id, schedule_item["id"]),
                UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
                ConditionExpression=Attr("pk").exists(),
                ExpressionAttributeValues={":now": current, ":status": "pending"},
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
            raise ApiError(404, "Scheduled task not found") from exc
    try:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
            UpdateExpression="SET lastMessage = :message, lastMessageAt = :now, updatedAt = :now",
            ConditionExpression=Attr("pk").exists(),
            ExpressionAttributeValues={":message": text, ":now": current},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
        if schedule_item:
            try:
                table.update_item(
                    Key=_schedule_key(user_id, schedule_item["id"]),
                    UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
                    ConditionExpression=Attr("pk").exists(),
                    ExpressionAttributeValues={":now": current, ":status": "error"},
                )
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                pass
        raise ApiError(404, "Bot not found") from exc
    try:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(
                {
                    "type": "AGENT_REPLY",
                    "userId": user_id,
                    "botId": bot_id,
                    "turnKey": item["sk"],
                }
            ),
        )
    except Exception:
        failed_at = _now()
        table.update_item(
            Key={"pk": item["pk"], "sk": item["sk"]},
            UpdateExpression="SET #status = :status, assistantText = :text, completedAt = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "ERROR",
                ":text": "I could not start that request. Please try again.",
                ":now": failed_at,
            },
        )
        if schedule_item:
            try:
                table.update_item(
                    Key=_schedule_key(user_id, schedule_item["id"]),
                    UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
                    ConditionExpression=Attr("pk").exists(),
                    ExpressionAttributeValues={":now": failed_at, ":status": "error"},
                )
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                pass
        raise
    return {"turnId": turn_id, "status": "pending"}


def _send_message(user_id: str, bot_id: str, value: dict) -> dict:
    _get_bot(user_id, bot_id)
    text = _validate_string(value.get("text"), "text", 8_000)
    return _start_bot_turn(user_id, bot_id, text)


def _run_schedule_now(user_id: str, bot_id: str, schedule_id: str) -> dict:
    schedule_item = _get_schedule(user_id, bot_id, schedule_id)
    _get_bot(user_id, bot_id)
    return _start_bot_turn(
        user_id, bot_id, schedule_item["prompt"], schedule_item
    )


def _register_push_token(user_id: str, value: dict) -> dict:
    token = _validate_push_token(value.get("token"))
    token_id = _push_token_id(token)
    owner_key = _push_owner_key(token_id)
    previous_owner = (
        table.get_item(Key=owner_key, ConsistentRead=True).get("Item", {}).get("userId")
    )
    current = _now()
    expires_at = int(datetime.now(UTC).timestamp()) + 180 * 24 * 60 * 60

    with table.batch_writer() as batch:
        if (
            isinstance(previous_owner, str)
            and previous_owner
            and previous_owner != user_id
        ):
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
    owner = (
        table.get_item(Key=owner_key, ConsistentRead=True).get("Item", {}).get("userId")
    )
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
    skill_snapshots = []
    for skill_id, version in bot.get("skillVersions", {}).items():
        skill = catalog.get_version(skill_id, int(version))
        if skill:
            skill_snapshots.append(
                {
                    key: skill[key]
                    for key in (
                        "id",
                        "version",
                        "name",
                        "description",
                        "requiredToolIds",
                        "source",
                        "visibility",
                        "editable",
                        "ownerId",
                    )
                    if key in skill
                }
            )
    snapshot: dict[str, Any] = {"bot": bot, "skills": skill_snapshots}
    if scope == "chat":
        snapshot["turns"] = [
            {
                key: turn[key]
                for key in (
                    "id",
                    "userText",
                    "assistantText",
                    "createdAt",
                    "completedAt",
                    "status",
                )
                if key in turn
            }
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
    invite_kind = "chat" if scope == "chat" else "bot"
    _register_access_invite(invite_kind, token, user_id, expires_at, bot_id)
    return {
        "url": invite_url(PUBLIC_WEB_BASE_URL, invite_kind, token),
        "expiresAt": expires_at,
    }


def _import_share(user_id: str, token: str) -> dict:
    share = table.get_item(
        Key={"pk": f"SHARE#{token}", "sk": "META"}, ConsistentRead=True
    ).get("Item")
    if not share or int(share.get("expiresAt", 0)) < int(datetime.now(UTC).timestamp()):
        raise ApiError(404, "This share link is invalid or expired")
    for skill in share["snapshot"].get("skills", []):
        try:
            catalog.install_snapshot(user_id, skill)
        except CatalogError as exc:
            raise ApiError(400, str(exc)) from exc
    source = share["snapshot"]["bot"]
    values = _bot_values(user_id, {**source, "name": f"{source['name'][:43]} copy"})
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
    _record_invite_join("chat" if share.get("scope") == "chat" else "bot", token)
    return bot


def _get_skill(user_id: str, skill_id: str) -> dict:
    try:
        return catalog.get_skill(user_id, skill_id)
    except CatalogError as exc:
        raise ApiError(404, str(exc)) from exc


def _save_skill(user_id: str, value: dict, skill_id: str | None = None) -> dict:
    try:
        return catalog.save_skill(user_id, value, skill_id)
    except CatalogError as exc:
        raise ApiError(400, str(exc)) from exc


def _share_skill(user_id: str, skill_id: str) -> dict:
    try:
        share = catalog.create_share(user_id, skill_id)
        _register_access_invite(
            "skill", share["token"], user_id, int(share["expiresAt"]), skill_id
        )
        return {key: value for key, value in share.items() if key != "token"}
    except CatalogError as exc:
        raise ApiError(400, str(exc)) from exc


def _import_skill(user_id: str, token: str) -> dict:
    try:
        skill = catalog.import_share(user_id, token)
        _record_invite_join("skill", token)
        return skill
    except CatalogError as exc:
        raise ApiError(404, str(exc)) from exc


def handler(event: dict, _context: Any) -> dict:
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method", "")
        path = event.get("rawPath", "")
        params = event.get("pathParameters") or {}

        if method == "GET" and path.startswith("/public/invites/"):
            return _response(
                200,
                _public_invite_preview(params.get("kind", ""), params.get("token", "")),
            )

        user_id = _user_id(event)

        display_name = _display_name(event)

        if method == "GET" and path == "/bootstrap":
            return _response(200, _bootstrap(user_id))
        if method == "POST" and path == "/groups":
            return _response(201, _create_group(user_id, display_name, _body(event)))
        if method == "PUT" and path.startswith("/groups/") and "/members/" not in path:
            return _response(
                200, _update_group(user_id, params.get("groupId", ""), _body(event))
            )
        if (
            method == "GET"
            and path.startswith("/groups/")
            and path.endswith("/messages")
        ):
            return _response(
                200,
                {"messages": _list_group_messages(user_id, params.get("groupId", ""))},
            )
        if (
            method == "POST"
            and path.startswith("/groups/")
            and path.endswith("/messages")
        ):
            return _response(
                202,
                _send_group_message(
                    user_id, display_name, params.get("groupId", ""), _body(event)
                ),
            )
        if (
            method == "POST"
            and path.startswith("/groups/")
            and path.endswith("/invites")
        ):
            return _response(
                201, _create_group_invite(user_id, params.get("groupId", ""))
            )
        if (
            method == "POST"
            and path.startswith("/group-invites/")
            and path.endswith("/join")
        ):
            return _response(
                201, _join_group(user_id, display_name, params.get("token", ""))
            )
        if method == "DELETE" and "/members/" in path:
            return _response(
                200,
                _remove_group_member(
                    user_id, params.get("groupId", ""), params.get("memberId", "")
                ),
            )
        if method == "DELETE" and path.startswith("/groups/"):
            return _response(200, _delete_group(user_id, params.get("groupId", "")))
        if method == "POST" and path == "/bots":
            return _response(201, _create_bot(user_id, _body(event)))
        if method == "GET" and path.endswith("/schedules"):
            return _response(
                200,
                {"schedules": _list_schedules(user_id, params.get("botId", ""))},
            )
        if method == "POST" and path.endswith("/schedules"):
            return _response(
                201,
                _create_schedule(user_id, params.get("botId", ""), _body(event)),
            )
        if method == "POST" and path.endswith("/run") and "/schedules/" in path:
            return _response(
                202,
                _run_schedule_now(
                    user_id,
                    params.get("botId", ""),
                    params.get("scheduleId", ""),
                ),
            )
        if method == "PUT" and "/schedules/" in path:
            return _response(
                200,
                _update_schedule(
                    user_id,
                    params.get("botId", ""),
                    params.get("scheduleId", ""),
                    _body(event),
                ),
            )
        if method == "DELETE" and "/schedules/" in path:
            return _response(
                200,
                _delete_schedule(
                    user_id,
                    params.get("botId", ""),
                    params.get("scheduleId", ""),
                ),
            )
        if method == "PUT" and path.startswith("/bots/"):
            return _response(
                200, _update_bot(user_id, params.get("botId", ""), _body(event))
            )
        if method == "GET" and path.startswith("/bots/") and path.endswith("/messages"):
            bot_id = params.get("botId", "")
            _get_bot(user_id, bot_id)
            return _response(
                200, {"messages": _messages_from_turns(_list_turns(user_id, bot_id))}
            )
        if (
            method == "POST"
            and path.startswith("/bots/")
            and path.endswith("/messages")
        ):
            return _response(
                202, _send_message(user_id, params.get("botId", ""), _body(event))
            )
        if (
            method == "DELETE"
            and path.startswith("/bots/")
            and path.endswith("/messages")
        ):
            return _response(200, _clear_bot_chat(user_id, params.get("botId", "")))
        if method == "DELETE" and path.startswith("/bots/"):
            return _response(200, _delete_bot(user_id, params.get("botId", "")))
        if method == "PUT" and path == "/devices/push-token":
            return _response(200, _register_push_token(user_id, _body(event)))
        if method == "DELETE" and path == "/devices/push-token":
            return _response(200, _unregister_push_token(user_id, _body(event)))
        if method == "POST" and path == "/shares":
            return _response(201, _create_share(user_id, _body(event)))
        if (
            method == "POST"
            and path.startswith("/shares/")
            and path.endswith("/import")
        ):
            return _response(201, _import_share(user_id, params.get("token", "")))
        if method == "POST" and path == "/skills":
            return _response(201, _save_skill(user_id, _body(event)))
        if method == "GET" and path.startswith("/skills/"):
            return _response(200, _get_skill(user_id, params.get("skillId", "")))
        if (
            method == "PUT"
            and path.startswith("/skills/")
            and not path.endswith("/share")
        ):
            return _response(
                200, _save_skill(user_id, _body(event), params.get("skillId", ""))
            )
        if method == "POST" and path.startswith("/skills/") and path.endswith("/share"):
            return _response(201, _share_skill(user_id, params.get("skillId", "")))
        if (
            method == "POST"
            and path.startswith("/skill-shares/")
            and path.endswith("/import")
        ):
            return _response(201, _import_skill(user_id, params.get("token", "")))
        raise ApiError(404, "Route not found")
    except ApiError as exc:
        return _response(exc.status_code, {"message": exc.message})
    except Exception:
        logger.exception("Unhandled API error")
        return _response(500, {"message": "Something went wrong"})
