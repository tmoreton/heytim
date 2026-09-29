from __future__ import annotations

import asyncio
from typing import Any

import pytest

from model import load as model_loader


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
    assert model.fallback.model.get_config()["model_id"] == "deepseek/deepseek-v4.1-flash"
    assert model.primary.model.get_config()["params"]["extra_body"] == {
        "reasoning": {"effort": "low"}
    }


@pytest.mark.parametrize("preference", ["other", "", ["glm"]])
def test_bot_cannot_choose_an_unapproved_model(preference: Any) -> None:
    with pytest.raises(ValueError, match="modelPreference"):
        asyncio.run(model_loader.load_model(model_preference=preference))
