from __future__ import annotations

import base64
import json
from email import policy
from email.parser import BytesParser

import pytest

from heytim_runtime import capabilities, gmail_api
from heytim_runtime.mcp_connections import GMAIL_MCP_ENDPOINT, _bounded_tool_name

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


def _tools(artifact_prefix: str | None = None, storage_client=None) -> dict:
    return {
        tool.tool_name: tool
        for tool in gmail_api.gmail_api_tools(
            BINDING, artifact_prefix, storage_client=storage_client
        )
    }


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_gmail_tools_keep_the_existing_connection_tool_names() -> None:
    assert set(_tools()) == {
        _bounded_tool_name(CONNECTION_ID, remote) for remote in BINDING["allowedTools"]
    }


def test_gmail_tools_identify_the_selected_account() -> None:
    binding = {**BINDING, "accountLabel": "work@example.com"}
    tools = gmail_api.gmail_api_tools(binding)
    assert all("work@example.com" in item.tool_spec["description"] for item in tools)
    assert {item.tool_name for item in tools} == set(_tools())


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


def test_create_draft_embeds_a_scoped_png_in_safe_html(monkeypatch) -> None:
    captured = {}
    image_id = "12345678-1234-4234-8234-123456789012"
    prefix = f"users/{'a' * 64}/artifacts/12345678-1234-1234-1234-123456789012"
    monkeypatch.setattr(gmail_api, "_google_access_token", lambda _binding: "token")
    monkeypatch.setattr(
        gmail_api.artifacts,
        "load_png_artifact",
        lambda scoped_prefix, artifact_id, client=None: (
            {
                "artifactId": artifact_id,
                "filename": "Delta award.png",
                "contentType": "image/png",
                "body": gmail_api.artifacts.PNG_SIGNATURE + b"image",
            }
            if scoped_prefix == prefix and artifact_id == image_id
            else (_ for _ in ()).throw(ValueError("inline image is unavailable"))
        ),
    )

    def fake_api(_token, path, **kwargs):
        captured["path"] = path
        captured.update(kwargs)
        return {
            "id": "draft-1",
            "message": {"id": "message-1", "threadId": "thread-1"},
        }

    monkeypatch.setattr(gmail_api, "_api_json", fake_api)
    create = _tools(prefix)[_bounded_tool_name(CONNECTION_ID, "create_draft")]
    html_body = (
        "<html><body><h2>Delta award deal</h2>"
        f'<img src="cid:{image_id}" alt="42,000 SkyMiles award">'
        '<p><a href="https://www.delta.com/">Check current availability</a></p>'
        "</body></html>"
    )

    result = json.loads(
        create(
            "Weekly points",
            "Delta award deal: 42,000 SkyMiles.",
            htmlBody=html_body,
            inlineImageIds=[image_id],
        )
    )
    raw = captured["payload"]["message"]["raw"]
    raw += "=" * (-len(raw) % 4)
    message = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(raw)
    )
    parts = list(message.walk())

    assert captured["path"] == "drafts"
    assert any(part.get_content_type() == "text/plain" for part in parts)
    html_part = next(part for part in parts if part.get_content_type() == "text/html")
    assert f"cid:{image_id}" in html_part.get_content()
    image_part = next(part for part in parts if part.get_content_type() == "image/png")
    assert image_part["Content-ID"] == f"<{image_id}>"
    assert image_part.get_content_disposition() == "inline"
    assert image_part.get_filename() == "Delta award.png"
    assert result["status"] == "draft_created_not_sent"


@pytest.mark.parametrize(
    ("html_body", "image_ids", "message"),
    [
        (
            '<img src="https://publisher.example/deal.png">',
            [],
            "cid:<artifactId>",
        ),
        ("<script>alert(1)</script>", [], "unsupported <script>"),
        ("<svg></svg>", [], "unsupported <svg>"),
        (
            '<a href="javascript:alert(1)">deal</a>',
            [],
            "HTTPS or mailto",
        ),
        (
            '<img src="cid:12345678-1234-4234-8234-123456789012">',
            [],
            "Every inlineImageId",
        ),
    ],
)
def test_create_draft_rejects_unsafe_or_unscoped_html(
    monkeypatch, html_body, image_ids, message
) -> None:
    monkeypatch.setattr(gmail_api, "_google_access_token", lambda _binding: "token")
    create = _tools()[_bounded_tool_name(CONNECTION_ID, "create_draft")]

    with pytest.raises(ValueError, match=message):
        create(
            "Weekly points", "Fallback", htmlBody=html_body, inlineImageIds=image_ids
        )


def test_capabilities_use_general_availability_gmail_tools(monkeypatch) -> None:
    gmail_tools = [type("Tool", (), {"tool_name": "gmail-search"})()]
    monkeypatch.setattr(
        capabilities, "gmail_api_tools", lambda _binding, _prefix: gmail_tools
    )
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


def test_expired_workspace_connection_does_not_disable_fresh_gmail(
    monkeypatch, caplog
) -> None:
    gmail_tools = [type("Tool", (), {"tool_name": "gmail-search"})()]
    workspace = {
        "id": "connection_workspace",
        "kind": "mcp_bundle",
        "authType": "oauth",
    }
    monkeypatch.setattr(
        capabilities, "gmail_api_tools", lambda _binding, _prefix: gmail_tools
    )

    def unavailable(_binding):
        raise capabilities.ConnectionCredentialUnavailable(
            "OAuth access token is unavailable"
        )

    monkeypatch.setattr(capabilities, "connection_clients", unavailable)
    monkeypatch.setattr(
        capabilities,
        "tool_bindings",
        lambda _bot: [BINDING, workspace],
    )
    monkeypatch.setattr(capabilities, "dynamic_skills", lambda _bot: [])
    monkeypatch.setattr(capabilities, "validate_skill_selection", lambda *_args: None)

    with caplog.at_level("WARNING"):
        config = capabilities.resolve_capabilities(
            {"skillIds": [], "skills": []}, "session-1"
        )

    assert config.tools == gmail_tools
    assert "Skipping unavailable connection connection_workspace" in caplog.text
