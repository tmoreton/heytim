from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from pydantic import BaseModel
from strands.models import Model

from model import load as model_loader


class FakeModel(Model):
    def __init__(
        self,
        model_id: str,
        events: list[dict[str, Any]],
        error: Exception | None = None,
    ) -> None:
        self.config = {"model_id": model_id}
        self.events = events
        self.error = error
        self.calls = 0

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return self.config

    async def structured_output(
        self,
        output_model: type[BaseModel],
        prompt: Any,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if self.error:
            raise self.error
        if False:
            yield {}

    async def stream(
        self, *args: Any, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        self.calls += 1
        for event in self.events:
            yield event
        if self.error:
            raise self.error


async def _events(model: Model) -> list[dict[str, Any]]:
    return [event async for event in model.stream([])]


def test_load_model_uses_openrouter_primary_and_hides_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def key() -> str:
        return "test-secret"

    monkeypatch.setattr(model_loader, "_openrouter_api_key", key)
    model = asyncio.run(model_loader.load_model())

    assert isinstance(model, model_loader.PrimaryFallbackModel)
    assert model.primary.get_config()["model_id"] == "z-ai/glm-5.3-flash"
    assert model.fallback.get_config()["model_id"].startswith(
        "global.anthropic.claude-sonnet"
    )
    assert "test-secret" not in repr(model.get_config())


def test_load_model_uses_bedrock_when_credential_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def key() -> str:
        raise RuntimeError("unavailable")

    monkeypatch.setattr(model_loader, "_openrouter_api_key", key)
    model = asyncio.run(model_loader.load_model())

    assert model.get_config()["model_id"].startswith("global.anthropic.claude-sonnet")


def test_fallback_discards_incomplete_primary_stream() -> None:
    primary = FakeModel("primary", [{"messageStart": {}}], RuntimeError("unavailable"))
    fallback_events = [
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "hello"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    fallback = FakeModel("fallback", fallback_events)

    events = asyncio.run(_events(model_loader.PrimaryFallbackModel(primary, fallback)))

    assert events == fallback_events
    assert fallback.calls == 1


def test_fallback_does_not_duplicate_a_started_response() -> None:
    primary = FakeModel(
        "primary",
        [{"messageStart": {}}, {"contentBlockDelta": {"delta": {"text": "started"}}}],
        RuntimeError("interrupted"),
    )
    fallback = FakeModel(
        "fallback", [{"contentBlockDelta": {"delta": {"text": "duplicate"}}}]
    )

    with pytest.raises(RuntimeError, match="interrupted"):
        asyncio.run(_events(model_loader.PrimaryFallbackModel(primary, fallback)))

    assert fallback.calls == 0
