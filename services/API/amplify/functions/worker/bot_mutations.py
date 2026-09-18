from __future__ import annotations

import json
import uuid
from typing import Any

from shared.catalog import CatalogError
from shared.catalog_rules import MAX_SKILLS_PER_BOT

from .support import _bot_key, catalog, table

MAX_MUTATIONS = 1
MAX_MUTATION_BYTES = 24_000
CREATE_FIELDS = {"name", "tagline", "prompt", "color", "toolIds", "skillIds"}
UPDATE_FIELDS = CREATE_FIELDS
SELF_UPDATE_FIELDS = {"name", "tagline", "prompt", "color", "skillIds"}
CREATE_SKILL_FIELDS = {"name", "description", "instructions", "requiredToolIds"}
CREATE_MEMORY_FIELDS = {"kind", "content"}


def _bot_api():
    from api import bots

    return bots


def _memory_api():
    from api import memories

    return memories


def _mutation(value: Any) -> tuple[str, str, dict]:
    if not isinstance(value, dict):
        raise TypeError("Bot mutation must be an object")
    if set(value) != {"mutationId", "action", "value"}:
        raise ValueError("Bot mutation fields are invalid")
    mutation_id = value.get("mutationId")
    try:
        parsed_id = uuid.UUID(mutation_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Bot mutation ID is invalid") from exc
    if str(parsed_id) != mutation_id:
        raise ValueError("Bot mutation ID is invalid")
    action = value.get("action")
    body = value.get("value")
    if action not in {
        "create",
        "install_template",
        "update",
        "create_skill",
        "update_self",
        "create_memory",
    }:
        raise ValueError("Bot mutation action is unsupported")
    if not isinstance(body, dict):
        raise TypeError("Bot mutation value must be an object")
    return mutation_id, action, body


def _create(user_id: str, mutation_id: str, value: dict) -> None:
    if set(value) != CREATE_FIELDS:
        raise ValueError("Create bot fields are invalid")
    bot_id = f"ai-{mutation_id}"
    existing = table.get_item(Key=_bot_key(user_id, bot_id), ConsistentRead=True).get(
        "Item"
    )
    if existing:
        return
    bot_api = _bot_api()
    values = bot_api._bot_values(user_id, value)
    _reject_new_connection_grants(user_id, values["toolIds"], [])
    bot_api._put_bot(user_id, values, bot_id=bot_id)


def _install(user_id: str, value: dict) -> None:
    if set(value) != {"templateId"}:
        raise ValueError("Install bot fields are invalid")
    template_id = value.get("templateId")
    if not isinstance(template_id, str) or not template_id:
        raise ValueError("Bot template ID is invalid")
    bot_api = _bot_api()
    if any(bot.get("templateId") == template_id for bot in bot_api._list_bots(user_id)):
        return
    bot_api._install_bot_template(user_id, template_id)


def _update(user_id: str, value: dict) -> None:
    if set(value) != {"botId", "changes"}:
        raise ValueError("Update bot fields are invalid")
    bot_id = value.get("botId")
    changes = value.get("changes")
    if not isinstance(bot_id, str) or not bot_id or not isinstance(changes, dict):
        raise ValueError("Update bot value is invalid")
    if not changes or set(changes) - UPDATE_FIELDS:
        raise ValueError("Update bot settings are invalid")
    bot_api = _bot_api()
    target = bot_api._get_bot(user_id, bot_id)
    if target.get("systemRole") == "chief":
        raise ValueError("Chief cannot update its own protected configuration")
    if "toolIds" in changes or "skillIds" in changes:
        values = bot_api._bot_values(user_id, changes, target)
        _reject_new_connection_grants(user_id, values["toolIds"], target.get("toolIds", []))
    bot_api._update_bot(user_id, bot_id, changes)


def _reject_new_connection_grants(
    user_id: str, requested: Any, existing: Any
) -> None:
    if not isinstance(requested, list) or not isinstance(existing, list):
        raise TypeError("Bot tool IDs are invalid")
    if not all(isinstance(tool_id, str) for tool_id in [*requested, *existing]):
        raise ValueError("Bot tool IDs are invalid")
    connection_ids = {item["id"] for item in catalog.list_connections(user_id)}
    if (set(requested) - set(existing)) & connection_ids:
        raise ValueError("Connected accounts must be assigned in bot settings")


def _create_skill(
    user_id: str, invoking_bot: dict, mutation_id: str, value: dict
) -> None:
    fields = set(value)
    if fields not in (CREATE_SKILL_FIELDS, CREATE_SKILL_FIELDS | {"targetBotId"}):
        raise ValueError("Create skill fields are invalid")
    target_bot_id = value.get("targetBotId")
    if target_bot_id is not None and invoking_bot.get("systemRole") != "chief":
        raise ValueError("Only Chief can create a skill for another bot")
    bot_id = target_bot_id if target_bot_id is not None else invoking_bot.get("id")
    if not isinstance(bot_id, str) or not bot_id:
        raise ValueError("The target bot ID is invalid")
    required_tool_ids = value.get("requiredToolIds")
    if not isinstance(required_tool_ids, list) or not all(
        isinstance(tool_id, str) for tool_id in required_tool_ids
    ):
        raise ValueError("Skill requiredToolIds must be a list")

    bot_api = _bot_api()
    target = bot_api._get_bot(user_id, bot_id)
    if target_bot_id is not None and target.get("systemRole") == "chief":
        raise ValueError("Use self skill creation for Chief")
    allowed_tool_ids = {
        tool_id
        for tool_id in target.get("toolIds", [])
        if isinstance(tool_id, str) and tool_id != "bot_manager"
    }
    # A bot can be edited while its agent run is still in progress. The runtime
    # authorizes the mutation against the invocation snapshot, but applying that
    # stale snapshot must never restore a tool the user removed in the meantime.
    # Keep the skill creation successful while narrowing it to the bot's current
    # capabilities. This remains fail-closed: a mutation can never add a tool.
    current_required_tool_ids = [
        tool_id
        for tool_id in dict.fromkeys(required_tool_ids)
        if tool_id in allowed_tool_ids
    ]

    skill_id = f"skill-ai-{mutation_id.replace('-', '')}"
    skill_ids = [
        skill_id_value
        for skill_id_value in target.get("skillIds", [])
        if isinstance(skill_id_value, str)
    ]
    if skill_id not in skill_ids and len(set(skill_ids)) >= MAX_SKILLS_PER_BOT:
        raise ValueError("The target bot already has the maximum number of skills")
    try:
        catalog.get_skill(user_id, skill_id)
    except CatalogError:
        if any(
            str(skill.get("name", "")).strip().casefold()
            == str(value.get("name", "")).strip().casefold()
            for skill in catalog.list_skills(user_id)
        ):
            raise ValueError("A skill with that name already exists")
        catalog.save_skill(
            user_id,
            {
                **{key: value[key] for key in CREATE_SKILL_FIELDS},
                "requiredToolIds": current_required_tool_ids,
                "visibility": "private",
            },
            new_skill_id=skill_id,
        )

    if skill_id not in skill_ids:
        bot_api._update_bot(user_id, bot_id, {"skillIds": [*skill_ids, skill_id]})


def _update_self(user_id: str, invoking_bot: dict, value: dict) -> None:
    if set(value) != {"changes"} or not isinstance(value.get("changes"), dict):
        raise ValueError("Self-update fields are invalid")
    changes = value["changes"]
    if not changes or set(changes) - SELF_UPDATE_FIELDS:
        raise ValueError("Self-update settings are invalid")
    bot_id = invoking_bot.get("id")
    if not isinstance(bot_id, str) or not bot_id:
        raise ValueError("The invoking bot ID is invalid")

    bot_api = _bot_api()
    target = bot_api._get_bot(user_id, bot_id)
    if target.get("systemRole") == "chief" and "color" in changes:
        raise ValueError("Chief's protected color cannot be changed")
    requested_skills = changes.get("skillIds")
    if requested_skills is not None:
        if not isinstance(requested_skills, list) or not all(
            isinstance(skill_id, str) for skill_id in requested_skills
        ):
            raise ValueError("Self-update skillIds must be a list")
        current_tool_ids = {
            tool_id
            for tool_id in target.get("toolIds", [])
            if isinstance(tool_id, str) and tool_id != "bot_manager"
        }
        for skill_id in dict.fromkeys(requested_skills):
            skill = catalog.get_skill(user_id, skill_id)
            required_tool_ids = skill.get("requiredToolIds", [])
            if not isinstance(required_tool_ids, list) or not set(
                required_tool_ids
            ).issubset(current_tool_ids):
                raise ValueError(
                    "A self-attached skill cannot grant this bot a new tool"
                )
    bot_api._update_bot(user_id, bot_id, changes)


def _create_memory(user_id: str, mutation_id: str, value: dict) -> None:
    if set(value) != CREATE_MEMORY_FIELDS:
        raise ValueError("Create memory fields are invalid")
    _memory_api()._create_user_memory(user_id, value, request_identifier=mutation_id)


def apply_bot_mutations(
    user_id: str,
    invoking_bot: dict,
    turn: dict,
    raw_mutations: Any,
) -> None:
    if raw_mutations is None:
        return
    if (
        not isinstance(raw_mutations, list)
        or not raw_mutations
        or len(raw_mutations) > MAX_MUTATIONS
    ):
        raise ValueError("Bot mutations must contain exactly one change")
    if (
        len(json.dumps(raw_mutations, ensure_ascii=False).encode("utf-8"))
        > MAX_MUTATION_BYTES
    ):
        raise ValueError("Bot mutation is too large")
    mutation_id, action, value = _mutation(raw_mutations[0])
    if turn.get("source") == "schedule":
        raise ValueError(
            "Bot, skill, and memory changes are unavailable during scheduled runs"
        )
    if action == "create_skill":
        _create_skill(user_id, invoking_bot, mutation_id, value)
        return
    if action == "update_self":
        _update_self(user_id, invoking_bot, value)
        return
    if action == "create_memory":
        _create_memory(user_id, mutation_id, value)
        return
    if invoking_bot.get("systemRole") != "chief":
        raise ValueError("Bot changes are allowed only from a direct Chief chat")
    if action == "create":
        _create(user_id, mutation_id, value)
    elif action == "install_template":
        _install(user_id, value)
    else:
        _update(user_id, value)


__all__ = ["apply_bot_mutations"]
