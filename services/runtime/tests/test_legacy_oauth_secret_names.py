from __future__ import annotations

import pytest

from heytim_runtime import mcp_connections, provider_connections

USER_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "heytim/connections/abcdef1234567890abcdef12/"
    "connection_1234567890abcdef1234-abcdef123456-ABC123"
)


def _app_secret(namespace: str, provider: str) -> str:
    return (
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
        f"{namespace}/oauth/{provider}-production-ABC123"
    )


def _provider_binding(provider: str, app_secret: str) -> dict:
    return provider_connections.validated_provider_binding(
        "connection_1234567890abcdef1234",
        {
            "kind": "provider_api",
            "provider": provider,
            "authType": "oauth",
            "oauthProvider": "google" if provider == "youtube" else provider,
            "secretArn": USER_SECRET,
            "oauthClientSecretArn": app_secret,
            "scopes": list(provider_connections.PROVIDER_SCOPES[provider]),
        },
    )


@pytest.mark.parametrize(
    ("provider", "app_provider"),
    [
        ("youtube", "google"),
        ("x", "x"),
        ("slack", "slack"),
        ("microsoft", "microsoft"),
        ("microsoft_teams", "microsoft"),
        ("notion", "notion"),
        ("hubspot", "hubspot"),
        ("zoom", "zoom"),
    ],
)
def test_oauth_provider_bindings_accept_retained_app_secret_names(
    provider: str, app_provider: str
) -> None:
    app_secret = _app_secret("heytim", app_provider)
    assert _provider_binding(provider, app_secret)["oauthClientSecretArn"] == app_secret


@pytest.mark.parametrize(
    ("provider", "app_provider"),
    [("youtube", "google"), ("x", "x"), ("slack", "slack"), ("notion", "notion")],
)
def test_provider_bindings_accept_existing_legacy_app_secret_names(
    provider: str, app_provider: str
) -> None:
    app_secret = _app_secret("frogbot", app_provider)
    assert _provider_binding(provider, app_secret)["oauthClientSecretArn"] == app_secret


@pytest.mark.parametrize("namespace", ["other", "frogbot/connections"])
def test_provider_binding_rejects_unapproved_app_secret_namespace(
    namespace: str,
) -> None:
    with pytest.raises(ValueError, match="OAuth provider connection is invalid"):
        _provider_binding("youtube", _app_secret(namespace, "google"))


def test_provider_binding_rejects_wrong_app_secret_provider() -> None:
    with pytest.raises(ValueError, match="OAuth provider connection is invalid"):
        _provider_binding("youtube", _app_secret("frogbot", "notion"))


def test_provider_binding_rejects_unstaged_legacy_app_secret_name() -> None:
    with pytest.raises(ValueError, match="OAuth provider connection is invalid"):
        _provider_binding("microsoft", _app_secret("frogbot", "microsoft"))


@pytest.mark.parametrize(
    "app_secret",
    [
        _app_secret("frogbot", "google").replace("-production-", "-staging-"),
        _app_secret("frogbot", "google") + "7",
    ],
)
def test_provider_binding_rejects_other_legacy_secret_names(app_secret: str) -> None:
    with pytest.raises(ValueError, match="OAuth provider connection is invalid"):
        _provider_binding("youtube", app_secret)


def test_plaid_binding_accepts_heytim_app_secret_name() -> None:
    app_secret = _app_secret("heytim", "plaid")
    binding = provider_connections.validated_provider_binding(
        "connection_1234567890abcdef1234",
        {
            "kind": "provider_api",
            "provider": "plaid",
            "authType": "plaid_link",
            "secretArn": USER_SECRET,
            "appSecretArn": app_secret,
            "environment": "production",
        },
    )
    assert binding["appSecretArn"] == app_secret


