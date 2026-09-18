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
        "currentBot": {
            "id": "chief",
            "name": "Chief",
            "tagline": "Coordinates the team.",
            "prompt": "Coordinate.",
            "color": "#007A3D",
            "toolIds": ["meme_lord"],
            "skillIds": [],
            "systemRole": "chief",
        },
        "canManageBots": True,
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
                "id": "meme_lord",
                "name": "Meme Lord",
                "description": "Caption images.",
            }
        ],
        "skills": [{"id": "meme-maker", "name": "Meme Maker"}],
        "selfToolIds": ["meme_lord"],
    }


def _tools():
    tracker = BotMutationTracker()
    tools = {item.tool_name: item for item in bot_management_tools(_context(), tracker)}
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
        tool_ids=["meme_lord"],
        skill_ids=["meme-maker"],
    )

    mutation = tracker.pending[0]
    assert mutation["action"] == "create"
    assert mutation["value"]["toolIds"] == ["meme_lord"]
    assert mutation["value"]["skillIds"] == ["meme-maker"]


def test_any_bot_can_stage_a_private_skill_using_only_its_existing_tools() -> None:
    tracker, tools = _tools()

    result = tools["create_skill_for_self"](
        "Newsletter Review",
        "Reviews newsletter drafts for voice and clarity.",
        "Identify observable prose problems without claiming to prove authorship.",
        required_tool_ids=["meme_lord"],
    )

    assert "created and attached" in result
    assert tracker.pending == [
        {
            "mutationId": tracker.pending[0]["mutationId"],
            "action": "create_skill",
            "value": {
                "name": "Newsletter Review",
                "description": "Reviews newsletter drafts for voice and clarity.",
                "instructions": (
                    "Identify observable prose problems without claiming to prove "
                    "authorship."
                ),
                "requiredToolIds": ["meme_lord"],
            },
        }
    ]


def test_self_authored_skill_cannot_grant_a_new_tool() -> None:
    _, tools = _tools()

    with pytest.raises(ValueError, match="Unknown required_tool_ids"):
        tools["create_skill_for_self"](
            "Unsafe Skill", "Requests a new tool.", "Use shell access.", ["shell"]
        )


def test_chief_can_create_a_private_skill_for_an_existing_bot() -> None:
    context = _context()
    context["bots"][1]["toolIds"] = ["meme_lord"]
    tracker = BotMutationTracker()
    tools = {
        item.tool_name: item for item in bot_management_tools(context, tracker)
    }

    result = tools["create_skill_for_bot"](
        "Research",
        "Competitor Brief",
        "Creates a repeatable competitor brief.",
        "Compare supplied competitors and mark unknowns.",
        required_tool_ids=["meme_lord"],
    )

    assert "attached to Research" in result
    assert tracker.pending[0]["action"] == "create_skill"
    assert tracker.pending[0]["value"]["targetBotId"] == "research"
    assert tracker.pending[0]["value"]["requiredToolIds"] == ["meme_lord"]
    with pytest.raises(ValueError, match="Unknown required_tool_ids"):
        tools["create_skill_for_bot"](
            "Research", "Unsafe", "Needs shell.", "Run shell.", ["shell"]
        )


def test_any_bot_can_update_its_own_prompt_without_changing_tools() -> None:
    tracker, tools = _tools()

    result = tools["update_self"](
        tagline="Keeps the team moving.", prompt="Coordinate clearly and concisely."
    )

    assert "own settings" in result
    assert tracker.pending[0]["action"] == "update_self"
    assert tracker.pending[0]["value"] == {
        "changes": {
            "tagline": "Keeps the team moving.",
            "prompt": "Coordinate clearly and concisely.",
        }
    }
    assert "toolIds" not in tracker.pending[0]["value"]["changes"]


def test_any_bot_can_stage_an_explicit_personal_memory() -> None:
    tracker, tools = _tools()

    result = tools["remember_for_user"]("preference", "Keep status updates concise.")

    assert "ready to be saved" in result
    assert tracker.pending[0]["action"] == "create_memory"
    assert tracker.pending[0]["value"] == {
        "kind": "preference",
        "content": "Keep status updates concise.",
    }


