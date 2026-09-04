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
from shared.catalog import CatalogError, CatalogService
from shared.group_chat import ALL_BOTS_REPLY_TARGET, select_group_reply_targets
from shared.invites import invite_token_hash, invite_url

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
INVITE_TABLE_NAME = os.environ.get("INVITE_TABLE_NAME", TABLE_NAME)
QUEUE_URL = os.environ["QUEUE_URL"]
PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://frogbot.expo.app")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
invite_access_table = dynamodb.Table(INVITE_TABLE_NAME)
sqs = boto3.client("sqs")
catalog = CatalogService(table)
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
    expires_at = int(datetime.now(UTC).timestamp()) + 30 * 24 * 60 * 60
    table.put_item(
        Item={
            "pk": f"GROUP_INVITE#{token}",
            "sk": "META",
            "entity": "GROUP_INVITE",
            "groupId": group_id,
            "createdBy": user_id,
            "createdAt": _now(),
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


def _bootstrap(user_id: str) -> dict:
    bots = _list_bots(user_id)
    if not bots:
        bots = [_put_bot(user_id, _bot_values(user_id, seed)) for seed in DEFAULT_BOTS]
    else:
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
                {
                    "type": "AGENT_REPLY",
                    "userId": user_id,
                    "botId": bot_id,
                    "turnKey": item["sk"],
                }
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
        if method == "POST" and path == "/bots":
            return _response(201, _create_bot(user_id, _body(event)))
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
