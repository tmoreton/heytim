from __future__ import annotations

import json
import uuid
from typing import Any

from .support import _bot_key, table

MAX_MUTATIONS = 1
MAX_MUTATION_BYTES = 20_000
CREATE_FIELDS = {"name", "tagline", "prompt", "color", "toolIds", "skillIds"}
UPDATE_FIELDS = CREATE_FIELDS


def _bot_api():
    from api import bots

    return bots


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
    if action not in {"create", "install_template", "update"}:
        raise ValueError("Bot mutation action is unsupported")
    if not isinstance(body, dict):
        raise TypeError("Bot mutation value must be an object")
    return mutation_id, action, body


def _create(user_id: str, mutation_id: str, value: dict) -> None:
    if set(value) != CREATE_FIELDS:
        raise ValueError("Create bot fields are invalid")
    bot_id = f"ai-{mutation_id}"
    existing = table.get_item(
        Key=_bot_key(user_id, bot_id), ConsistentRead=True
    ).get("Item")
    if existing:
        return
    bot_api = _bot_api()
    bot_api._put_bot(
        user_id, bot_api._bot_values(user_id, value), bot_id=bot_id
    )


def _install(user_id: str, value: dict) -> None:
    if set(value) != {"templateId"}:
        raise ValueError("Install bot fields are invalid")
    template_id = value.get("templateId")
    if not isinstance(template_id, str) or not template_id:
        raise ValueError("Bot template ID is invalid")
    bot_api = _bot_api()
    if any(
        bot.get("templateId") == template_id
        for bot in bot_api._list_bots(user_id)
    ):
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
    bot_api._update_bot(user_id, bot_id, changes)


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
    if invoking_bot.get("systemRole") != "chief" or turn.get("source") == "schedule":
        raise ValueError("Bot changes are allowed only from a direct Chief chat")
    if len(json.dumps(raw_mutations, ensure_ascii=False).encode("utf-8")) > MAX_MUTATION_BYTES:
        raise ValueError("Bot mutation is too large")
    mutation_id, action, value = _mutation(raw_mutations[0])
    if action == "create":
        _create(user_id, mutation_id, value)
    elif action == "install_template":
        _install(user_id, value)
    else:
        _update(user_id, value)


__all__ = ["apply_bot_mutations"]