def test_self_update_cannot_attach_a_skill_that_grants_a_new_tool() -> None:
    context = {
        **_context(),
        "skills": [
            {
                "id": "web-research",
                "name": "Web Research",
                "requiredToolIds": ["web"],
            }
        ],
    }
    tools = {
        item.tool_name: item
        for item in bot_management_tools(context, BotMutationTracker())
    }

    with pytest.raises(ValueError, match="Unknown skill_ids"):
        tools["update_self"](skill_ids=["web-research"])


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


def test_bot_management_payload_is_limited_to_direct_chat() -> None:
    payload = {
        "bot": {"id": "chief", "systemRole": "chief"},
        "botManagement": _context(),
    }
    assert bot_management_from_payload(payload) == _context()

    with pytest.raises(ValueError, match="direct chat"):
        bot_management_from_payload({**payload, "group": {}})


def test_legacy_payload_ignores_unlisted_self_tools_instead_of_crashing() -> None:
    context = {
        **_context(),
        "tools": [],
        "selfToolIds": ["calculator", "current_time", "web"],
    }

    parsed = bot_management_from_payload(
        {"bot": {"id": "chief", "systemRole": "chief"}, "botManagement": context}
    )

    assert parsed is not None
    assert parsed["selfToolIds"] == []


def test_unlisted_self_tools_do_not_expand_chief_management_options() -> None:
    context = {
        **_context(),
        "selfTools": [
            {"id": "calculator", "name": "Calculator"},
            {"id": "current_time", "name": "World clock"},
            {"id": "web", "name": "Web reader"},
        ],
        "selfToolIds": ["calculator", "current_time", "web"],
    }
    parsed = bot_management_from_payload(
        {"bot": {"id": "chief", "systemRole": "chief"}, "botManagement": context}
    )
    assert parsed is not None
    tools = {
        item.tool_name: item
        for item in bot_management_tools(parsed, BotMutationTracker())
    }

    management = json.loads(tools["list_bot_options"]())
    authoring = json.loads(tools["list_skill_authoring_options"]())

    assert [item["id"] for item in management["tools"]] == ["meme_lord"]
    assert [item["id"] for item in authoring["allowedTools"]] == [
        "calculator",
        "current_time",
        "web",
    ]
    with pytest.raises(ValueError, match="Unknown tool_ids"):
        tools["create_bot"]("Calculator bot", "", "Calculate.", tool_ids=["calculator"])


def test_non_chief_receives_only_safe_self_management_tools() -> None:
    context = {
        **_context(),
        "currentBot": {
            "id": "research",
            "name": "Research",
            "toolIds": [],
            "skillIds": [],
        },
        "canManageBots": False,
        "bots": [],
        "templates": [],
        "selfToolIds": [],
    }
    parsed = bot_management_from_payload(
        {
            "bot": {"id": "research"},
            "botManagement": context,
        }
    )
    assert parsed is not None
    tools = {
        item.tool_name for item in bot_management_tools(parsed, BotMutationTracker())
    }
    assert tools == {
        "create_skill_for_self",
        "list_skill_authoring_options",
        "remember_for_user",
        "update_self",
    }


def test_catalog_bindings_expose_chief_and_meme_tools(monkeypatch) -> None:
    actor_id = "a" * 64
    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "files")
    monkeypatch.setattr(artifacts.boto3, "client", lambda *_args, **_kwargs: object())
    payload = {
        "bot": {
            "id": "chief",
            "name": "Chief",
            "prompt": "Coordinate.",
            "systemRole": "chief",
            "toolIds": ["bot_manager", "meme_lord"],
            "tools": [
                {
                    "id": "bot_manager",
                    "runtime": {"kind": "local", "name": "bot_manager"},
                },
                {
                    "id": "meme_lord",
                    "runtime": {"kind": "local", "name": "meme_lord"},
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
        "create_skill_for_bot",
        "create_skill_for_self",
        "install_bot_template",
        "list_bot_options",
        "list_skill_authoring_options",
        "remember_for_user",
        "save_artifact",
        "search_meme_templates",
        "update_bot",
        "update_self",
    }
    descriptions = {
        item.tool_name: item.tool_spec["description"] for item in config.tools
    }
    assert "untrusted configuration data" in descriptions["list_bot_options"]
    assert "explicitly asked to create" in descriptions["create_bot"]
    assert "explicitly requested update" in descriptions["update_bot"]
    assert "Bot management" not in config.instructions
    assert "list_bot_options" not in config.instructions
