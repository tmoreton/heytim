from __future__ import annotations

import asyncio
from typing import Any

import pytest

from model import load as model_loader


@pytest.mark.parametrize("effort", ["low", "high", "max"])
def test_openrouter_model_accepts_supported_reasoning_efforts(effort: str) -> None:
    model = model_loader._load_openrouter_model(
        "test-secret",
        model_id="z-ai/glm-5.3",
        reasoning_effort=effort,
        max_tokens=2048,
        temperature=0.1,
    )

    config = model.get_config()
    assert config["model_id"] == "z-ai/glm-5.3"
    assert config["params"]["max_tokens"] == 2048
    assert config["params"]["temperature"] == 0.1
    assert config["params"]["extra_body"] == {
        "reasoning": {"effort": effort},
        "provider": {"zdr": True, "data_collection": "deny"},
    }
    assert model.client_args["max_retries"] == 0


def test_bot_can_choose_glm_with_deepseek_fallback_and_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def key() -> str:
        return "test-secret"

    monkeypatch.setattr(model_loader, "_openrouter_api_key", key)
    model = asyncio.run(
        model_loader.load_model(model_preference="glm", reasoning_effort="low")
    )

    assert model.primary.model.get_config()["model_id"] == "z-ai/glm-5.3"
    assert (
        model.fallback.model.get_config()["model_id"] == "deepseek/deepseek-v4.1-flash"
    )
    assert model.primary.model.get_config()["params"]["extra_body"] == {
        "reasoning": {"effort": "low"},
        "provider": {"zdr": True, "data_collection": "deny"},
    }


@pytest.mark.parametrize("preference", ["other", "", ["glm"]])
def test_bot_cannot_choose_an_unapproved_model(preference: Any) -> None:
    with pytest.raises(ValueError, match="modelPreference"):
        asyncio.run(model_loader.load_model(model_preference=preference))
