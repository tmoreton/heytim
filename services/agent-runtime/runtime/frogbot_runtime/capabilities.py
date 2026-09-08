from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strands.vended_plugins.skills import AgentSkills

from .agentcore_adapters import agentcore_tools
from .artifacts import artifact_tool, image_tool
from .background_work import BackgroundWorkTracker
from .capability_contract import (
    dynamic_skills,
    tool_bindings,
    validate_skill_selection,
)
from .gateway_tools import gateway_client, gateway_operations
from .local_tools import CUSTOM_TOOLS
from .mcp_connections import (
    GITHUB_MCP_ENDPOINT,
    connection_client,
    connection_credential,
)
from .repository_workspace import repository_workspace_tool


@dataclass(frozen=True)
class CapabilityConfiguration:
    tools: list[Any]
    builtin_tools: list[str]
    plugins: list[Any]
    builtin_plugins: list[str]
    background_work: BackgroundWorkTracker


def resolve_capabilities(
    bot: dict,
    session_id: str,
    artifact_prefix: str | None = None,
    *,
    allow_background_work: bool = True,
) -> CapabilityConfiguration:
    bindings = tool_bindings(bot)
    skills = dynamic_skills(bot)
    background_work = BackgroundWorkTracker()
    tools = [CUSTOM_TOOLS[item["name"]] for item in bindings if item["kind"] == "local"]
    if artifact_prefix:
        tools.extend([artifact_tool(artifact_prefix), image_tool(artifact_prefix)])
    managed_tools, interpreter = agentcore_tools(
        bindings,
        session_id,
        background_work,
        allow_background_work=allow_background_work,
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
    managed_gateway = gateway_client(gateway_operations(bindings))
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
    )


__all__ = ["CapabilityConfiguration", "resolve_capabilities"]
