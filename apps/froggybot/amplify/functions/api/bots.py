from __future__ import annotations

import uuid

from shared.catalog import CatalogError
from shared.cleanup import has_pending_work

from .attachments import _public_file
from .support import (
    ALLOWED_COLORS,
    CHIEF_COLOR,
    CHIEF_SYSTEM_ROLE,
    DEFAULT_BOT_COLOR,
    DEFAULT_BOTS,
    ApiError,
    _bot_sk,
    _group_pk,
    _now,
    _partition_items,
    _public_bot,
    _revoke_bot_shares,
    _turn_pk,
    _user_pk,
    _user_state_key,
    _validate_string,
    catalog,
    table,
)


def _list_groups(user_id: str) -> list[dict]:
    from .groups import _list_groups as list_groups

    return list_groups(user_id)


def _schedule_items(user_id: str, bot_id: str | None = None) -> list[dict]:
    from .schedules import _schedule_items as schedule_items

    return schedule_items(user_id, bot_id)


def _delete_remote_schedule(item: dict) -> None:
    from .schedules import _delete_remote_schedule as delete_remote_schedule

    delete_remote_schedule(item)


def _bot_values(
    user_id: str,
    value: dict,
    previous: dict | None = None,
    system_role: str | None = None,
) -> dict:
    previous = previous or {}
    catalog.sync_official()
    role = system_role or previous.get("systemRole")
    color = value.get("color", previous.get("color", DEFAULT_BOT_COLOR))
    if role == CHIEF_SYSTEM_ROLE:
        color = CHIEF_COLOR
    elif color == CHIEF_COLOR:
        if "color" in value:
            raise ApiError(400, "FroggyBot green is reserved for Chief")
        color = DEFAULT_BOT_COLOR
    if color not in ALLOWED_COLORS:
        raise ApiError(400, "Choose one of the available bot colors")
    try:
        skill_ids = value.get("skillIds", previous.get("skillIds", []))
        skill_versions = catalog.validate_and_pin(
            user_id, skill_ids, previous.get("skillVersions")
        )
        required_tools = []
        for skill_id, version in skill_versions.items():
            skill = catalog.get_version(skill_id, version)
            if skill:
                required_tools.extend(skill.get("requiredToolIds", []))
        if "toolIds" in value:
            extra_tool_ids = catalog.validate_tools(user_id, value.get("toolIds"))
        elif isinstance(previous.get("extraToolIds"), list):
            extra_tool_ids = catalog.validate_tools(user_id, previous["extraToolIds"])
        else:
            required_tool_set = set(required_tools)
            extra_tool_ids = catalog.validate_tools(
                user_id,
                [
                    tool_id
                    for tool_id in previous.get("toolIds", [])
                    if tool_id not in required_tool_set
                ],
            )
        tool_ids = catalog.validate_tools(user_id, [*extra_tool_ids, *required_tools])
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
        "extraToolIds": extra_tool_ids,
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


def _put_bot(
    user_id: str,
    values: dict,
    bot_id: str | None = None,
    system_role: str | None = None,
) -> dict:
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
                "extraToolIds",
                "skillIds",
                "skillVersions",
            )
        },
    }
    if system_role == CHIEF_SYSTEM_ROLE:
        item["systemRole"] = CHIEF_SYSTEM_ROLE
        item["color"] = CHIEF_COLOR
    table.put_item(Item=item)
    return _public_bot(item)


def _list_bots(user_id: str) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _user_pk(user_id), ":prefix": "BOT#"},
    ).get("Items", [])
    bots = sorted(
        (_public_bot(item) for item in items),
        key=lambda item: item["lastMessageAt"],
        reverse=True,
    )
    return sorted(bots, key=lambda item: item.get("systemRole") != CHIEF_SYSTEM_ROLE)


