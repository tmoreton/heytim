from __future__ import annotations

import json

import pytest

from frogbot_runtime import provider_connections

USER_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "frogbot/connections/abcdef1234567890abcdef12/"
    "connection_1234567890abcdef1234-abcdef123456-ABC123"
)
GOOGLE_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "frogbot/oauth/google-production-ABC123"
)
X_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "frogbot/oauth/x-production-ABC123"
)
SLACK_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "frogbot/oauth/slack-production-ABC123"
)
MICROSOFT_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "frogbot/oauth/microsoft-production-ABC123"
)
NOTION_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "frogbot/oauth/notion-production-ABC123"
)


class Usage:
    def __init__(self) -> None:
        self.calls = []

    def observe_tool(self, provider: str, operation: str) -> None:
        self.calls.append((provider, operation))


def _youtube_binding() -> dict:
    return provider_connections.validated_provider_binding(
        "connection_1234567890abcdef1234",
        {
            "kind": "provider_api",
            "provider": "youtube",
            "authType": "oauth",
            "oauthProvider": "google",
            "secretArn": USER_SECRET,
            "oauthClientSecretArn": GOOGLE_SECRET,
            "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
        },
    )


def _provider_binding(provider: str, secret_arn: str) -> dict:
    return provider_connections.validated_provider_binding(
        "connection_1234567890abcdef1234",
        {
            "kind": "provider_api",
            "provider": provider,
            "authType": "oauth",
            "oauthProvider": provider,
            "secretArn": USER_SECRET,
            "oauthClientSecretArn": secret_arn,
            "scopes": list(provider_connections.PROVIDER_SCOPES[provider]),
        },
    )


