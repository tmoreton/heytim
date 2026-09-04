from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from group_context import collaboration_instructions

from .capabilities import resolve_capabilities

MAX_INSTRUCTIONS_CHARS = 12_000


@dataclass(frozen=True)
class BotConfiguration:
    instructions: str
    tools: list[Any]
    builtin_tools: list[str]
    plugins: list[Any]
    skill_paths: list[str]
    builtin_plugins: list[str]
    builtin_subagents: list[str]


def bot_configuration(payload: dict, session_id: str = "unknown") -> BotConfiguration:
    bot = payload.get("bot", {})
    if not isinstance(bot, dict):
        raise TypeError("bot must be an object")

    name = bot.get("name", "FrogBot")
    prompt = bot.get("prompt", "Be helpful, direct, and honest.")
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise ValueError("bot.name must be a non-empty string up to 60 characters")
    if not isinstance(prompt, str):
        raise TypeError("bot.prompt must be a string")
    if len(prompt) > MAX_INSTRUCTIONS_CHARS:
        raise ValueError(
            f"bot.prompt must be at most {MAX_INSTRUCTIONS_CHARS} characters"
        )

    capabilities = resolve_capabilities(bot, session_id)
    instructions = (
        f"Your name is {name.strip()}. You are one member of the user's team of AI assistants.\n\n"
        f"Your role and working preferences:\n{prompt.strip()}"
    )
    group_instructions = collaboration_instructions(payload.get("group"))
    if group_instructions:
        instructions = f"{instructions}\n\n{group_instructions}"
    return BotConfiguration(
        instructions=instructions,
        tools=capabilities.tools,
        builtin_tools=capabilities.builtin_tools,
        plugins=capabilities.plugins,
        skill_paths=capabilities.skill_paths,
        builtin_plugins=capabilities.builtin_plugins,
        builtin_subagents=capabilities.builtin_subagents,
    )
