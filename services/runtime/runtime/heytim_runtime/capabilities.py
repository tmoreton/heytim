from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from strands.vended_plugins.skills import AgentSkills

from .agentcore_adapters import PersistentAgentCoreBrowser, agentcore_tools
from .artifacts import artifact_tool
from .background_work import BackgroundWorkTracker
from .bot_management import BotMutationTracker, bot_management_tools
from .capability_contract import (
    dynamic_skills,
    tool_bindings,
    validate_skill_selection,
)
from .device_tools import device_tools
from .gateway_tools import gateway_client, gateway_operations
from .gmail_api import gmail_api_tools
from .image_generation import image_generation_tools
from .local_tools import CUSTOM_TOOLS
from .mcp_connections import (
    GITHUB_MCP_ENDPOINT,
    GMAIL_MCP_ENDPOINT,
    ConnectionCredentialUnavailable,
    connection_clients,
    github_installation_token,
)
from .memes import meme_tools
from .provider_connections import provider_connection_tools
from .repository_workspace import repository_workspace_tool
from .tool_results import ResultStorage, ToolResultOffloader
from .workspace_assets import workspace_asset_tools
from .workspace_sync import workspace_sync_tool

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityConfiguration:
    tools: list[Any]
    builtin_tools: list[str]
    plugins: list[Any]
    builtin_plugins: list[str]
    background_work: BackgroundWorkTracker
    bot_mutations: BotMutationTracker
    browser: PersistentAgentCoreBrowser | None

    async def close(self) -> None:
        if self.browser:
            await self.browser.aclose()


def resolve_capabilities(
    bot: dict,
    session_id: str,
    artifact_prefix: str | None = None,
    *,
    allow_background_work: bool = True,
    managed_browser: dict | None = None,
    bot_management: dict | None = None,
    image_references: list[dict] | None = None,
    usage: Any = None,
    workspace_files: list[dict] | None = None,
    workspace_assets: list[dict] | None = None,
) -> CapabilityConfiguration:
    if bot.get("conversationMode", "agent") == "chat":
        # Validate the supplied bot recipe even though this mode exposes none
        # of its capabilities to the model.
        tool_bindings(bot)
        selected_skills = dynamic_skills(bot)
        validate_skill_selection(bot, selected_skills)
        return CapabilityConfiguration(
            tools=[],
            builtin_tools=[],
            plugins=[],
            builtin_plugins=[],
            background_work=BackgroundWorkTracker(),
            bot_mutations=BotMutationTracker(),
            browser=None,
        )
    bindings = tool_bindings(bot)
    skills = dynamic_skills(bot)
    skills.sort(key=lambda skill: skill.name)
    background_work = BackgroundWorkTracker()
    bot_mutations = BotMutationTracker()
    tools = [
        CUSTOM_TOOLS[item["name"]]
        for item in bindings
        if item["kind"] == "local" and item["name"] in CUSTOM_TOOLS
    ]
    tools.extend(device_tools(bindings))
    local_names = {item["name"] for item in bindings if item["kind"] == "local"}
    if "bot_manager" in local_names and bot_management is not None:
        tools.extend(bot_management_tools(bot_management, bot_mutations))
    # Google tool output can enter an image prompt on this bot. The OpenRouter
    # Image API has no documented per-request ZDR control, so do not expose a
    # route that could send connected Google content to its image provider.
    google_connected = any(item.get("oauthProvider") == "google" for item in bindings)
    if artifact_prefix:
        tools.append(artifact_tool(artifact_prefix))
        tools.extend(workspace_asset_tools(artifact_prefix, workspace_assets or []))
        if "meme_lord" in local_names:
            tools.extend(
                meme_tools(
                    artifact_prefix,
                    [item["body"] for item in image_references or []],
                )
            )
        if "image_generator" in local_names and not google_connected:
            tools.extend(
                image_generation_tools(
                    artifact_prefix,
                    image_references or [],
                    usage=usage,
                )
            )
    managed_tools, interpreter, browser = agentcore_tools(
        bindings,
        session_id,
        background_work,
        allow_background_work=allow_background_work,
        managed_browser=managed_browser,
        artifact_prefix=artifact_prefix,
    )
    tools.extend(managed_tools)
    if interpreter and workspace_files:
        tools.append(workspace_sync_tool(interpreter, workspace_files))
    github_binding = next(
        (
            item
            for item in bindings
            if item["kind"] == "mcp"
            and item["endpoint"].rstrip("/") == GITHUB_MCP_ENDPOINT.rstrip("/")
        ),
        None,
    )
    if (
        github_binding
        and github_binding.get("authType") == "github_app"
        and interpreter
    ):
        tools.append(
            repository_workspace_tool(
                interpreter,
                lambda: github_installation_token(github_binding),
            )
        )
    managed_gateway = gateway_client(gateway_operations(bindings), usage)
    if managed_gateway:
        tools.append(managed_gateway)
    for item in bindings:
        if item["kind"] in {"mcp", "mcp_bundle"}:
            if item["kind"] == "mcp" and item["endpoint"].rstrip(
                "/"
            ) == GMAIL_MCP_ENDPOINT.rstrip("/"):
                tools.extend(gmail_api_tools(item, artifact_prefix))
            else:
                try:
                    tools.extend(connection_clients(item))
                except ConnectionCredentialUnavailable as exc:
                    log.warning(
                        "Skipping unavailable connection %s (%s): %s",
                        item.get("id", "unknown"),
                        item.get("authType", "unknown"),
                        exc,
                    )
    for item in bindings:
        if item["kind"] == "provider_api":
            tools.extend(provider_connection_tools(item, usage))
    validate_skill_selection(bot, skills)

    # A stable order preserves the model's tool-schema prefix across turns when
    # the authorized tool set is unchanged. Never keep a tool after it is revoked.
    tools.sort(
        key=lambda item: (
            getattr(item, "tool_name", None)
            or getattr(item, "__name__", None)
            or type(item).__name__
        )
    )
    named_tools = {item.tool_name: item for item in tools if hasattr(item, "tool_name")}
    saved_results = ToolResultOffloader(
        ResultStorage(artifact_prefix),
        save_artifact=named_tools.get("save_artifact"),
        save_workspace=named_tools.get("save_workspace_asset"),
    )

    return CapabilityConfiguration(
        tools=tools,
        builtin_tools=sorted(
            [item["name"] for item in bindings if item["kind"] == "stan_builtin"]
            + (
                ["subagent"]
                if any(item["kind"] == "stan_subagent" for item in bindings)
                else []
            )
        ),
        plugins=[saved_results]
        + ([AgentSkills(skills=skills, strict=True)] if skills else []),
        builtin_plugins=sorted(
            [item["name"] for item in bindings if item["kind"] == "stan_plugin"]
        ),
        background_work=background_work,
        bot_mutations=bot_mutations,
        browser=browser,
    )


__all__ = ["CapabilityConfiguration", "resolve_capabilities"]
