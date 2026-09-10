from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from strands import tool

ALLOWED_COLORS = {
    "#58BEAA",
    "#FFAA34",
    "#6C5CE7",
    "#3984F6",
    "#F46A27",
    "#E95383",
}
MAX_BOTS = 24
MAX_OPTIONS = 100
MAX_MUTATIONS = 1
MAX_NAME_CHARS = 48
MAX_TAGLINE_CHARS = 120
MAX_PROMPT_CHARS = 12_000


def _text(value: Any, field_name: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be text")
    clean = value.strip()
    if required and not clean:
        raise ValueError(f"{field_name} is required")
    if len(clean) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return clean


def _ids(value: Any, field_name: str, allowed: set[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{field_name} must be a list of IDs")
    unique = list(dict.fromkeys(item.strip() for item in value if item.strip()))
    if len(unique) > 12:
        raise ValueError(f"{field_name} can contain at most 12 IDs")
    unknown = set(unique) - allowed
    if unknown:
        raise ValueError(f"Unknown {field_name}: {', '.join(sorted(unknown))}")
    return unique


def _option_list(value: Any, field_name: str) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_OPTIONS:
        raise ValueError(f"botManagement.{field_name} is invalid")
    if not all(isinstance(item, dict) for item in value):
        raise TypeError(f"botManagement.{field_name} entries must be objects")
    return [dict(item) for item in value]


@dataclass
class BotMutationTracker:
    pending: list[dict] = field(default_factory=list)

    def stage(self, action: str, value: dict) -> str:
        if len(self.pending) >= MAX_MUTATIONS:
            raise ValueError("Only one bot change can be made in a single message")
        mutation_id = str(uuid.uuid4())
        self.pending.append(
            {"mutationId": mutation_id, "action": action, "value": value}
        )
        return mutation_id


def bot_management_from_payload(payload: dict) -> dict | None:
    raw = payload.get("botManagement")
    if raw is None:
        return None
    bot = payload.get("bot")
    if (
        not isinstance(raw, dict)
        or not isinstance(bot, dict)
        or bot.get("systemRole") != "chief"
        or payload.get("group") is not None
    ):
        raise ValueError("botManagement is available only to Chief in a direct chat")
    bots = _option_list(raw.get("bots"), "bots")
    if len(bots) > MAX_BOTS:
        raise ValueError(f"botManagement.bots can contain at most {MAX_BOTS} bots")
    return {
        "bots": bots,
        "templates": _option_list(raw.get("templates"), "templates"),
        "tools": _option_list(raw.get("tools"), "tools"),
        "skills": _option_list(raw.get("skills"), "skills"),
    }


def _named_items(items: list[dict], *, include_prompt: bool = False) -> list[dict]:
    allowed = {
        "id",
        "name",
        "tagline",
        "description",
        "category",
        "color",
        "toolIds",
        "skillIds",
        "systemRole",
    }
    if include_prompt:
        allowed.add("prompt")
    return [
        {key: item[key] for key in allowed if key in item}
        for item in items
        if isinstance(item.get("id"), str) and isinstance(item.get("name"), str)
    ]


def bot_management_tools(context: dict, tracker: BotMutationTracker) -> list[Any]:
    bots = context["bots"]
    templates = context["templates"]
    available_tool_ids = {
        item["id"] for item in context["tools"] if isinstance(item.get("id"), str)
    }
    available_skill_ids = {
        item["id"] for item in context["skills"] if isinstance(item.get("id"), str)
    }
    template_ids = {
        item["id"]
        for item in templates
        if isinstance(item.get("id"), str)
    }

    @tool
    def list_bot_options() -> str:
        """List saved bots plus the official templates, tools, and skills available for bot setup."""
        return json.dumps(
            {
                "bots": _named_items(bots, include_prompt=True),
                "templates": _named_items(templates),
                "tools": _named_items(context["tools"]),
                "skills": _named_items(context["skills"]),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @tool
    def install_bot_template(template_id: str) -> str:
        """Install one official bot template by its exact template ID."""
        template_id = _text(template_id, "template_id", 64)
        if template_id == "chief":
            raise ValueError("Chief is already installed")
        if template_id not in template_ids:
            raise ValueError("Unknown bot template ID; call list_bot_options first")
        tracker.stage("install_template", {"templateId": template_id})
        return (
            f"The {template_id} template is ready to be installed when this reply completes. "
            "Finish the response now without calling another tool."
        )

    @tool
    def create_bot(
        name: str,
        tagline: str,
        prompt: str,
        color: str = "#58BEAA",
        tool_ids: list[str] | None = None,
        skill_ids: list[str] | None = None,
    ) -> str:
        """Create one custom bot with a name, role prompt, color, and selected tool and skill IDs."""
        value = {
            "name": _text(name, "name", MAX_NAME_CHARS),
            "tagline": _text(
                tagline, "tagline", MAX_TAGLINE_CHARS, required=False
            ),
            "prompt": _text(prompt, "prompt", MAX_PROMPT_CHARS),
            "color": _text(color, "color", 7),
            "toolIds": _ids(tool_ids, "tool_ids", available_tool_ids),
            "skillIds": _ids(skill_ids, "skill_ids", available_skill_ids),
        }
        if value["color"] not in ALLOWED_COLORS:
            raise ValueError("color must be one of the available non-Chief bot colors")
        if any(
            str(item.get("name", "")).strip().casefold() == value["name"].casefold()
            for item in bots
        ):
            raise ValueError("A bot with that name already exists")
        tracker.stage("create", value)
        return (
            f"{value['name']} is ready to be created when this reply completes. "
            "Finish the response now without calling another tool."
        )

    @tool
    def update_bot(
        bot_id_or_name: str,
        name: str | None = None,
        tagline: str | None = None,
        prompt: str | None = None,
        color: str | None = None,
        tool_ids: list[str] | None = None,
        skill_ids: list[str] | None = None,
    ) -> str:
        """Update one non-Chief bot's name, tagline, role prompt, color, tools, or skills."""
        identifier = _text(bot_id_or_name, "bot_id_or_name", 80).casefold()
        matches = [
            item
            for item in bots
            if str(item.get("id", "")).casefold() == identifier
            or str(item.get("name", "")).strip().casefold() == identifier
        ]
        if len(matches) != 1:
            raise ValueError("Bot not found or name is ambiguous; call list_bot_options first")
        target = matches[0]
        if target.get("systemRole") == "chief":
            raise ValueError("Chief cannot edit its own protected configuration")
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = _text(name, "name", MAX_NAME_CHARS)
        if tagline is not None:
            changes["tagline"] = _text(
                tagline, "tagline", MAX_TAGLINE_CHARS, required=False
            )
        if prompt is not None:
            changes["prompt"] = _text(prompt, "prompt", MAX_PROMPT_CHARS)
        if color is not None:
            changes["color"] = _text(color, "color", 7)
            if changes["color"] not in ALLOWED_COLORS:
                raise ValueError("color must be one of the available non-Chief bot colors")
        if tool_ids is not None:
            changes["toolIds"] = _ids(
                tool_ids, "tool_ids", available_tool_ids
            )
        if skill_ids is not None:
            changes["skillIds"] = _ids(
                skill_ids, "skill_ids", available_skill_ids
            )
        if not changes:
            raise ValueError("Provide at least one bot setting to update")
        tracker.stage(
            "update", {"botId": str(target["id"]), "changes": changes}
        )
        return (
            f"{target['name']} is ready to be updated when this reply completes. "
            "Finish the response now without calling another tool."
        )

    return [list_bot_options, install_bot_template, create_bot, update_bot]


__all__ = [
    "BotMutationTracker",
    "bot_management_from_payload",
    "bot_management_tools",
]
