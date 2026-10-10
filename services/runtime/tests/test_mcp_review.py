from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpcore
import pytest
from mcp.types import Tool
from strands.tools.mcp.mcp_client import MCPClient
from strands.types import PaginatedList

from heytim_runtime.integration_setup import request_integration_setup
from heytim_runtime.mcp_client import BoundedMCPClient
from heytim_runtime.mcp_review import tool_digest
from heytim_runtime.mcp_transport import PublicNetworkBackend

READ = {"name": "read_state", "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True}}
WRITE = {"name": "unlock_door", "inputSchema": {"type": "object", "properties": {}}}


def client():
    return BoundedMCPClient(lambda: None, connection_id="connection-test",
                            approved_tools={"read_state": tool_digest(READ)})


def adapted(raw):
    return SimpleNamespace(mcp_tool=Tool.model_validate(raw), timeout=None)


def test_only_selected_unchanged_schema_is_discovered_and_invocable(monkeypatch):
    monkeypatch.setattr(MCPClient, "list_tools_sync", lambda *a, **kw: PaginatedList([
        adapted(READ), adapted(WRITE)
    ], token=None))
    invoked = AsyncMock(return_value={"status": "success"})
    monkeypatch.setattr(MCPClient, "call_tool_async", invoked)
    connection = client()
    discovered = connection.list_tools_sync()
    assert [t.mcp_tool.name for t in discovered] == ["read_state"]
    assert asyncio.run(connection.call_tool_async("read", "read_state", {}))["status"] == "success"
    assert asyncio.run(connection.call_tool_async("write", "unlock_door", {}))["status"] == "error"
    assert invoked.await_count == 1
    changed = {**READ, "inputSchema": {"type": "object", "required": ["new_argument"]}}
    monkeypatch.setattr(MCPClient, "list_tools_sync", lambda *a, **kw: PaginatedList([adapted(changed)]))
    assert not connection.list_tools_sync()
    assert asyncio.run(connection.call_tool_async("stale", "read_state", {}))["status"] == "error"


def test_repeated_cursor_does_not_loop_forever(monkeypatch):
    monkeypatch.setattr(MCPClient, "list_tools_sync", lambda *a, **kw: PaginatedList([], token="repeat"))
    with pytest.raises(ValueError, match="repeated"):
        client()._list_all_tools_sync()


def test_rediscovery_revokes_a_disappeared_tool_even_if_listing_fails(monkeypatch):
    listing = Mock(return_value=PaginatedList([adapted(READ)]))
    monkeypatch.setattr(MCPClient, "list_tools_sync", listing)
    invoked = AsyncMock()
    monkeypatch.setattr(MCPClient, "call_tool_async", invoked)
    connection = client()
    connection.list_tools_sync()
    listing.return_value = PaginatedList([])
    assert not connection.list_tools_sync()
    assert asyncio.run(connection.call_tool_async("removed", "read_state", {}))["status"] == "error"
    listing.return_value = PaginatedList([adapted(READ)])
    connection.list_tools_sync()
    listing.side_effect = OSError("offline")
    with pytest.raises(OSError):
        connection.list_tools_sync()
    assert asyncio.run(connection.call_tool_async("offline", "read_state", {}))["status"] == "error"
    invoked.assert_not_called()


def test_failed_custom_server_does_not_abort_other_capability_loading(monkeypatch):
    monkeypatch.setattr(MCPClient, "load_tools", AsyncMock(side_effect=OSError("offline")))
    assert asyncio.run(client().load_tools()) == []
    legacy = BoundedMCPClient(lambda: None, connection_id="legacy")
    with pytest.raises(OSError):
        asyncio.run(legacy.load_tools())


def test_tcp_backend_rejects_private_rebinding_before_connect(monkeypatch):
    monkeypatch.setattr("heytim_runtime.mcp_transport.anyio.getaddrinfo", AsyncMock(return_value=[
        (2, 1, 6, "", ("127.0.0.1", 443))
    ]))
    backend = PublicNetworkBackend()
    backend.backend = Mock(connect_tcp=AsyncMock())
    with pytest.raises(httpcore.ConnectError):
        asyncio.run(backend.connect_tcp("example.com", 443, timeout=1))
    backend.backend.connect_tcp.assert_not_called()


def test_tcp_backend_connects_to_validated_ip_not_hostname(monkeypatch):
    monkeypatch.setattr("heytim_runtime.mcp_transport.anyio.getaddrinfo", AsyncMock(return_value=[
        (2, 1, 6, "", ("93.184.216.34", 443))
    ]))
    backend = PublicNetworkBackend()
    backend.backend = Mock(connect_tcp=AsyncMock())
    asyncio.run(backend.connect_tcp("example.com", 443, timeout=1))
    assert backend.backend.connect_tcp.call_args.args == ("93.184.216.34", 443)


def test_setup_link_is_user_activated_and_never_contains_credentials():
    link = request_integration_setup("Home Assistant", "https://home.example.com/api/mcp/assist")
    assert "heytim://connect-mcp?" in link
    assert "name=Home%20Assistant" in link
    for endpoint in ["https://token@example.com/mcp", "https://example.com/mcp?token=secret"]:
        with pytest.raises(ValueError):
            request_integration_setup("Unsafe", endpoint)
