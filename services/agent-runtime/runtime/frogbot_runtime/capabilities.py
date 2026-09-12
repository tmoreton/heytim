from __future__ import annotations

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
from .gateway_tools import gateway_client, gateway_operations
from .image_generation import image_generation_tools
from .local_tools import CUSTOM_TOOLS
from .mcp_connections import (
    GITHUB_MCP_ENDPOINT,
    connection_client,
    connection_credential,
)
from .memes import meme_tools
from .repository_workspace import repository_workspace_tool


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
) -> CapabilityConfiguration:
    bindings = tool_bindings(bot)
    skills = dynamic_skills(bot)
    background_work = BackgroundWorkTracker()
    bot_mutations = BotMutationTracker()
    tools = [
        CUSTOM_TOOLS[item["name"]]
        for item in bindings
        if item["kind"] == "local" and item["name"] in CUSTOM_TOOLS
    ]
    local_names = {item["name"] for item in bindings if item["kind"] == "local"}
    if "bot_manager" in local_names and bot_management is not None:
        tools.extend(bot_management_tools(bot_management, bot_mutations))
    if artifact_prefix:
        tools.append(artifact_tool(artifact_prefix))
        if "meme_lord" in local_names:
            tools.extend(
                meme_tools(
                    artifact_prefix,
                    [item["body"] for item in image_references or []],
                )
            )
        if "image_generator" in local_names:
            tools.extend(
                image_generation_tools(
                    artifact_prefix, image_references or [], usage=usage
                )
            )
    managed_tools, interpreter, browser = agentcore_tools(
        bindings,
        session_id,
        background_work,
        allow_background_work=allow_background_work,
        managed_browser=managed_browser,
    )
    tools.extend(managed_tools)
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
        and github_binding.get("authType") in {"bearer", "api_key"}
        and interpreter
    ):
        tools.append(
            repository_workspace_tool(
                interpreter,
                lambda: connection_credential(github_binding),
            )
        )
    managed_gateway = gateway_client(gateway_operations(bindings), usage)
    if managed_gateway:
        tools.append(managed_gateway)
    tools.extend(connection_client(item) for item in bindings if item["kind"] == "mcp")
    validate_skill_selection(bot, skills)

    return CapabilityConfiguration(
        tools=tools,
        builtin_tools=[
            item["name"] for item in bindings if item["kind"] == "stan_builtin"
        ]
        + (
            ["subagent"]
            if any(item["kind"] == "stan_subagent" for item in bindings)
            else []
        ),
        plugins=[AgentSkills(skills=skills, strict=True)] if skills else [],
        builtin_plugins=[
            item["name"] for item in bindings if item["kind"] == "stan_plugin"
        ],
        background_work=background_work,
        bot_mutations=bot_mutations,
        browser=browser,
    )


__all__ = ["CapabilityConfiguration", "resolve_capabilities"]
