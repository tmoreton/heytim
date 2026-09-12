from __future__ import annotations

import json
import uuid

from boto3.dynamodb.conditions import Attr
from shared.account_state import (
    AccountInactiveError,
    UserItemConflictError,
    put_user_item_while_account_active,
)
from shared.browser_session_store import BrowserSessionError, context_key
from shared.browser_sessions import delete_browser_context
from shared.catalog import CatalogError
from shared.cleanup import has_pending_work
from shared.connection_providers import connection_providers
from shared.memory_identity import direct_session_id, memory_actor_id
from shared.work_state import processing_summary

from .bot_documents import _delete_bot_documents, _preserve_bot_documents
from .bot_roles import (
    ALLOWED_COLORS,
    CHIEF_COLOR,
    CHIEF_SYSTEM_ROLE,
    DEFAULT_BOT_COLOR,
)
from .bot_setup import ensure_chief, install_bot_template
from .direct_messages import _list_turn_page
from .message_views import messages_from_turns
from .support import (
    QUEUE_URL,
    ApiError,
    _bot_sk,
    _group_pk,
    _now,
    _partition_items,
    _public_bot,
    _recent_partition_items,
    _revoke_bot_shares,
    _turn_pk,
    _user_pk,
    _user_state_key,
    _validate_string,
    catalog,
    sqs,
    table,
)


def _messages_from_turns(turns: list[dict]) -> list[dict]:
    return messages_from_turns(turns)


LEGACY_BOT_TEMPLATE_IDS = {
    "starter-trip-planner": "trip-planner",
    "starter-event-planner": "event-planner",
    "starter-research-reports": "research-reports",
}


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
        raw_always_allowed = value.get(
            "alwaysAllowedToolIds", previous.get("alwaysAllowedToolIds", [])
        )
        if not isinstance(raw_always_allowed, list) or not all(
            isinstance(tool_id, str) for tool_id in raw_always_allowed
        ):
            raise ApiError(400, "alwaysAllowedToolIds must be a list")
        interactive_tool_ids = set(catalog.approval_tool_ids(user_id, tool_ids))
        raw_previously_allowed = previous.get("alwaysAllowedToolIds", [])
        previously_allowed = (
            set(raw_previously_allowed)
            if isinstance(raw_previously_allowed, list)
            and all(isinstance(tool_id, str) for tool_id in raw_previously_allowed)
            else set()
        )
        requested_always_allowed = set(raw_always_allowed) & previously_allowed
        always_allowed_tool_ids = [
            tool_id
            for tool_id in tool_ids
            if tool_id in requested_always_allowed and tool_id in interactive_tool_ids
        ]
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
        "alwaysAllowedToolIds": always_allowed_tool_ids,
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
    require_active_account: bool = False,
    create_only: bool = False,
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
                "alwaysAllowedToolIds",
                "skillIds",
                "skillVersions",
            )
        },
    }
    if system_role == CHIEF_SYSTEM_ROLE:
        item["systemRole"] = CHIEF_SYSTEM_ROLE
        item["color"] = CHIEF_COLOR
    for key in ("templateId", "templateVersion"):
        if key in values:
            item[key] = values[key]
    if require_active_account:
        try:
            put_user_item_while_account_active(
                table,
                user_id,
                item,
                require_absent=create_only,
            )
        except AccountInactiveError as exc:
            raise ApiError(
                409, "Account deletion is still in progress. Please try again."
            ) from exc
        except UserItemConflictError:
            existing = table.get_item(
                Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
                ConsistentRead=True,
            ).get("Item")
            if existing:
                return _public_bot(existing)
            raise
    else:
        table.put_item(Item=item)
    return _public_bot(item)


def _list_bots(user_id: str) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _user_pk(user_id), ":prefix": "BOT#"},
    ).get("Items", [])
    bots = sorted(
        (
            {
                **_public_bot(item),
                **processing_summary(
                    _recent_partition_items(
                        _turn_pk(user_id, item["id"]), "TURN#", 1
                    )
                ),
            }
            for item in items
        ),
        key=lambda item: item["lastMessageAt"],
        reverse=True,
    )
    return sorted(bots, key=lambda item: item.get("systemRole") != CHIEF_SYSTEM_ROLE)


def _ensure_chief(user_id: str, bots: list[dict]) -> list[dict]:
    return ensure_chief(user_id, bots, _bot_values, _put_bot)


def _install_bot_template(user_id: str, template_id: str) -> dict:
    return install_bot_template(
        user_id, template_id, _list_bots, _bot_values, _put_bot
    )


