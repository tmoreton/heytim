from __future__ import annotations

import re

from strands.vended_plugins.skills import Skill

from .device_tools import DEVICE_TOOL_SPECS
from .local_tools import CUSTOM_TOOLS
from .mcp_connections import (
    validated_connection_binding,
    validated_connection_bundle_binding,
)
from .provider_connections import validated_provider_binding

MAX_SKILL_INSTRUCTIONS_CHARS = 20_000
MAX_SKILLS = 12
MAX_TOOLS = 12
STAN_BUILTIN_TOOLS = {"web_fetch"}
STAN_PLUGINS = {"todos"}
STAN_SUBAGENTS = {"generalist"}
AGENTCORE_TOOLS = {"browser", "code_interpreter"}
CONTEXTUAL_LOCAL_TOOLS = {
    "bot_manager",
    "image_generator",
    "meme_lord",
}


def dynamic_skills(bot: dict) -> list[Skill]:
    raw_skills = bot.get("skills")
    if raw_skills is None:
        return []
    if not isinstance(raw_skills, list) or len(raw_skills) > MAX_SKILLS:
        raise ValueError(f"bot.skills must be a list with at most {MAX_SKILLS} items")

    skills = []
    seen = set()
    for raw in raw_skills:
        if not isinstance(raw, dict):
            raise TypeError("each bot skill must be an object")
        skill_id = raw.get("id")
        name = raw.get("name")
        description = raw.get("description")
        instructions = raw.get("instructions")
        if not isinstance(skill_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,63}", skill_id
        ):
            raise ValueError("bot skill id is invalid")
        if skill_id in seen:
            raise ValueError(f"bot skill id is duplicated: {skill_id}")
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError(f"bot skill name is invalid: {skill_id}")
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > 240
        ):
            raise ValueError(f"bot skill description is invalid: {skill_id}")
        if (
            not isinstance(instructions, str)
            or not instructions.strip()
            or len(instructions) > MAX_SKILL_INSTRUCTIONS_CHARS
        ):
            raise ValueError(f"bot skill instructions are invalid: {skill_id}")
        seen.add(skill_id)
        skills.append(
            Skill(
                name=skill_id,
                description=description.strip(),
                instructions=instructions.strip(),
                metadata={
                    "display_name": name.strip(),
                    "version": int(raw.get("version", 1)),
                },
            )
        )
    return skills


def tool_bindings(bot: dict) -> list[dict]:
    raw_bindings = bot.get("tools")
    if raw_bindings is None:
        raise ValueError("bot.tools must be resolved by the catalog service")
    if not isinstance(raw_bindings, list) or len(raw_bindings) > MAX_TOOLS:
        raise ValueError(f"bot.tools must be a list with at most {MAX_TOOLS} items")

    bindings = []
    seen = set()
    for raw in raw_bindings:
        if not isinstance(raw, dict):
            raise TypeError("each bot tool must be an object")
        tool_id = raw.get("id")
        runtime = raw.get("runtime")
        if not isinstance(tool_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_]{0,63}", tool_id
        ):
            raise ValueError("bot tool id is invalid")
        if tool_id in seen:
            raise ValueError(f"bot tool id is duplicated: {tool_id}")
        if not isinstance(runtime, dict):
            raise TypeError(f"bot tool runtime is invalid: {tool_id}")

        kind = runtime.get("kind")
        if kind == "gateway":
            operations = runtime.get("operations")
            if (
                not isinstance(operations, list)
                or not 1 <= len(operations) <= 8
                or len(set(operations)) != len(operations)
                or any(
                    not isinstance(operation, str)
                    or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,127}", operation)
                    for operation in operations
                )
            ):
                raise ValueError(f"gateway operations are invalid: {tool_id}")
            binding = {"id": tool_id, "kind": kind, "operations": operations}
        elif kind == "mcp":
            binding = validated_connection_binding(tool_id, runtime)
        elif kind == "mcp_bundle":
            binding = validated_connection_bundle_binding(tool_id, runtime)
        elif kind == "provider_api":
            binding = validated_provider_binding(tool_id, runtime)
        elif kind == "device":
            platform = runtime.get("platform")
            operations = runtime.get("operations")
            interactive = runtime.get("interactiveOperations", [])
            if (
                platform not in {"ios", "macos"}
                or not isinstance(operations, list)
                or not 1 <= len(operations) <= 8
                or not all(isinstance(operation, str) for operation in operations)
                or len(set(operations)) != len(operations)
                or any(
                    not isinstance(operation, str)
                    or operation not in DEVICE_TOOL_SPECS
                    or DEVICE_TOOL_SPECS[operation]["platform"] != platform
                    for operation in operations
                )
                or not isinstance(interactive, list)
                or not all(isinstance(operation, str) for operation in interactive)
                or len(set(interactive)) != len(interactive)
                or not set(interactive).issubset(operations)
            ):
                raise ValueError(f"device operations are invalid: {tool_id}")
            binding = {
                "id": tool_id,
                "kind": kind,
                "platform": platform,
                "operations": operations,
                "interactiveOperations": interactive,
            }
        else:
            name = runtime.get("name")
            allowed = {
                "agentcore": AGENTCORE_TOOLS,
                "local": set(CUSTOM_TOOLS) | CONTEXTUAL_LOCAL_TOOLS,
                "stan_builtin": STAN_BUILTIN_TOOLS,
                "stan_plugin": STAN_PLUGINS,
                "stan_subagent": STAN_SUBAGENTS,
            }.get(kind)
            if not allowed or name not in allowed:
                raise ValueError(f"bot tool runtime is unsupported: {tool_id}")
            binding = {"id": tool_id, "kind": kind, "name": name}
        seen.add(tool_id)
        bindings.append(binding)
    return bindings


def validate_skill_selection(bot: dict, skills: list[Skill]) -> None:
    skill_ids = bot.get("skillIds", [])
    if not isinstance(skill_ids, list) or not all(
        isinstance(value, str) for value in skill_ids
    ):
        raise TypeError("bot.skillIds must be a list of strings")
    if bot.get("skills") is None:
        raise ValueError("bot.skills must be resolved by the catalog service")
    if set(skill_ids) != {skill.name for skill in skills}:
        raise ValueError("bot.skillIds and resolved bot.skills do not match")