@pytest.mark.parametrize(
    "app_secret", [_app_secret("frogbot", "plaid"), _app_secret("frogbot", "google")]
)
def test_plaid_binding_rejects_unstaged_app_secret(app_secret: str) -> None:
    with pytest.raises(ValueError, match="Plaid provider connection is invalid"):
        provider_connections.validated_provider_binding(
            "connection_1234567890abcdef1234",
            {
                "provider": "plaid",
                "authType": "plaid_link",
                "secretArn": USER_SECRET,
                "appSecretArn": app_secret,
                "environment": "production",
            },
        )


@pytest.mark.parametrize("namespace", ["heytim", "frogbot"])
@pytest.mark.parametrize(
    ("auth_type", "provider", "endpoint", "app_secret_key"),
    [
        ("oauth", "google", mcp_connections.GMAIL_MCP_ENDPOINT, "oauthClientSecretArn"),
        ("github_app", "github", mcp_connections.GITHUB_MCP_ENDPOINT, "appSecretArn"),
    ],
)
def test_mcp_bindings_accept_retained_app_secret_names(
    monkeypatch,
    namespace: str,
    auth_type: str,
    provider: str,
    endpoint: str,
    app_secret_key: str,
) -> None:
    monkeypatch.setattr(
        mcp_connections.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    app_secret = _app_secret(namespace, provider)
    binding = mcp_connections.validated_connection_binding(
        "connection_1234567890abcdef1234",
        {
            "kind": "mcp",
            "endpoint": endpoint,
            "authType": auth_type,
            "secretArn": USER_SECRET,
            app_secret_key: app_secret,
            **(
                {
                    "oauthProvider": "google",
                    "allowedTools": [min(mcp_connections.GMAIL_MCP_TOOLS)],
                }
                if provider == "google"
                else {}
            ),
        },
    )
    assert binding[app_secret_key] == app_secret


@pytest.mark.parametrize(
    "app_secret",
    [
        _app_secret("other", "google"),
        _app_secret("frogbot", "github"),
    ],
)
def test_google_mcp_binding_rejects_wrong_app_secret(
    monkeypatch, app_secret: str
) -> None:
    monkeypatch.setattr(
        mcp_connections.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    with pytest.raises(ValueError, match="OAuth MCP connection is invalid"):
        mcp_connections.validated_connection_binding(
            "connection_1234567890abcdef1234",
            {
                "endpoint": mcp_connections.GMAIL_MCP_ENDPOINT,
                "authType": "oauth",
                "oauthProvider": "google",
                "secretArn": USER_SECRET,
                "oauthClientSecretArn": app_secret,
                "allowedTools": [min(mcp_connections.GMAIL_MCP_TOOLS)],
            },
        )


def test_workspace_bundle_accepts_retained_google_app_secret(monkeypatch) -> None:
    monkeypatch.setattr(
        mcp_connections.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    app_secret = _app_secret("frogbot", "google")
    binding = mcp_connections.validated_connection_bundle_binding(
        "connection_1234567890abcdef1234",
        {
            "kind": "mcp_bundle",
            "authType": "oauth",
            "oauthProvider": "google",
            "secretArn": USER_SECRET,
            "oauthClientSecretArn": app_secret,
            "scopes": list(mcp_connections.GOOGLE_WORKSPACE_SCOPES),
            "servers": [
                {"endpoint": endpoint, "allowedTools": list(tools)}
                for endpoint, tools in mcp_connections.GOOGLE_WORKSPACE_MCP_SERVERS.items()
            ],
        },
    )
    assert binding["oauthClientSecretArn"] == app_secret


def test_user_connection_secret_stays_in_heytim_namespace() -> None:
    legacy_user_secret = USER_SECRET.replace(
        "heytim/connections", "frogbot/connections"
    )
    with pytest.raises(ValueError, match="OAuth provider connection is invalid"):
        provider_connections.validated_provider_binding(
            "connection_1234567890abcdef1234",
            {
                "provider": "youtube",
                "authType": "oauth",
                "oauthProvider": "google",
                "secretArn": legacy_user_secret,
                "oauthClientSecretArn": _app_secret("frogbot", "google"),
                "scopes": list(provider_connections.PROVIDER_SCOPES["youtube"]),
            },
        )