def _list_turns(user_id: str, bot_id: str, limit: int = 100) -> list[dict]:
    return _list_turn_page(user_id, bot_id, limit=limit)[0]


def _bootstrap(user_id: str) -> dict:
    bots = _list_bots(user_id)
    initialized = table.get_item(Key=_user_state_key(user_id), ConsistentRead=True).get(
        "Item"
    )
    needs_bot_onboarding = not initialized and not bots
    bots = _ensure_chief(user_id, bots)
    if not initialized:
        try:
            table.put_item(
                Item={
                    **_user_state_key(user_id),
                    "entity": "USER_STATE",
                    "initializedAt": _now(),
                },
                ConditionExpression=Attr("pk").not_exists(),
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            # A concurrent bootstrap initialized the same deterministic state.
            pass
    if bots:
        migrated = []
        for bot in bots:
            legacy_template_id = LEGACY_BOT_TEMPLATE_IDS.get(bot["id"])
            if legacy_template_id and not bot.get("templateId"):
                table.update_item(
                    Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot["id"])},
                    UpdateExpression=(
                        "SET templateId = :templateId, "
                        "templateVersion = :templateVersion"
                    ),
                    ExpressionAttributeValues={
                        ":templateId": legacy_template_id,
                        ":templateVersion": 1,
                    },
                )
                bot = {
                    **bot,
                    "templateId": legacy_template_id,
                    "templateVersion": 1,
                }
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
                            "alwaysAllowedToolIds",
                        )
                    },
                }
            )
        bots = migrated
    return {
        "bots": bots,
        "botTemplates": catalog.list_bot_templates(user_id),
        "needsBotOnboarding": needs_bot_onboarding,
        "groups": _list_groups(user_id),
        "connectionProviders": connection_providers(),
        "tools": catalog.list_tools(user_id),
        "retiredToolIds": catalog.retired_tool_ids(),
        "skills": catalog.list_skills(user_id),
    }


def _create_bot(
    user_id: str,
    value: dict,
    *,
    bot_id: str | None = None,
    require_active_account: bool = False,
    create_only: bool = False,
) -> dict:
    return _put_bot(
        user_id,
        _bot_values(user_id, value),
        bot_id=bot_id,
        require_active_account=require_active_account,
        create_only=create_only,
    )


def _update_bot(user_id: str, bot_id: str, value: dict) -> dict:
    previous = _get_bot(user_id, bot_id)
    values = _bot_values(user_id, value, previous)
    values.update(
        {
            "createdAt": previous["createdAt"],
            "lastMessage": previous.get("lastMessage", "Ready when you are."),
            "lastMessageAt": previous.get("lastMessageAt", previous["createdAt"]),
            **(
                {"templateId": previous["templateId"]}
                if "templateId" in previous
                else {}
            ),
            **(
                {"templateVersion": previous["templateVersion"]}
                if "templateVersion" in previous
                else {}
            ),
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


def _forget_bot_conversation(user_id: str, bot_id: str) -> dict[str, bool]:
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(
            {
                "type": "DELETE_MEMORY_SESSION",
                "actorId": memory_actor_id(user_id),
                "sessionId": direct_session_id(user_id, bot_id),
            }
        ),
    )
    return {"queued": True}


def _clear_bot_chat(user_id: str, bot_id: str, *, forget_memory: bool = False) -> dict:
    _get_bot(user_id, bot_id)
    turns = _partition_items(_turn_pk(user_id, bot_id))
    if has_pending_work(turns):
        raise ApiError(
            409, "Wait for this FroggyBot to finish before clearing the chat"
        )
    forgotten_memory = (
        _forget_bot_conversation(user_id, bot_id)
        if forget_memory
        else {"queued": False}
    )
    preserved_documents = _preserve_bot_documents(user_id, bot_id, turns)
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
        "preservedDocuments": preserved_documents,
        "revokedShares": revoked_shares,
        "forgottenMemory": forgotten_memory,
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

    try:
        delete_browser_context(table, user_id, bot_id)
    except BrowserSessionError as exc:
        raise ApiError(exc.status_code, exc.message, code=exc.code) from None
    forgotten_memory = _forget_bot_conversation(user_id, bot_id)

    for schedule_item in schedules:
        _delete_remote_schedule(schedule_item)

    revoked_shares = _revoke_bot_shares(user_id, bot_id)
    document_deletion = _delete_bot_documents(user_id, bot_id, turns)

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
        batch.delete_item(Key=context_key(user_id, bot_id))
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
        "forgottenMemory": forgotten_memory,
        **document_deletion,
    }
