from __future__ import annotations

import json

import pytest

from frogbot_runtime import provider_connections
from frogbot_runtime.mcp_connections import _bounded_tool_name

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
HUBSPOT_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "frogbot/oauth/hubspot-production-ABC123"
)
JIRA_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "frogbot/oauth/jira-production-ABC123"
)
ZOOM_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "frogbot/oauth/zoom-production-ABC123"
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
            **(
                {"siteId": "11223344-a1b2-3b33-c444-def123456789"}
                if provider == "jira" else {}
            ),
        },
    )


def test_youtube_connection_exposes_search_and_own_channel_read_tools(monkeypatch) -> None:
    usage = Usage()
    monkeypatch.setattr(
        provider_connections, "_google_access_token", lambda _binding: "access-token"
    )
    responses = iter(
        [
            {"items": [{"id": {"videoId": "public-1"}}], "pageInfo": {"totalResults": 1}},
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
        _bounded_tool_name(_youtube_binding()["id"], name)
        for name in ("youtube_search", "youtube_my_channel", "youtube_my_videos")
    ]
    assert json.loads(tools[0]("frogs"))["videos"][0]["id"]["videoId"] == "public-1"
    assert json.loads(tools[1]())["snippet"]["title"] == "My channel"
    assert json.loads(tools[2](5))["videos"] == [
        {
            "videoId": "video-1",
            "title": "Private preview",
            "publishedAt": "2026-09-13T12:00:00Z",
            "privacyStatus": "private",
        }
    ]
    assert usage.calls == [
        ("youtube", "youtube_search"),
        ("youtube", "youtube_my_channel"),
        ("youtube", "youtube_my_videos"),
    ]


def test_x_search_uses_only_the_connected_accounts_token(monkeypatch) -> None:
    usage = Usage()
    urls = []
    monkeypatch.setattr(
        provider_connections, "_x_access_token", lambda _binding: "user-access-token"
    )
    monkeypatch.setattr(
        provider_connections, "_api_json",
        lambda url, token: urls.append((url, token)) or {"data": [{"id": "post-1"}]},
    )
    tools = provider_connections.provider_connection_tools(
        _provider_binding("x", X_SECRET), usage
    )
    search = next(item for item in tools if item.tool_name.endswith("_x_search_recent"))
    assert json.loads(search("frogs"))["posts"] == [{"id": "post-1"}]
    assert urls[0][0].startswith("https://api.x.com/2/tweets/search/recent?")
    assert urls[0][1] == "user-access-token"
    assert usage.calls == [("x", "x_search_recent")]


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
        "hubspot": (
            HUBSPOT_SECRET,
            ["hubspot_contacts", "hubspot_companies", "hubspot_deals"],
        ),
        "jira": (
            JIRA_SECRET,
            ["jira_projects", "jira_search_issues", "jira_issue"],
        ),
        "microsoft_teams": (
            MICROSOFT_SECRET,
            ["teams_joined", "teams_channels", "teams_messages"],
        ),
        "zoom": (
            ZOOM_SECRET,
            ["zoom_meetings", "zoom_meeting"],
        ),
    }
    for provider, (secret_arn, expected) in expectations.items():
        binding = _provider_binding(provider, secret_arn)
        tools = provider_connections.provider_connection_tools(binding)
        assert [item.tool_name for item in tools] == [
            _bounded_tool_name(binding["id"], name) for name in expected
        ]
        assert not any(
            word in item.tool_name
            for item in tools
            for word in ("send", "write", "create", "update", "delete")
        )


def test_two_accounts_have_distinct_labeled_tools_and_tokens(monkeypatch) -> None:
    first = _provider_binding("hubspot", HUBSPOT_SECRET)
    second = {**first, "id": "connection_abcdef1234567890abcd"}
    first["accountLabel"] = "Sales team"
    second["accountLabel"] = "Support team"
    calls = []
    monkeypatch.setattr(
        provider_connections,
        "_provider_access_token",
        lambda binding: f"token-{binding['id']}",
    )
    monkeypatch.setattr(
        provider_connections,
        "_provider_api_json",
        lambda url, token, **_kwargs: calls.append((url, token)) or {"results": []},
    )
    first_tool = provider_connections.provider_connection_tools(first)[0]
    second_tool = provider_connections.provider_connection_tools(second)[0]
    assert first_tool.tool_name != second_tool.tool_name
    assert "Sales team" in first_tool.tool_spec["description"]
    assert "Support team" in second_tool.tool_spec["description"]
    first_tool("Ada")
    second_tool("Ada")
    assert [token for _, token in calls] == [
        f"token-{first['id']}", f"token-{second['id']}"
    ]


def test_hubspot_search_uses_only_the_assigned_connection(monkeypatch) -> None:
    usage = Usage()
    calls = []
    monkeypatch.setattr(
        provider_connections, "_provider_access_token", lambda _binding: "hubspot-token"
    )
    monkeypatch.setattr(
        provider_connections,
        "_provider_api_json",
        lambda url, token, **kwargs: calls.append((url, token, kwargs))
        or {"results": [{"id": "42"}], "total": 1},
    )
    tools = provider_connections.provider_connection_tools(
        _provider_binding("hubspot", HUBSPOT_SECRET), usage
    )
    assert json.loads(tools[0]("Ada"))["results"] == [{"id": "42"}]
    assert calls[0][0].endswith("/crm/objects/2026-03/contacts/search")
    assert calls[0][1] == "hubspot-token"
    assert calls[0][2]["payload"]["query"] == "Ada"
    assert usage.calls == [("hubspot", "hubspot_contacts")]


