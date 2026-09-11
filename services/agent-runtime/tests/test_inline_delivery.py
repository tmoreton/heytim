from __future__ import annotations

import json
from pathlib import Path

import pytest

from frogbot_runtime import artifacts, image_generation
from frogbot_runtime.configuration import (
    INLINE_DELIVERY_INSTRUCTIONS,
    bot_configuration,
)


def test_direct_answers_are_inline_by_default() -> None:
    config = bot_configuration(
        {"bot": {"name": "Researcher", "tools": [], "skills": []}}
    )

    assert config.instructions.endswith(INLINE_DELIVERY_INSTRUCTIONS)
    assert (
        "Deliver the useful content inline in the chat by default"
        in config.instructions
    )
    assert "not just a changelog" in config.instructions
    assert "Do not create unsolicited files" in config.instructions
    assert (
        "A request for a report, Markdown, table, or reusable plan alone is not an export request"
        in config.instructions
    )
    assert "downloadable file automatically" not in config.instructions


def test_delivery_policy_overrides_legacy_template_export_defaults() -> None:
    legacy_prompt = "Always create a Markdown artifact for a reusable report."
    config = bot_configuration(
        {"bot": {"prompt": legacy_prompt, "tools": [], "skills": []}}
    )

    assert legacy_prompt in config.instructions
    assert config.instructions.index(legacy_prompt) < config.instructions.index(
        "Response delivery policy"
    )
    assert "takes precedence over automatic-export suggestions" in config.instructions


@pytest.mark.parametrize("role", ["lead", "contributor", "synthesizer", "solo"])
def test_delivery_policy_applies_to_every_group_role(role: str) -> None:
    config = bot_configuration(
        {
            "bot": {"name": "Chief", "tools": [], "skills": []},
            "group": {
                "name": "Creator group",
                "people": [{"name": "Owner", "role": "owner"}],
                "bots": [{"name": "Chief", "isCurrent": True}],
                "decisions": [],
                "round": {
                    "position": 1,
                    "size": 1,
                    "role": role,
                    "coordinatorName": "Chief",
                },
            },
        }
    )

    assert config.instructions.endswith(INLINE_DELIVERY_INSTRUCTIONS)
    assert (
        "Intermediate group contributions must still respect their assigned role"
        in config.instructions
    )
    if role == "lead":
        assert "or create an artifact yet" in config.instructions
    if role == "contributor":
        assert "create an artifact during this intermediate step" in config.instructions
    if role == "synthesizer":
        assert "inline in this final chat message" in config.instructions


def test_inline_default_preserves_explicit_export_and_meme_tools(monkeypatch) -> None:
    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "test-inline-exports")
    monkeypatch.setattr(artifacts.boto3, "client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        image_generation.boto3, "client", lambda *_args, **_kwargs: object()
    )
    actor_id = "a" * 64
    config = bot_configuration(
        {
            "bot": {
                "tools": [
                    {
                        "id": "meme_lord",
                        "runtime": {"kind": "local", "name": "meme_lord"},
                    },
                    {
                        "id": "image_generator",
                        "runtime": {
                            "kind": "local",
                            "name": "image_generator",
                        },
                    },
                ],
                "skills": [],
            },
            "artifacts": {
                "prefix": f"users/{actor_id}/artifacts/12345678-1234-1234-1234-123456789012"
            },
        },
        actor_id=actor_id,
    )

    assert {tool.tool_name for tool in config.tools} == {
        "compose_meme",
        "generate_image",
        "save_artifact",
        "search_meme_templates",
    }
    assert "only when the user explicitly asks for a file" in config.instructions
    assert (
        "Requested exports and original images remain supported" in config.instructions
    )
    assert "private template catalog" in config.instructions
    assert "does not generate or broadly edit imagery" in config.instructions
    assert "one original image from a text prompt" in config.instructions


def test_creator_schedule_examples_request_complete_inline_briefs() -> None:
    root = Path(__file__).resolve().parents[3]
    pack = json.loads((root / "examples/creator-workspaces.json").read_text())

    assert {group["name"] for group in pack["groups"]} == {
        "Heytim.dev",
        "strandsagents.com",
    }
    for group in pack["groups"]:
        schedule = group["schedule"]
        assert "Display the full brief inline in this group" in schedule["prompt"]
        assert "Files are only for an explicit export request" in schedule["prompt"]
        assert "draft responses" in schedule["prompt"]
        assert schedule["time"] == "07:00"
        assert schedule["timezone"] == "America/New_York"
