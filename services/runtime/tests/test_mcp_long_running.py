"""Exercise the installed MCP transport over a simulated eight-hour task."""

from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from types import SimpleNamespace

import httpx
import pytest

from heytim_runtime import mcp_auth, mcp_connections
from heytim_runtime.mcp_auth import AccessToken


@pytest.mark.parametrize("kind", ["github_app", "oauth", "workspace"])
def test_mcp_tools_remain_authenticated_throughout_an_eight_hour_run(monkeypatch, kind):
    elapsed = [0]
    minted, executed = [], []
    monkeypatch.setattr(mcp_auth, "time", SimpleNamespace(
        monotonic=lambda: elapsed[0], time=lambda: elapsed[0],
    ))

    def credential(_binding):
        token = f"test-credential-{len(minted)}"
        minted.append((token, elapsed[0]))
        return AccessToken.expiring(token, 3_600)

    monkeypatch.setattr(mcp_connections, "_google_access_credential", credential)
    monkeypatch.setattr(mcp_connections, "_github_installation_credential", credential)
    monkeypatch.setattr(
        mcp_connections.socket, "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    if kind == "workspace":
        servers = mcp_connections.GOOGLE_WORKSPACE_MCP_SERVERS
        binding = {
            "kind": "mcp_bundle", "authType": "oauth", "id": "assigned-account",
            "servers": [
                {"endpoint": endpoint, "allowedTools": sorted(names)}
                for endpoint, names in servers.items()
            ],
        }
    else:
        endpoint = (
            mcp_connections.GITHUB_MCP_ENDPOINT if kind == "github_app"
            else mcp_connections.GMAIL_MCP_ENDPOINT
        )
        servers = {endpoint: {"create_issue" if kind == "github_app" else "search_threads"}}
        binding = {
            "kind": "mcp", "authType": kind, "id": "assigned-account",
            "endpoint": endpoint, "allowedTools": sorted(servers[endpoint]),
        }

    def provider(request):
        token, issued = minted[-1]
        assert elapsed[0] < issued + 3_600
        assert request.headers["authorization"] == f"Bearer {token}"
        if request.method == "DELETE":
            return httpx.Response(204)
        assert request.method == "POST"
        message = json.loads(request.content)
        method = message["method"]
        if "id" not in message:
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test-provider", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": [{
                "name": name, "description": "Test assigned tool",
                "inputSchema": {"type": "object", "properties": {}},
            } for name in sorted(servers[str(request.url)])]}
        else:
            assert method == "tools/call"
            assert message["params"]["name"] in servers[str(request.url)]
            executed.append((str(request.url), elapsed[0], message["params"]["name"]))
            result = {"content": [{"type": "text", "text": f"receipt-{len(executed)}"}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def http_client(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            headers=headers, auth=auth, follow_redirects=False,
            transport=httpx.MockTransport(provider),
            event_hooks={"request": [mcp_connections._validate_outbound_request]},
        )

    monkeypatch.setattr(mcp_connections, "_secure_http_client", http_client)
    with ExitStack() as stack:
        clients = [stack.enter_context(client) for client in mcp_connections.connection_clients(binding)]
        tools = [client.list_tools_sync()[0] for client in clients]
        assert len(minted) == 1
        moments = [*range(0, 28_800, 3_600), 28_799]
        for moment in moments:
            elapsed[0] = moment
            for client, tool in zip(clients, tools, strict=True):
                result = asyncio.run(client.call_tool_async(
                    f"tool-{moment}", tool.mcp_tool.name, {},
                ))
                assert result["status"] == "success"
                assert result["content"][0]["text"] == f"receipt-{len(executed)}"
    assert len(minted) == len(moments)
    assert len(executed) == len(moments) * len(servers)
    assert len(set(executed)) == len(executed)


def test_provider_expiry_is_preserved_by_google_and_github_loaders(monkeypatch):
    from datetime import UTC, datetime, timedelta

    tokens = iter([
        {"access_token": "google-token", "expires_in": 10},
        {"token": "github-token", "expires_at": (
            datetime.now(UTC) + timedelta(seconds=10)
        ).isoformat()},
    ])

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self, _limit):
            return json.dumps(next(tokens)).encode()

    monkeypatch.setattr(mcp_connections, "_json_secret", lambda _: {
        "refreshToken": "test-refresh", "web": {"client_id": "id", "client_secret": "secret"},
        "installationId": "1", "repositoryIds": [1],
        "permissions": {"metadata": "read", "contents": "write"},
    })
    monkeypatch.setattr(mcp_connections, "github_app_config", lambda _: {"appId": "1", "privateKey": "key"})
    monkeypatch.setattr(mcp_connections, "github_app_jwt", lambda *_: "test-jwt")
    monkeypatch.setattr(mcp_connections.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    binding = {"authType": "github_app", "secretArn": "user", "appSecretArn": "app", "oauthClientSecretArn": "oauth"}
    before = mcp_auth.time.monotonic()
    google = mcp_connections._google_access_credential(binding)
    github = mcp_connections._github_installation_credential(binding)
    assert google.value == "google-token"
    assert github.value == "github-token"
    assert before < google.refresh_at < before + 10
    assert before < github.refresh_at < before + 10