def _ensure_chief(user_id: str, bots: list[dict]) -> list[dict]:
    if any(bot.get("systemRole") == CHIEF_SYSTEM_ROLE for bot in bots):
        return sorted(bots, key=lambda bot: bot.get("systemRole") != CHIEF_SYSTEM_ROLE)

    legacy = next(
        (bot for bot in bots if str(bot.get("name", "")).strip().casefold() == "chief"),
        None,
    )
    if legacy:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(legacy["id"])},
            UpdateExpression="SET systemRole = :role, color = :color, updatedAt = :now",
            ExpressionAttributeValues={
                ":role": CHIEF_SYSTEM_ROLE,
                ":color": CHIEF_COLOR,
                ":now": _now(),
            },
        )
        return sorted(
            [
                {**bot, "systemRole": CHIEF_SYSTEM_ROLE, "color": CHIEF_COLOR}
                if bot["id"] == legacy["id"]
                else bot
                for bot in bots
            ],
            key=lambda bot: bot.get("systemRole") != CHIEF_SYSTEM_ROLE,
        )

    seed = DEFAULT_BOTS[0]
    chief = _put_bot(
        user_id,
        _bot_values(user_id, seed, system_role=CHIEF_SYSTEM_ROLE),
        system_role=CHIEF_SYSTEM_ROLE,
    )
    return [chief, *bots]


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
                **(
                    {
                        "attachments": [
                            _public_file(item)
                            for item in turn["attachments"]
                            if isinstance(item, dict)
                        ]
                    }
                    if isinstance(turn.get("attachments"), list)
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
                    **(
                        {
                            "attachments": [
                                _public_file(item)
                                for item in turn["artifacts"]
                                if isinstance(item, dict)
                            ]
                        }
                        if isinstance(turn.get("artifacts"), list)
                        else {}
                    ),
                }
            )
        elif turn.get("status") in {
            "PENDING",
            "RUNNING",
            "NEEDS_INPUT",
            "AWAITING_APPROVAL",
        }:
            messages.append(
                {
                    "id": f"{turn['id']}-assistant",
                    "role": "assistant",
                    "text": "",
                    "createdAt": turn["createdAt"],
                    "status": str(turn.get("status", "PENDING")).lower(),
                    "activity": turn.get("activity", []),
                    **(
                        {"approvalTools": turn["approvalTools"]}
                        if isinstance(turn.get("approvalTools"), list)
                        else {}
                    ),
                }
            )
    return messages


def _bootstrap(user_id: str) -> dict:
    bots = _list_bots(user_id)
    initialized = table.get_item(Key=_user_state_key(user_id), ConsistentRead=True).get(
        "Item"
    )
    bots = _ensure_chief(user_id, bots)
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
            if isinstance(bot.get("skillVersions"), dict) and isinstance(
                bot.get("extraToolIds"), list
            ):
                migrated.append(bot)
                continue
            values = _bot_values(user_id, {}, bot)
            table.update_item(
                Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot["id"])},
                UpdateExpression=(
                    "SET skillVersions = :versions, skillIds = :skills, "
                    "toolIds = :tools, extraToolIds = :extraTools"
                ),
                ExpressionAttributeValues={
                    ":versions": values["skillVersions"],
                    ":skills": values["skillIds"],
                    ":tools": values["toolIds"],
                    ":extraTools": values["extraToolIds"],
                },
            )
            migrated.append(
                {
                    **bot,
                    **{
                        key: values[key]
                        for key in (
                            "skillVersions",
                            "skillIds",
                            "toolIds",
                            "extraToolIds",
                        )
                    },
                }
            )
        bots = migrated
    return {
        "bots": bots,
        "groups": _list_groups(user_id),
        "tools": catalog.list_tools(user_id),
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
    if catalog.approval_tool_names(user_id, values["toolIds"]) and _schedule_items(
        user_id, bot_id
    ):
        raise ApiError(
            409,
            "Remove this bot's scheduled tasks before enabling interactive tools.",
        )
    return _put_bot(user_id, values, bot_id, previous.get("systemRole"))


def _clear_bot_chat(user_id: str, bot_id: str) -> dict:
    _get_bot(user_id, bot_id)
    turns = _partition_items(_turn_pk(user_id, bot_id))
    if has_pending_work(turns):
        raise ApiError(
            409, "Wait for this FroggyBot to finish before clearing the chat"
        )
    revoked_shares = _revoke_bot_shares(user_id, bot_id, scopes={"chat"})
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
    return {
        "deleted": True,
        "deletedTurns": len(turns),
        "revokedShares": revoked_shares,
    }


def _delete_bot(user_id: str, bot_id: str) -> dict:
    bot = _get_bot(user_id, bot_id)
    if bot.get("systemRole") == CHIEF_SYSTEM_ROLE:
        raise ApiError(409, "Chief coordinates your other bots and cannot be deleted")
    turns = _partition_items(_turn_pk(user_id, bot_id))
    schedules = _schedule_items(user_id, bot_id)
    if has_pending_work(turns):
        raise ApiError(409, "Wait for this FroggyBot to finish before deleting it")

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
                "Wait for this FroggyBot to finish its group reply before deleting it",
            )
        group_bot_keys.append({"pk": group_bot["pk"], "sk": group_bot["sk"]})
        meta = next(
            (item for item in group_items if item.get("entity") == "GROUP"), None
        )
        if meta:
            group_meta_updates.append({**meta, "updatedAt": _now()})

    for schedule_item in schedules:
        _delete_remote_schedule(schedule_item)

    revoked_shares = _revoke_bot_shares(user_id, bot_id)

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
    return {
        "deleted": True,
        "deletedTurns": len(turns),
        "revokedShares": revoked_shares,
    }
