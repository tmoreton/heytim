from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from frogbot_runtime import mcp_connections


def _public_address(*_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def test_authenticated_connection_fetches_secret_server_side(monkeypatch) -> None:
    class FakeSecrets:
        def get_secret_value(self, *, SecretId: str) -> dict:
            assert SecretId.endswith("-ABC123")
            return {"SecretString": "private-token"}

    captured = {}

    class FakeMCPClient:
        def __init__(self, transport, **kwargs):
            captured["transport"] = transport
            captured.update(kwargs)

    monkeypatch.setattr(mcp_connections.socket, "getaddrinfo", _public_address)
    monkeypatch.setattr(mcp_connections, "_secrets_manager", FakeSecrets())
    monkeypatch.setattr(mcp_connections, "MCPClient", FakeMCPClient)
    binding = mcp_connections.validated_connection_binding(
        "connection_1234567890abcdef1234",
        {
            "endpoint": "https://mcp.example.com/mcp",
            "authType": "bearer",
            "secretArn": (
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                "frogbot/connections/abcdef1234567890abcdef12/"
                "connection_1234567890abcdef1234-abcdef123456-ABC123"
            ),
            "headerName": "Authorization",
            "headerPrefix": "Bearer ",
        },
    )

    mcp_connections.connection_client(binding)

    assert captured["prefix"] == "connection_1234567890abcdef1234"
    transport = captured["transport"]
    assert transport.func is mcp_connections._secure_streamable_http
    assert transport.args == (
        "https://mcp.example.com/mcp",
        {"Authorization": "Bearer private-token"},
    )


def test_connection_rejects_private_dns_results(monkeypatch) -> None:
    monkeypatch.setattr(
        mcp_connections.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("10.0.0.5", 443))],
    )

    try:
        mcp_connections.validated_connection_binding(
            "connection_1234567890abcdef1234",
            {"endpoint": "https://mcp.example.com/mcp", "authType": "none"},
        )
    except ValueError as error:
        assert "public" in str(error)
    else:
        raise AssertionError("private DNS result was accepted")


def test_http_transport_revalidates_dns_for_each_request(monkeypatch) -> None:
    answers = iter(
        [
            [(2, 1, 6, "", ("93.184.216.34", 443))],
            [(2, 1, 6, "", ("10.0.0.5", 443))],
        ]
    )
    monkeypatch.setattr(
        mcp_connections.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: next(answers),
    )
    mcp_connections._validated_endpoint("https://mcp.example.com/mcp")

    request = httpx.Request("POST", "https://mcp.example.com/mcp")
    with pytest.raises(ValueError, match="resolve publicly"):
        asyncio.run(mcp_connections._validate_outbound_request(request))


def test_http_transport_does_not_follow_redirects() -> None:
    client = mcp_connections._secure_http_client()
    try:
        assert client.follow_redirects is False
        assert client.event_hooks["request"] == [
            mcp_connections._validate_outbound_request
        ]
    finally:
        asyncio.run(client.aclose())


def test_google_oauth_connection_refreshes_token_and_filters_tools(monkeypatch) -> None:
    user_secret = (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        "frogbot/connections/abcdef1234567890abcdef12/"
        "connection_1234567890abcdef1234-abcdef123456-ABC123"
    )
    client_secret = (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        "frogbot/oauth/google-ABC123"
    )

    class FakeSecrets:
        def get_secret_value(self, *, SecretId: str) -> dict:
            if SecretId == user_secret:
                return {"SecretString": json.dumps({"refreshToken": "refresh-token"})}
            assert SecretId == client_secret
            return {
                "SecretString": json.dumps(
                    {"web": {"client_id": "client-id", "client_secret": "secret"}}
                )
            }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps({"access_token": "access-token"}).encode()

    captured = {}

    class FakeMCPClient:
        def __init__(self, transport, **kwargs):
            captured["transport"] = transport
            captured.update(kwargs)

    monkeypatch.setattr(mcp_connections.socket, "getaddrinfo", _public_address)
    monkeypatch.setattr(mcp_connections, "_secrets_manager", FakeSecrets())
    monkeypatch.setattr(
        mcp_connections.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    monkeypatch.setattr(mcp_connections, "MCPClient", FakeMCPClient)
    binding = mcp_connections.validated_connection_binding(
        "connection_1234567890abcdef1234",
        {
            "endpoint": "https://gmailmcp.googleapis.com/mcp/v1",
            "authType": "oauth",
            "oauthProvider": "google",
            "secretArn": user_secret,
            "oauthClientSecretArn": client_secret,
            "allowedTools": ["search_threads", "create_draft"],
        },
    )

    mcp_connections.connection_client(binding)

    assert captured["transport"].args == (
        "https://gmailmcp.googleapis.com/mcp/v1",
        {"Authorization": "Bearer access-token"},
    )
    assert captured["tool_filters"] == {"allowed": ["search_threads", "create_draft"]}


def test_google_oauth_connection_rejects_destructive_tools(monkeypatch) -> None:
    monkeypatch.setattr(mcp_connections.socket, "getaddrinfo", _public_address)

    try:
        mcp_connections.validated_connection_binding(
            "connection_1234567890abcdef1234",
            {
                "endpoint": "https://gmailmcp.googleapis.com/mcp/v1",
                "authType": "oauth",
                "oauthProvider": "google",
                "secretArn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                    "frogbot/connections/abcdef1234567890abcdef12/"
                    "connection_1234567890abcdef1234-abcdef123456-ABC123"
                ),
                "oauthClientSecretArn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                    "frogbot/oauth/google-ABC123"
                ),
                "allowedTools": ["search_threads", "trash_thread"],
            },
        )
    except ValueError as error:
        assert "OAuth" in str(error)
    else:
        raise AssertionError("destructive Gmail tool was accepted")