def test_jira_tools_use_only_the_selected_site(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        provider_connections, "_provider_access_token", lambda _binding: "jira-token"
    )
    monkeypatch.setattr(
        provider_connections,
        "_provider_api_json",
        lambda url, token, **_kwargs: calls.append((url, token))
        or {"issues": [], "total": 0},
    )
    tools = provider_connections.provider_connection_tools(
        _provider_binding("jira", JIRA_SECRET)
    )
    tools[1]("FROG", "crash")
    assert calls[0][0].startswith(
        "https://api.atlassian.com/ex/jira/"
        "11223344-a1b2-3b33-c444-def123456789/rest/api/3/search/jql?"
    )
    assert calls[0][1] == "jira-token"


def test_jira_project_selection_blocks_other_project_before_api(monkeypatch) -> None:
    binding = _provider_binding("jira", JIRA_SECRET)
    binding["projectKeys"] = ["FROG"]
    monkeypatch.setattr(
        provider_connections, "_provider_access_token", lambda _binding: "jira-token"
    )
    calls = []
    monkeypatch.setattr(
        provider_connections,
        "_provider_api_json",
        lambda url, *_args, **_kwargs: calls.append(url) or {"issues": []},
    )
    tools = provider_connections.provider_connection_tools(binding)
    with pytest.raises(ValueError, match="not assigned"):
        tools[1]("OTHER", "bug")
    with pytest.raises(ValueError, match="not assigned"):
        tools[2]("OTHER-12")
    assert calls == []


def test_teams_channel_selection_blocks_other_channels_before_api(monkeypatch) -> None:
    binding = _provider_binding("microsoft_teams", MICROSOFT_SECRET)
    team = "11223344-a1b2-3b33-c444-def123456789"
    binding["channelAccess"] = [f"{team}/19:selected@thread.tacv2"]
    calls = []
    monkeypatch.setattr(
        provider_connections, "_provider_access_token", lambda _binding: "teams-token"
    )
    monkeypatch.setattr(
        provider_connections, "_api_json",
        lambda url, *_args: calls.append(url) or {"value": []},
    )
    tools = provider_connections.provider_connection_tools(binding)
    with pytest.raises(ValueError, match="not assigned"):
        tools[2](team, "19:other@thread.tacv2")
    assert calls == []
    tools[2](team, "19:selected@thread.tacv2")
    assert len(calls) == 1


def test_slack_channel_selection_filters_search_and_blocks_threads(monkeypatch) -> None:
    binding = _provider_binding("slack", SLACK_SECRET)
    binding["resourceIds"] = ["C123ABC456"]
    calls = []
    monkeypatch.setattr(
        provider_connections, "_provider_access_token", lambda _binding: "slack-token"
    )
    monkeypatch.setattr(
        provider_connections, "_provider_api_json",
        lambda _url, _token, **kwargs: calls.append(kwargs) or {
            "ok": True,
            "results": {
                "messages": [
                    {"channel_id": "C123ABC456", "content": "allowed"},
                    {"channel_id": "C999ABC456", "content": "private"},
                ],
                "files": [{"content": "private"}],
            },
        },
    )
    tools = provider_connections.provider_connection_tools(binding)
    result = json.loads(tools[0]("planning"))
    assert result == {"ok": True, "results": {"messages": [
        {"channel_id": "C123ABC456", "content": "allowed"}
    ]}}
    assert calls[0]["payload"]["content_types"] == ["messages"]
    with pytest.raises(ValueError, match="not assigned"):
        tools[1]("C999ABC456", "123.456")


def test_notion_page_selection_allows_only_descendant_blocks(monkeypatch) -> None:
    binding = _provider_binding("notion", NOTION_SECRET)
    page = "11223344-a1b2-3b33-c444-def123456789"
    child = "22223344-a1b2-3b33-c444-def123456789"
    other = "33333344-a1b2-3b33-c444-def123456789"
    binding["resourceIds"] = [page]
    calls = []
    monkeypatch.setattr(
        provider_connections, "_provider_access_token", lambda _binding: "notion-token"
    )
    monkeypatch.setattr(
        provider_connections, "_provider_api_json",
        lambda url, *_args, **_kwargs: calls.append(url) or {
            "results": [{"id": child}] if page in url else []
        },
    )
    tools = provider_connections.provider_connection_tools(binding)
    with pytest.raises(ValueError, match="not assigned"):
        tools[2](other)
    assert calls == []
    tools[2](page)
    tools[2](child)
    assert len(calls) == 2


def test_zoom_meeting_tool_returns_no_host_start_url(monkeypatch) -> None:
    monkeypatch.setattr(
        provider_connections, "_provider_access_token", lambda _binding: "zoom-token"
    )
    monkeypatch.setattr(
        provider_connections, "_api_json",
        lambda url, *_args: (
            {"meetings": [{"id": 123456789, "topic": "Planning", "start_url": "host-secret"}]}
            if "/users/me/meetings" in url else
            {"id": 123456789, "topic": "Planning", "start_url": "host-secret"}
        ),
    )
    tools = provider_connections.provider_connection_tools(
        _provider_binding("zoom", ZOOM_SECRET)
    )
    listed = json.loads(tools[0]())["meetings"]
    result = json.loads(tools[1]("123456789"))
    assert result["topic"] == "Planning"
    assert "start_url" not in result
    assert "start_url" not in listed[0]


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
