from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from shared.cleanup import has_pending_work, purge_group
from shared.invites import invite_token_hash, invite_url

from .bots import _get_bot
from .support import (
    CHIEF_SYSTEM_ROLE,
    FILES_BUCKET_NAME,
    PUBLIC_WEB_BASE_URL,
    ApiError,
    _active_access_invite,
    _bot_color,
    _group_pk,
    _now,
    _partition_items,
    _public_bot,
    _record_invite_join,
    _register_access_invite,
    _user_pk,
    _validate_string,
    invite_access_table,
    s3,
    table,
)

logger = logging.getLogger(__name__)


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
                "name": item.get("name", "FroggyBot user"),
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
                "color": _bot_color(item),
                "systemRole": item.get("systemRole"),
            }
            for item in items
            if item.get("entity") == "GROUP_BOT"
        ),
        key=lambda item: (
            item.get("systemRole") != CHIEF_SYSTEM_ROLE,
            item["name"].lower(),
        ),
    )
    return {
        "id": meta["id"],
        "name": meta["name"],
        "memory": meta.get("memory", ""),
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
        "color": _bot_color(bot),
        **(
            {"systemRole": CHIEF_SYSTEM_ROLE}
            if bot.get("systemRole") == CHIEF_SYSTEM_ROLE
            else {}
        ),
        "addedAt": _now(),
    }


def _create_group(user_id: str, display_name: str, value: dict) -> dict:
    name = _validate_string(value.get("name"), "name", 64)
    memory = _validate_string(value.get("memory", ""), "memory", 4_000, required=False)
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
        "memory": memory,
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
    memory = _validate_string(
        value.get("memory", meta.get("memory", "")),
        "memory",
        4_000,
        required=False,
    )
    current_bot_ids = {
        item["botId"] for item in items if item.get("entity") == "GROUP_BOT"
    }
    bot_ids = _validate_bot_ids(value.get("botIds", list(current_bot_ids)))
    selected_bots = [_public_bot(_get_bot(user_id, bot_id)) for bot_id in bot_ids]
    current = _now()
    with table.batch_writer() as batch:
        batch.put_item(
            Item={**meta, "name": name, "memory": memory, "updatedAt": current}
        )
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
                "createdBy": user_id,
                "createdAt": created_at,
                "expiresAt": expires_at,
            }
        )
        batch.put_item(
            Item={
                "pk": _user_pk(user_id),
                "sk": f"INVITE#{token}",
                "entity": "USER_SHARE",
                "kind": "group",
                "targetId": group_id,
                "createdAt": created_at,
                "expiresAt": expires_at,
            }
        )
    _register_access_invite("group", token, user_id, expires_at, group_id)
    return {
        "url": invite_url(PUBLIC_WEB_BASE_URL, "group", token),
        "expiresAt": expires_at,
    }


def _join_group(user_id: str, display_name: str, token: str) -> dict:
    token = _validate_string(token, "invite", 128)
    access = _active_access_invite("group", token)
    invite = table.get_item(
        Key={"pk": f"GROUP_INVITE#{token}", "sk": "META"}, ConsistentRead=True
    ).get("Item")
    if not invite or int(invite.get("expiresAt", 0)) < int(
        datetime.now(UTC).timestamp()
    ):
        raise ApiError(404, "This group invite is invalid or expired")
    group_id = invite.get("groupId")
    if not isinstance(group_id, str) or access.get("targetId") != group_id:
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
            409, "Wait for the FroggyBots to finish before deleting this group"
        )
    _purge_group(group_id, items)
    return {"deleted": True}


def _purge_group(group_id: str, items: list[dict] | None = None) -> None:
    items = items or _partition_items(_group_pk(group_id))
    purge_group(
        table,
        invite_access_table,
        s3,
        FILES_BUCKET_NAME,
        group_id,
        items,
    )
