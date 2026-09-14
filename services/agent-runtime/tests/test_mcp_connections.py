from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from functools import lru_cache

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from frogbot_runtime import github_app, mcp_connections


@lru_cache(maxsize=1)
def _test_private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _public_address(*_args, **_kwargs):
    return [(2, 1, 6, "", ("93.184.216.34", 443))]


def test_github_app_jwt_is_a_verifiable_short_lived_rs256_token() -> None:
    private_key = _test_private_key()
    token = github_app.github_app_jwt("12345", private_key, now=2_000)
    header, payload, encoded_signature = token.split(".")
    decode = lambda value: base64.urlsafe_b64decode(
        value + ("=" * (-len(value) % 4))
    )

    assert json.loads(decode(header)) == {"alg": "RS256", "typ": "JWT"}
    assert json.loads(decode(payload)) == {
        "iat": 1_940,
        "exp": 2_540,
        "iss": "12345",
    }
    modulus, _private_exponent = github_app._rsa_private_numbers(private_key)
    signature = int.from_bytes(decode(encoded_signature), "big")
    recovered = pow(signature, 65_537, modulus).to_bytes(
        (modulus.bit_length() + 7) // 8, "big"
    )
    digest_info = (
        github_app._SHA256_DIGEST_INFO_PREFIX
        + hashlib.sha256(f"{header}.{payload}".encode("ascii")).digest()
    )
    assert recovered.startswith(b"\x00\x01\xff")
    assert recovered.endswith(b"\x00" + digest_info)


def test_github_app_connection_mints_installation_token_server_side(monkeypatch) -> None:
    user_secret = (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        "frogbot/connections/abcdef1234567890abcdef12/"
        "connection_1234567890abcdef1234-abcdef123456-ABC123"
    )
    app_secret = (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        "frogbot/oauth/github-production-ABC123"
    )

    class FakeSecrets:
        def get_secret_value(self, *, SecretId: str) -> dict:
            if SecretId == user_secret:
                return {
                    "SecretString": json.dumps(
                        {
                            "installationId": "12345",
                            "repositoryIds": [101, 202],
                            "permissions": {"metadata": "read", "contents": "write"},
                        }
                    )
                }
            assert SecretId == app_secret
            return {"SecretString": json.dumps({"appId": "77", "privateKey": "pem"})}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps({"token": "installation-token"}).encode()

    captured = {}

    class FakeMCPClient:
        def __init__(self, transport, **kwargs):
            captured["transport"] = transport
            captured.update(kwargs)

    monkeypatch.setattr(mcp_connections.socket, "getaddrinfo", _public_address)
    monkeypatch.setattr(mcp_connections, "_secrets_manager", FakeSecrets())
    monkeypatch.setattr(mcp_connections, "BoundedMCPClient", FakeMCPClient)
    monkeypatch.setattr(
        mcp_connections,
        "github_app_config",
        lambda _document: {"appId": "77", "privateKey": "pem"},
    )
    monkeypatch.setattr(mcp_connections, "github_app_jwt", lambda *_args: "app-jwt")
    requests = []
    monkeypatch.setattr(
        mcp_connections.urllib.request,
        "urlopen",
        lambda request, **_kwargs: requests.append(request) or FakeResponse(),
    )
    binding = mcp_connections.validated_connection_binding(
        "connection_1234567890abcdef1234",
        {
            "endpoint": "https://api.githubcopilot.com/mcp/",
            "authType": "github_app",
            "secretArn": user_secret,
            "appSecretArn": app_secret,
        },
    )

    mcp_connections.connection_client(binding)

    assert captured["connection_id"] == "connection_1234567890abcdef1234"
    assert requests[0].full_url.endswith("/app/installations/12345/access_tokens")
    assert requests[0].get_header("Authorization") == "Bearer app-jwt"
    assert json.loads(requests[0].data) == {
        "repository_ids": [101, 202],
        "permissions": {"metadata": "read", "contents": "write"},
    }
    transport = captured["transport"]
    assert transport.func is mcp_connections._secure_streamable_http
    assert transport.args == (
        "https://api.githubcopilot.com/mcp/",
        {"Authorization": "Bearer installation-token"},
    )


