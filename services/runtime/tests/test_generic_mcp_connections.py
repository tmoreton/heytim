from __future__ import annotations

import json

from heytim_runtime import mcp_connections


def test_generic_mcp_server_uses_its_own_private_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr(
        mcp_connections.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    secret = (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        "heytim/connections/abcdef1234567890abcdef12/"
        "connection_1234567890abcdef1234-abcdef123456-ABC123"
    )
    binding = mcp_connections.validated_connection_binding(
        "connection_1234567890abcdef1234",
        {
            "endpoint": "https://planning.example.com/mcp",
            "authType": "bearer_token",
            "secretArn": secret,
        },
    )

    class FakeSecrets:
        def get_secret_value(self, *, SecretId: str) -> dict:
            assert SecretId == secret
            return {"SecretString": json.dumps({"accessToken": "p" * 48})}

    monkeypatch.setattr(mcp_connections, "_secrets_manager", FakeSecrets())
    assert mcp_connections._mcp_access_token(binding) == "p" * 48
    captured = {}

    def fake_client(transport, **options):
        captured["transport"] = transport
        captured["options"] = options
        return object()

    monkeypatch.setattr(mcp_connections, "BoundedMCPClient", fake_client)
    mcp_connections.connection_client(binding)
    assert captured["transport"].args == (
        "https://planning.example.com/mcp",
        {"Authorization": "Bearer " + "p" * 48},
    )
