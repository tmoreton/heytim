"""Scoped MCP tool discovery and stable model-facing names."""

from __future__ import annotations

from typing import Any

from strands.tools.mcp.mcp_agent_tool import MCPAgentTool
from strands.tools.mcp.mcp_client import MCPClient
from strands.types import PaginatedList

from .mcp_tool_catalog import SCOPED_GOOGLE_TOOLS
from .mcp_tool_names import _bounded_tool_name


class LabeledMCPAgentTool(MCPAgentTool):
    def __init__(self, *args: Any, account_label: str | None = None, **kwargs: Any) -> None:
        self._heytim_account_label = account_label
        super().__init__(*args, **kwargs)

    @property
    def tool_spec(self):
        spec = super().tool_spec
        if self._heytim_account_label:
            spec["description"] += f" Connected account: {self._heytim_account_label}."
        return spec


class BoundedMCPClient(MCPClient):
    """Expose stable MCP aliases that every supported text model can accept."""

    def __init__(
        self, *args: Any, connection_id: str,
        resource_ids: set[str] | None = None,
        resource_server: str | None = None,
        account_label: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._heytim_connection_id = connection_id
        self._heytim_resource_ids = resource_ids
        self._heytim_resource_server = resource_server
        self._heytim_account_label = account_label
        super().__init__(*args, prefix=None, **kwargs)

    def list_tools_sync(
        self,
        pagination_token: str | None = None,
        prefix: str | None = None,
        tool_filters: Any = None,
    ) -> PaginatedList[MCPAgentTool]:
        page = super().list_tools_sync(
            pagination_token,
            prefix="",
            tool_filters=tool_filters,
        )
        tools = [
            LabeledMCPAgentTool(
                tool.mcp_tool,
                self,
                account_label=self._heytim_account_label,
                name_override=_bounded_tool_name(
                    self._heytim_connection_id,
                    tool.mcp_tool.name,
                ),
                timeout=tool.timeout,
            )
            for tool in page
            if self._heytim_resource_ids is None
            or tool.mcp_tool.name in SCOPED_GOOGLE_TOOLS.get(
                self._heytim_resource_server or "", {}
            )
        ]
        return PaginatedList(tools, token=page.pagination_token)

    async def call_tool_async(
        self, tool_use_id: str, name: str,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        if self._heytim_resource_ids is not None:
            field = SCOPED_GOOGLE_TOOLS.get(
                self._heytim_resource_server or "", {}
            ).get(name)
            resource = arguments.get(field) if isinstance(arguments, dict) and field else None
            if not isinstance(resource, str) or resource not in self._heytim_resource_ids:
                return {
                    "toolUseId": tool_use_id,
                    "status": "error",
                    "content": [{"text": "This bot is not assigned that Workspace resource"}],
                }
        return await super().call_tool_async(
            tool_use_id, name, arguments=arguments, **kwargs
        )
