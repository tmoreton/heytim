from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from group_context import collaboration_instructions

from .artifacts import artifact_prefix_from_payload
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


def bot_configuration(
    payload: dict, session_id: str = "unknown", actor_id: str | None = None
) -> BotConfiguration:
    bot = payload.get("bot", {})
    if not isinstance(bot, dict):
        raise TypeError("bot must be an object")

    name = bot.get("name", "FroggyBot")
    prompt = bot.get("prompt", "Be helpful, direct, and honest.")
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise ValueError("bot.name must be a non-empty string up to 60 characters")
    if not isinstance(prompt, str):
        raise TypeError("bot.prompt must be a string")
    if len(prompt) > MAX_INSTRUCTIONS_CHARS:
        raise ValueError(
            f"bot.prompt must be at most {MAX_INSTRUCTIONS_CHARS} characters"
        )

    artifact_prefix = artifact_prefix_from_payload(payload, actor_id)
    capabilities = resolve_capabilities(bot, session_id, artifact_prefix)
    instructions = (
        f"Your name is {name.strip()}. You are one member of the user's team of AI assistants.\n\n"
        f"Your role and working preferences:\n{prompt.strip()}\n\n"
        "Capability use:\n"
        "- The user does not need to name a skill or tool.\n"
        "- When an available skill clearly matches the request, activate it with the skills tool before doing the work.\n"
        "- Use available tools when they materially improve accuracy or are required by an activated skill.\n"
        "- When the user asks for a downloadable text, Markdown, CSV, JSON, HTML, PDF, Word, Excel, or PowerPoint file, use save_artifact.\n"
        "- When an itinerary, budget, checklist, or reusable plan would help, create the most useful downloadable file automatically unless the user asks for chat only. Prefer PDF for a polished plan and Excel for a budget or table.\n"
        "- For PDF or Word, pass Markdown content. For Excel, pass CSV content. For PowerPoint, pass Markdown and put --- on a line between slides.\n"
        "- When the user asks you to create an original image, use generate_image.\n"
        "- Do not claim to have used a skill or tool unless you actually activated or called it.\n\n"
        "Execution discipline:\n"
        "- Keep progress narration to one short sentence before a tool call.\n"
        "- For change requests, inspect only what is needed, make a reasonable choice, act promptly, verify the result, and then answer.\n"
        "- Do not spend the response budget debating options or repeatedly restating the plan.\n"
        "- After using tools, always finish with a concise final answer that states the outcome."
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
