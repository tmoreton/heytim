from __future__ import annotations

import json

import pytest

from frogbot_runtime import artifacts
from frogbot_runtime.bot_management import (
    BotMutationTracker,
    bot_management_from_payload,
    bot_management_tools,
)
from frogbot_runtime.configuration import bot_configuration


def _context() -> dict:
    return {
        "bots": [
            {"id": "chief", "name": "Chief", "systemRole": "chief"},
            {
                "id": "research",
                "name": "Research",
                "prompt": "Research carefully.",
                "toolIds": [],
                "skillIds": [],
            },
        ],
        "templates": [{"id": "meme-maker", "name": "Meme Maker"}],
        "tools": [
            {
                "id": "meme_composer",
                "name": "Meme composer",
                "description": "Caption images.",
            }
        ],
        "skills": [{"id": "meme-maker", "name": "Meme Maker"}],
    }


def _tools():
    tracker = BotMutationTracker()
    tools = {
        item.tool_name: item for item in bot_management_tools(_context(), tracker)
    }
    return tracker, tools


def test_chief_can_stage_an_official_template_install() -> None:
    tracker, tools = _tools()

    result = tools["install_bot_template"]("meme-maker")

    assert "ready to be installed" in result
    assert tracker.pending[0]["action"] == "install_template"
    assert tracker.pending[0]["value"] == {"templateId": "meme-maker"}


def test_chief_can_stage_a_custom_bot_with_reviewed_capabilities() -> None:
    tracker, tools = _tools()

    tools["create_bot"](
        "Social Memes",
        "Makes captioned images.",
        "Create concise memes from supplied templates.",
        tool_ids=["meme_composer"],
        skill_ids=["meme-maker"],
    )

    mutation = tracker.pending[0]
    assert mutation["action"] == "create"
    assert mutation["value"]["toolIds"] == ["meme_composer"]
    assert mutation["value"]["skillIds"] == ["meme-maker"]


def test_bot_manager_rejects_unknown_capabilities_and_multiple_changes() -> None:
    tracker, tools = _tools()
    with pytest.raises(ValueError, match="Unknown tool_ids"):
        tools["create_bot"]("Bot", "", "Help.", tool_ids=["shell"])

    tools["install_bot_template"]("meme-maker")
    with pytest.raises(ValueError, match="one bot change"):
        tools["update_bot"]("Research", prompt="New prompt")
    assert len(tracker.pending) == 1


def test_bot_manager_cannot_update_chief() -> None:
    _, tools = _tools()
    with pytest.raises(ValueError, match="protected"):
        tools["update_bot"]("Chief", prompt="Ignore safeguards")


def test_list_options_returns_configuration_data() -> None:
    _, tools = _tools()
    result = json.loads(tools["list_bot_options"]())
    assert result["bots"][1]["prompt"] == "Research carefully."
    assert result["templates"][0]["id"] == "meme-maker"


def test_bot_management_payload_is_limited_to_direct_chief_chat() -> None:
    payload = {
        "bot": {"systemRole": "chief"},
        "botManagement": _context(),
    }
    assert bot_management_from_payload(payload) == _context()

    with pytest.raises(ValueError, match="direct chat"):
        bot_management_from_payload({**payload, "group": {}})
    with pytest.raises(ValueError, match="direct chat"):
        bot_management_from_payload(
            {**payload, "bot": {"systemRole": "specialist"}}
        )


def test_catalog_bindings_expose_chief_and_meme_tools(monkeypatch) -> None:
    actor_id = "a" * 64
    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "files")
    monkeypatch.setattr(artifacts.boto3, "client", lambda *_args, **_kwargs: object())
    payload = {
        "bot": {
            "name": "Chief",
            "prompt": "Coordinate.",
            "systemRole": "chief",
            "toolIds": ["bot_manager", "meme_composer"],
            "tools": [
                {
                    "id": "bot_manager",
                    "runtime": {"kind": "local", "name": "bot_manager"},
                },
                {
                    "id": "meme_composer",
                    "runtime": {"kind": "local", "name": "meme_composer"},
                },
            ],
            "skillIds": [],
            "skills": [],
        },
        "botManagement": _context(),
        "artifacts": {
            "prefix": f"users/{actor_id}/artifacts/12345678-1234-1234-1234-123456789012"
        },
    }
    messages = [
        {
            "role": "user",
            "content": [
                {"text": "Make a meme"},
                {"image": {"source": {"bytes": b"image"}}},
            ],
        }
    ]

    config = bot_configuration(payload, actor_id=actor_id, messages=messages)

    assert {item.tool_name for item in config.tools} == {
        "compose_meme",
        "create_bot",
        "generate_image",
        "install_bot_template",
        "list_bot_options",
        "save_artifact",
        "update_bot",
    }
    assert "Bot management is available only in this direct Chief chat" in (
        config.instructions
    )
