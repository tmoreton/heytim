from __future__ import annotations

import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

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
        def __init__(self, **kwargs):
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

    assert captured["url"] == "https://mcp.example.com/mcp"
    assert captured["headers"] == {"Authorization": "Bearer private-token"}
    assert captured["prefix"] == "connection_1234567890abcdef1234"


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
