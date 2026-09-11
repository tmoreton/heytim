from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from group_context import collaboration_instructions

from .artifacts import artifact_prefix_from_payload
from .background_work import BackgroundWorkTracker
from .bot_management import bot_management_from_payload
from .browser_session import managed_browser_from_payload
from .capabilities import CapabilityConfiguration, resolve_capabilities
from .instructions import (
    INLINE_DELIVERY_INSTRUCTIONS,
    base_instructions,
    continuation_instructions,
    image_reference_instructions,
    team_instructions,
)
from .memes import image_attachments_from_messages
from .request import image_references_from_payload

MAX_INSTRUCTIONS_CHARS = 12_000


@dataclass(frozen=True)
class BotConfiguration:
    instructions: str
    tools: list[Any]
    builtin_tools: list[str]
    plugins: list[Any]
    builtin_plugins: list[str]
    background_work: BackgroundWorkTracker
    capability_configuration: CapabilityConfiguration

    async def close(self) -> None:
        await self.capability_configuration.close()


def bot_configuration(
    payload: dict,
    session_id: str = "unknown",
    actor_id: str | None = None,
    messages: list[dict] | None = None,
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

    continuation_context = continuation_instructions(payload)
    team_context = team_instructions(payload.get("team"))
    artifact_prefix = artifact_prefix_from_payload(payload, actor_id)
    image_references = image_references_from_payload(payload, actor_id)
    if not image_references:
        image_references = [
            {"name": f"Latest attachment {index}", "body": body}
            for index, body in enumerate(
                image_attachments_from_messages(messages or []), start=1
            )
        ]
    capabilities = resolve_capabilities(
        bot,
        session_id,
        artifact_prefix,
        allow_background_work=not continuation_context,
        managed_browser=managed_browser_from_payload(
            payload, actor_id, artifact_prefix
        ),
        bot_management=bot_management_from_payload(payload),
        image_references=image_references,
    )
    instructions = base_instructions(name.strip(), prompt.strip())
    for context in (
        team_context,
        image_reference_instructions(image_references),
        continuation_context,
    ):
        if context:
            instructions = f"{instructions}\n\n{context}"
    group_instructions = collaboration_instructions(payload.get("group"))
    if group_instructions:
        instructions = f"{instructions}\n\n{group_instructions}"
    instructions = f"{instructions}\n\n{INLINE_DELIVERY_INSTRUCTIONS}"
    return BotConfiguration(
        instructions=instructions,
        tools=capabilities.tools,
        builtin_tools=capabilities.builtin_tools,
        plugins=capabilities.plugins,
        builtin_plugins=capabilities.builtin_plugins,
        background_work=capabilities.background_work,
        capability_configuration=capabilities,
    )