def test_legacy_bearer_connection_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(mcp_connections.socket, "getaddrinfo", _public_address)

    with pytest.raises(ValueError, match="authentication"):
        mcp_connections.validated_connection_binding(
            "connection_1234567890abcdef1234",
            {
                "endpoint": "https://mcp.example.com/mcp",
                "authType": "bearer",
                "secretArn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                    "frogbot/connections/abcdef1234567890abcdef12/"
                    "connection_1234567890abcdef1234-abcdef123456-ABC123"
                ),
            },
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
        "frogbot/oauth/google-production-ABC123"
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
    monkeypatch.setattr(mcp_connections, "BoundedMCPClient", FakeMCPClient)
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


def test_google_workspace_bundle_refreshes_once_and_isolates_server_tools(
    monkeypatch,
) -> None:
    user_secret = (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        "frogbot/connections/abcdef1234567890abcdef12/"
        "connection_1234567890abcdef1234-abcdef123456-ABC123"
    )
    client_secret = (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        "frogbot/oauth/google-production-ABC123"
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

    captured = []

    class FakeMCPClient:
        def __init__(self, transport, **kwargs):
            captured.append({"transport": transport, **kwargs})

    monkeypatch.setattr(mcp_connections.socket, "getaddrinfo", _public_address)
    monkeypatch.setattr(mcp_connections, "_secrets_manager", FakeSecrets())
    token_requests = []
    monkeypatch.setattr(
        mcp_connections.urllib.request,
        "urlopen",
        lambda request, **_kwargs: token_requests.append(request) or FakeResponse(),
    )
    monkeypatch.setattr(mcp_connections, "BoundedMCPClient", FakeMCPClient)
    binding = mcp_connections.validated_connection_bundle_binding(
        "connection_1234567890abcdef1234",
        {
            "kind": "mcp_bundle",
            "authType": "oauth",
            "oauthProvider": "google",
            "secretArn": user_secret,
            "oauthClientSecretArn": client_secret,
            "scopes": list(mcp_connections.GOOGLE_WORKSPACE_SCOPES),
            "servers": [
                {"endpoint": endpoint, "allowedTools": list(tools)}
                for endpoint, tools in mcp_connections.GOOGLE_WORKSPACE_MCP_SERVERS.items()
            ],
        },
    )

    clients = mcp_connections.connection_clients(binding)

    assert len(clients) == len(captured) == 3
    assert len(token_requests) == 1
    assert {
        entry["transport"].args[0]: set(entry["tool_filters"]["allowed"])
        for entry in captured
    } == mcp_connections.GOOGLE_WORKSPACE_MCP_SERVERS
    assert all(
        entry["transport"].args[1] == {"Authorization": "Bearer access-token"}
        for entry in captured
    )
    assert len({entry["connection_id"] for entry in captured}) == 3


def test_google_workspace_bundle_rejects_unreviewed_tools(monkeypatch) -> None:
    monkeypatch.setattr(mcp_connections.socket, "getaddrinfo", _public_address)
    servers = [
        {"endpoint": endpoint, "allowedTools": list(tools)}
        for endpoint, tools in mcp_connections.GOOGLE_WORKSPACE_MCP_SERVERS.items()
    ]
    servers[0]["allowedTools"].append("delete_file")

    with pytest.raises(ValueError, match="Google Workspace"):
        mcp_connections.validated_connection_bundle_binding(
            "connection_1234567890abcdef1234",
            {
                "kind": "mcp_bundle",
                "authType": "oauth",
                "oauthProvider": "google",
                "secretArn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                    "frogbot/connections/abcdef1234567890abcdef12/"
                    "connection_1234567890abcdef1234-abcdef123456-ABC123"
                ),
                "oauthClientSecretArn": (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                    "frogbot/oauth/google-production-ABC123"
                ),
                "scopes": list(mcp_connections.GOOGLE_WORKSPACE_SCOPES),
                "servers": servers,
            },
        )


def test_remote_tool_names_are_stable_and_bounded() -> None:
    connection_id = "connection_9890808d645c4c1b8d3e"
    remote_name = "add_reply_to_pull_request_comment"

    name = mcp_connections._bounded_tool_name(connection_id, remote_name)

    assert len(name) <= 64
    assert name == mcp_connections._bounded_tool_name(connection_id, remote_name)
    assert remote_name in name


def test_very_long_remote_tool_names_keep_unique_hashes() -> None:
    connection_id = "connection_9890808d645c4c1b8d3e"
    shared = "long_remote_tool_name_" + "x" * 100
    first = mcp_connections._bounded_tool_name(connection_id, shared + "a")
    second = mcp_connections._bounded_tool_name(connection_id, shared + "b")

    assert len(first) == len(second) == 64
    assert first != second


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
