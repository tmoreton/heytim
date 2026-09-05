from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from shared.catalog import CatalogError
from shared.invites import invite_url

from .bots import _bot_values, _get_bot, _list_turns, _put_bot
from .groups import _group_items
from .support import (
    PUBLIC_WEB_BASE_URL,
    ApiError,
    _delete_share_record,
    _group_pk,
    _json_default,
    _now,
    _owned_share_records,
    _public_bot,
    _push_owner_key,
    _push_token_id,
    _push_token_key,
    _record_invite_join,
    _register_access_invite,
    _share_token,
    _turn_pk,
    _user_pk,
    _validate_push_token,
    _validate_string,
    catalog,
    table,
)


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
            "description": f"{inviter} invited you to chat with friends and FroggyBots.",
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
            raise ApiError(404, "This FroggyBot invite is invalid or expired")
        bot = share.get("snapshot", {}).get("bot")
        if not isinstance(bot, dict):
            raise ApiError(404, "This FroggyBot invite is invalid")
        return {
            "kind": kind,
            "title": bot.get("name", "Shared FroggyBot"),
            "description": bot.get("tagline", "Add this FroggyBot to your team."),
            "bots": [
                {
                    "name": bot.get("name", "FroggyBot"),
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
                "description", "Add this skill to your FroggyBot team."
            ),
            "bots": [],
            "expiresAt": share["expiresAt"],
        }

    raise ApiError(404, "Invite not found")


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
    private_tool_ids = {
        connection["id"] for connection in catalog.list_connections(user_id)
    }
    for field in ("toolIds", "extraToolIds"):
        bot[field] = [
            tool_id for tool_id in bot.get(field, []) if tool_id not in private_tool_ids
        ]
    skill_snapshots = []
    for skill_id, version in bot.get("skillVersions", {}).items():
        skill = catalog.get_version(skill_id, int(version))
        if skill and not private_tool_ids.intersection(
            skill.get("requiredToolIds", [])
        ):
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
    shared_skill_ids = {skill["id"] for skill in skill_snapshots}
    bot["skillIds"] = [
        skill_id for skill_id in bot.get("skillIds", []) if skill_id in shared_skill_ids
    ]
    bot["skillVersions"] = {
        skill_id: version
        for skill_id, version in bot.get("skillVersions", {}).items()
        if skill_id in shared_skill_ids
    }
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
    created_at = _now()
    expires_at = int(datetime.now(UTC).timestamp()) + 30 * 24 * 60 * 60
    invite_kind = "chat" if scope == "chat" else "bot"
    with table.batch_writer() as batch:
        batch.put_item(
            Item={
                "pk": f"SHARE#{token}",
                "sk": "META",
                "entity": "SHARE",
                "ownerId": user_id,
                "targetId": bot_id,
                "scope": scope,
                "snapshot": snapshot,
                "createdAt": created_at,
                "expiresAt": expires_at,
            }
        )
        batch.put_item(
            Item={
                "pk": _user_pk(user_id),
                "sk": f"SHARE#{token}",
                "entity": "USER_SHARE",
                "kind": invite_kind,
                "targetId": bot_id,
                "createdAt": created_at,
                "expiresAt": expires_at,
            }
        )
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
    values = _bot_values(
        user_id,
        {
            **source,
            "name": f"{source['name'][:43]} copy",
            "toolIds": source.get("extraToolIds", source.get("toolIds", [])),
        },
    )
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
        table.put_item(
            Item={
                "pk": _user_pk(user_id),
                "sk": f"SHARE#{share['token']}",
                "entity": "USER_SHARE",
                "kind": "skill",
                "targetId": skill_id,
                "createdAt": share.get("createdAt", _now()),
                "expiresAt": int(share["expiresAt"]),
            }
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


def _share_summary(item: dict) -> dict | None:
    token = _share_token(item)
    if not token:
        return None
    entity = item.get("entity")
    if entity == "SHARE":
        snapshot = item.get("snapshot", {})
        bot = snapshot.get("bot", {}) if isinstance(snapshot, dict) else {}
        kind = "chat" if item.get("scope") == "chat" else "bot"
        title = (
            bot.get("name", "Shared FroggyBot")
            if isinstance(bot, dict)
            else "Shared FroggyBot"
        )
    elif entity == "SKILL_SHARE":
        snapshot = item.get("snapshot", {})
        kind = "skill"
        title = (
            snapshot.get("name", "Shared skill")
            if isinstance(snapshot, dict)
            else "Shared skill"
        )
    elif entity == "GROUP_INVITE":
        kind = "group"
        group_id = item.get("groupId")
        group = (
            table.get_item(
                Key={"pk": _group_pk(group_id), "sk": "META"}, ConsistentRead=True
            ).get("Item")
            if isinstance(group_id, str)
            else None
        )
        title = group.get("name", "Shared group") if group else "Shared group"
    else:
        return None
    return {
        "token": token,
        "kind": kind,
        "title": title,
        "createdAt": item.get("createdAt"),
        "expiresAt": item.get("expiresAt"),
        "url": invite_url(PUBLIC_WEB_BASE_URL, kind, token),
    }


def _list_shares(user_id: str) -> list[dict]:
    now = int(datetime.now(UTC).timestamp())
    shares = []
    for item in _owned_share_records(user_id):
        if int(item.get("expiresAt", 0)) <= now:
            continue
        summary = _share_summary(item)
        if summary:
            shares.append(summary)
    return sorted(shares, key=lambda item: int(item.get("expiresAt", 0)), reverse=True)


def _revoke_share(user_id: str, token: str) -> dict:
    token = _validate_string(token, "share", 128)
    candidates = (
        (f"SHARE#{token}", "ownerId"),
        (f"SKILL_SHARE#{token}", "ownerId"),
        (f"GROUP_INVITE#{token}", "createdBy"),
    )
    for pk, owner_field in candidates:
        item = table.get_item(Key={"pk": pk, "sk": "META"}, ConsistentRead=True).get(
            "Item"
        )
        if item and item.get(owner_field) == user_id:
            _delete_share_record(user_id, item)
            return {"revoked": True}
    raise ApiError(404, "Share link not found")