def test_youtube_connection_exposes_only_own_channel_read_tools(monkeypatch) -> None:
    usage = Usage()
    monkeypatch.setattr(
        provider_connections, "_google_access_token", lambda _binding: "access-token"
    )
    responses = iter(
        [
            {
                "items": [
                    {
                        "id": "channel-1",
                        "snippet": {"title": "My channel"},
                        "statistics": {"subscriberCount": "7"},
                        "status": {"privacyStatus": "public"},
                    }
                ]
            },
            {
                "items": [
                    {
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": "uploads-1"}
                        }
                    }
                ]
            },
            {
                "items": [
                    {
                        "snippet": {"title": "Private preview"},
                        "contentDetails": {
                            "videoId": "video-1",
                            "videoPublishedAt": "2026-09-13T12:00:00Z",
                        },
                        "status": {"privacyStatus": "private"},
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(
        provider_connections, "_api_json", lambda *_args: next(responses)
    )
    tools = provider_connections.provider_connection_tools(_youtube_binding(), usage)

    assert [item.tool_name for item in tools] == [
        "youtube_my_channel",
        "youtube_my_videos",
    ]
    assert json.loads(tools[0]())["snippet"]["title"] == "My channel"
    assert json.loads(tools[1](5))["videos"] == [
        {
            "videoId": "video-1",
            "title": "Private preview",
            "publishedAt": "2026-09-13T12:00:00Z",
            "privacyStatus": "private",
        }
    ]
    assert usage.calls == [
        ("youtube", "youtube_my_channel"),
        ("youtube", "youtube_my_videos"),
    ]


def test_x_refresh_rotation_is_saved_before_use(monkeypatch) -> None:
    class FakeSecrets:
        def __init__(self) -> None:
            self.saved = None

        def get_secret_value(self, *, SecretId: str) -> dict:
            if SecretId == USER_SECRET:
                return {"SecretString": json.dumps({"refreshToken": "old-refresh"})}
            assert SecretId == X_SECRET
            return {
                "SecretString": json.dumps(
                    {"clientId": "client-id", "clientSecret": "client-secret"}
                )
            }

        def put_secret_value(self, **kwargs) -> None:
            self.saved = kwargs

    secrets = FakeSecrets()
    monkeypatch.setattr(provider_connections, "_secrets_manager", secrets)
    monkeypatch.setattr(
        provider_connections,
        "_token_json",
        lambda _request: {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 7_200,
        },
    )
    binding = provider_connections.validated_provider_binding(
        "connection_1234567890abcdef1234",
        {
            "kind": "provider_api",
            "provider": "x",
            "authType": "oauth",
            "oauthProvider": "x",
            "secretArn": USER_SECRET,
            "oauthClientSecretArn": X_SECRET,
            "scopes": ["tweet.read", "users.read", "offline.access"],
        },
    )

    assert provider_connections._x_access_token(binding) == "new-access"
    assert secrets.saved["SecretId"] == USER_SECRET
    saved = json.loads(secrets.saved["SecretString"])
    assert saved["refreshToken"] == "new-refresh"
    assert saved["accessToken"] == "new-access"
    assert saved["expiresAt"] > 0


def test_provider_connection_rejects_write_scopes() -> None:
    with pytest.raises(ValueError, match="OAuth provider"):
        provider_connections.validated_provider_binding(
            "connection_1234567890abcdef1234",
            {
                "kind": "provider_api",
                "provider": "x",
                "authType": "oauth",
                "oauthProvider": "x",
                "secretArn": USER_SECRET,
                "oauthClientSecretArn": X_SECRET,
                "scopes": ["tweet.read", "tweet.write", "users.read", "offline.access"],
            },
        )


def test_external_providers_expose_only_reviewed_read_tools() -> None:
    expectations = {
        "slack": (
            SLACK_SECRET,
            ["slack_search", "slack_thread"],
        ),
        "microsoft": (
            MICROSOFT_SECRET,
            [
                "microsoft_recent_mail",
                "microsoft_calendar_events",
                "microsoft_search_content",
            ],
        ),
        "notion": (
            NOTION_SECRET,
            ["notion_search", "notion_page", "notion_block_children"],
        ),
    }
    for provider, (secret_arn, expected) in expectations.items():
        binding = _provider_binding(provider, secret_arn)
        tools = provider_connections.provider_connection_tools(binding)
        assert [item.tool_name for item in tools] == expected
        assert not any(
            word in item.tool_name
            for item in tools
            for word in ("send", "write", "create", "update", "delete")
        )


def test_slack_rotation_saves_replacement_before_use(monkeypatch) -> None:
    class FakeSecrets:
        def __init__(self) -> None:
            self.saved = None

        def get_secret_value(self, *, SecretId: str) -> dict:
            if SecretId == USER_SECRET:
                return {"SecretString": json.dumps({"refreshToken": "old-refresh"})}
            assert SecretId == SLACK_SECRET
            return {
                "SecretString": json.dumps(
                    {"clientId": "client-id", "clientSecret": "client-secret"}
                )
            }

        def put_secret_value(self, **kwargs) -> None:
            self.saved = kwargs

    secrets = FakeSecrets()
    monkeypatch.setattr(provider_connections, "_secrets_manager", secrets)
    monkeypatch.setattr(
        provider_connections,
        "_token_json",
        lambda _request: {
            "ok": True,
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 43_200,
        },
    )

    assert (
        provider_connections._provider_access_token(
            _provider_binding("slack", SLACK_SECRET)
        )
        == "new-access"
    )
    saved = json.loads(secrets.saved["SecretString"])
    assert secrets.saved["SecretId"] == USER_SECRET
    assert saved["refreshToken"] == "new-refresh"
    assert saved["accessToken"] == "new-access"


def test_slack_search_enforces_live_api_page_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        provider_connections, "_provider_access_token", lambda _binding: "token"
    )
    monkeypatch.setattr(
        provider_connections,
        "_provider_api_json",
        lambda *_args, **_kwargs: {"ok": True, "results": {}},
    )
    search = provider_connections.provider_connection_tools(
        _provider_binding("slack", SLACK_SECRET)
    )[0]

    assert json.loads(search("frog", 20))["ok"] is True
    with pytest.raises(ValueError, match="between 1 and 20"):
        search("frog", 21)


def test_external_provider_binding_rejects_write_scope() -> None:
    with pytest.raises(ValueError, match="OAuth provider"):
        provider_connections.validated_provider_binding(
            "connection_1234567890abcdef1234",
            {
                "kind": "provider_api",
                "provider": "microsoft",
                "authType": "oauth",
                "oauthProvider": "microsoft",
                "secretArn": USER_SECRET,
                "oauthClientSecretArn": MICROSOFT_SECRET,
                "scopes": [
                    *provider_connections.PROVIDER_SCOPES["microsoft"],
                    "Mail.Send",
                ],
            },
        )
