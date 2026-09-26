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
from .workspace_assets import workspace_assets_from_payload
from .workspace_sync import workspace_files_from_payload

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
    usage: Any = None,
) -> BotConfiguration:
    bot = payload.get("bot", {})
    if not isinstance(bot, dict):
        raise TypeError("bot must be an object")

    name = bot.get("name", "HeyTim")
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
    workspace_files = workspace_files_from_payload(payload, actor_id)
    workspace_assets = workspace_assets_from_payload(payload, actor_id)
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
        usage=usage,
        workspace_files=workspace_files,
        workspace_assets=workspace_assets,
    )
    instructions = base_instructions(name.strip(), prompt.strip())
    if workspace_files and any(
        getattr(candidate, "tool_name", None) == "load_workspace_files"
        for candidate in capabilities.tools
    ):
        instructions += (
            "\n\nThe user selected durable workspace files for this turn. "
            "Call load_workspace_files before using them in code_interpreter. "
            "Those files persist in the app workspace across code sessions."
        )
    if any(
        getattr(candidate, "tool_name", None) == "save_workspace_asset"
        for candidate in capabilities.tools
    ):
        asset_summary = ", ".join(
            f"{item['assetKey']} (revision {item['revision']}, {item['name']})"
            for item in workspace_assets
        )
        instructions += (
            "\n\nUse save_workspace_asset for files that should persist and be revised "
            "across future turns. Reuse one stable asset_key instead of creating a "
            "new file or filename for each refresh. Read an existing asset with "
            "read_workspace_asset before revising it when prior content matters. "
            "Use save_artifact only for one-time downloads."
        )
        if asset_summary:
            instructions += " Existing durable assets: " + asset_summary + "."
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
