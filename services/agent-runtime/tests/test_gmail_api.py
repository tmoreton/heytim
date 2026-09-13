from __future__ import annotations

import base64
import json
from email import policy
from email.parser import BytesParser

import pytest

from frogbot_runtime import capabilities, gmail_api
from frogbot_runtime.mcp_connections import GMAIL_MCP_ENDPOINT, _bounded_tool_name

CONNECTION_ID = "connection_1234567890abcdef1234"
BINDING = {
    "id": CONNECTION_ID,
    "kind": "mcp",
    "endpoint": GMAIL_MCP_ENDPOINT,
    "authType": "oauth",
    "oauthProvider": "google",
    "secretArn": "secret",
    "oauthClientSecretArn": "client-secret",
    "allowedTools": [
        "create_draft",
        "list_drafts",
        "get_draft",
        "get_thread",
        "get_message",
        "search_threads",
        "list_labels",
    ],
}


def _tools() -> dict:
    return {tool.tool_name: tool for tool in gmail_api.gmail_api_tools(BINDING)}


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_gmail_tools_keep_the_existing_connection_tool_names() -> None:
    assert set(_tools()) == {
        _bounded_tool_name(CONNECTION_ID, remote) for remote in BINDING["allowedTools"]
    }


def test_search_threads_uses_gmail_syntax_and_returns_metadata(monkeypatch) -> None:
    calls = []
    responses = iter(
        [
            {
                "threads": [{"id": "thread-1"}],
                "nextPageToken": "next",
                "resultSizeEstimate": 8,
            },
            {
                "id": "thread-1",
                "messages": [
                    {
                        "id": "message-1",
                        "threadId": "thread-1",
                        "snippet": "A useful preview",
                        "payload": {
                            "headers": [
                                {"name": "Subject", "value": "Weekly points"},
                                {
                                    "name": "From",
                                    "value": "Editor <editor@example.com>",
                                },
                            ]
                        },
                    }
                ],
            },
        ]
    )
    monkeypatch.setattr(gmail_api, "_google_access_token", lambda _binding: "token")

    def fake_api(_token, path, **kwargs):
        calls.append((path, kwargs))
        return next(responses)

    monkeypatch.setattr(gmail_api, "_api_json", fake_api)
    search = _tools()[_bounded_tool_name(CONNECTION_ID, "search_threads")]

    result = json.loads(search("journey on points", 8))

    assert result["resultCountEstimate"] == 8
    assert result["threads"][0]["messages"][0]["subject"] == "Weekly points"
    assert calls[0][0] == "threads"
    assert calls[0][1]["query"]["q"] == "journey on points"
    assert calls[0][1]["query"]["maxResults"] == 8
    assert calls[1][0] == "threads/thread-1"
    assert calls[1][1]["query"]["format"] == "metadata"


def test_get_thread_prefers_plain_text_and_strips_html(monkeypatch) -> None:
    monkeypatch.setattr(gmail_api, "_google_access_token", lambda _binding: "token")
    monkeypatch.setattr(
        gmail_api,
        "_api_json",
        lambda *_args, **_kwargs: {
            "id": "thread-1",
            "messages": [
                {
                    "id": "message-1",
                    "threadId": "thread-1",
                    "payload": {
                        "mimeType": "multipart/alternative",
                        "headers": [{"name": "Subject", "value": "Points"}],
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {"data": _encoded("Plain newsletter")},
                            },
                            {
                                "mimeType": "text/html",
                                "body": {"data": _encoded("<p>Rich newsletter</p>")},
                            },
                        ],
                    },
                }
            ],
        },
    )
    read = _tools()[_bounded_tool_name(CONNECTION_ID, "get_thread")]

    result = json.loads(read("thread-1"))

    assert result["messages"][0]["plaintextBody"] == "Plain newsletter"
    with pytest.raises(ValueError, match="threadId is invalid"):
        read("../other-user")


def test_create_draft_builds_mime_but_never_sends(monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr(gmail_api, "_google_access_token", lambda _binding: "token")

    def fake_api(_token, path, **kwargs):
        captured["path"] = path
        captured.update(kwargs)
        return {
            "id": "draft-1",
            "message": {"id": "message-1", "threadId": "thread-1"},
        }

    monkeypatch.setattr(gmail_api, "_api_json", fake_api)
    create = _tools()[_bounded_tool_name(CONNECTION_ID, "create_draft")]

    result = json.loads(create("Weekly points", "Hello readers", ""))
    raw = captured["payload"]["message"]["raw"]
    raw += "=" * (-len(raw) % 4)
    message = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(raw)
    )

    assert captured["path"] == "drafts"
    assert message["Subject"] == "Weekly points"
    assert message["To"] is None
    assert message.get_content().strip() == "Hello readers"
    assert result == {
        "draftId": "draft-1",
        "messageId": "message-1",
        "threadId": "thread-1",
        "status": "draft_created_not_sent",
    }


def test_capabilities_use_general_availability_gmail_tools(monkeypatch) -> None:
    gmail_tools = [type("Tool", (), {"tool_name": "gmail-search"})()]
    monkeypatch.setattr(capabilities, "gmail_api_tools", lambda _binding: gmail_tools)
    monkeypatch.setattr(
        capabilities,
        "connection_clients",
        lambda _binding: (_ for _ in ()).throw(AssertionError("MCP should not run")),
    )
    monkeypatch.setattr(
        capabilities,
        "tool_bindings",
        lambda _bot: [BINDING],
    )
    monkeypatch.setattr(capabilities, "dynamic_skills", lambda _bot: [])
    monkeypatch.setattr(capabilities, "validate_skill_selection", lambda *_args: None)

    config = capabilities.resolve_capabilities(
        {"skillIds": [], "skills": []}, "session-1"
    )

    assert config.tools == gmail_tools
