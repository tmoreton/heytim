"""Scoped MCP tool discovery and stable model-facing names."""

from __future__ import annotations

import json
import time
from typing import Any

from strands.tools.mcp.mcp_agent_tool import MCPAgentTool
from strands.tools.mcp.mcp_client import MCPClient
from strands.types import PaginatedList

from .mcp_review import tool_digest
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
        approved_tools: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._heytim_connection_id = connection_id
        self._heytim_resource_ids = resource_ids
        self._heytim_resource_server = resource_server
        self._heytim_account_label = account_label
        self._heytim_approved_tools = approved_tools
        self._heytim_verified_tools: set[str] = set()
        super().__init__(*args, prefix=None, **kwargs)

    def list_tools_sync(
        self,
        pagination_token: str | None = None,
        prefix: str | None = None,
        tool_filters: Any = None,
    ) -> PaginatedList[MCPAgentTool]:
        if pagination_token is None:
            self._heytim_verified_tools.clear()
            self._heytim_discovered_count = 0
        page = super().list_tools_sync(
            pagination_token,
            prefix="",
            tool_filters=tool_filters,
        )
        next_token = page.pagination_token
        self._heytim_discovered_count = getattr(self, "_heytim_discovered_count", 0) + len(page)
        if self._heytim_approved_tools is not None and self._heytim_discovered_count > 100:
            raise ValueError("MCP tool discovery limit exceeded")
        page = [tool for tool in page if self._reviewed(tool)]
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
        return PaginatedList(tools, token=next_token)

    def _reviewed(self, tool) -> bool:
        if self._heytim_approved_tools is None:
            return True
        raw = tool.mcp_tool.model_dump(mode="json", by_alias=True, exclude_unset=True)
        name = tool.mcp_tool.name
        if len(json.dumps(raw).encode()) > 32_000:
            return False
        if self._heytim_approved_tools.get(name) != tool_digest(raw):
            self._heytim_verified_tools.discard(name)
            return False
        self._heytim_verified_tools.add(name)
        return True

    def _list_all_tools_sync(self):
        # A malicious server must not keep discovery running via endless cursors.
        if self._heytim_approved_tools is None:
            return super()._list_all_tools_sync()
        tools, seen, cursor = [], set(), None
        deadline = time.monotonic() + 12
        for _ in range(8):
            if time.monotonic() > deadline:
                raise ValueError("MCP discovery timed out")
            page = self.list_tools_sync(cursor)
            tools.extend(page)
            if len(tools) > 100:
                raise ValueError("MCP tool discovery limit exceeded")
            cursor = page.pagination_token
            if cursor is None:
                return tools
            if cursor in seen:
                raise ValueError("MCP repeated a tool discovery cursor")
            seen.add(cursor)
        raise ValueError("MCP discovery page limit exceeded")

    async def load_tools(self, **kwargs):
        try:
            return await super().load_tools(**kwargs)
        except Exception:
            if self._heytim_approved_tools is None:
                raise
            self._heytim_verified_tools.clear()
            # Unavailable tools must be absent, rather than pretending the action succeeded.
            return []

    async def call_tool_async(
        self, tool_use_id: str, name: str,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        if self._heytim_approved_tools is not None and name not in self._heytim_verified_tools:
            return {"toolUseId": tool_use_id, "status": "error", "content": [{
                "text": "This MCP tool is unavailable or changed. Test and review the connection again."
            }]}
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
