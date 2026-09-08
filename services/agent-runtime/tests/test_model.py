from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from strands.models import (
    Model,
    ModelRouter,
    RoutingAttempt,
    RoutingCandidate,
    RoutingContext,
)

from model import load as model_loader
from model.routing import ADVANCED_REQUEST_MIN_CHARS, TaskRoutingStrategy


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

    assert isinstance(model, ModelRouter)
    primary = model.candidates[0].model
    advanced = model.candidates[1].model
    assert isinstance(primary, model_loader.PrimaryFallbackModel)
    assert isinstance(advanced, model_loader.PrimaryFallbackModel)
    assert primary.primary.get_config()["model_id"] == "z-ai/glm-5.3-flash"
    assert primary.primary.get_config()["params"]["extra_body"] == {
        "reasoning": {"effort": "low"}
    }
    assert advanced.primary.get_config()["model_id"] == "z-ai/glm-5.3"
    assert advanced.primary.get_config()["params"]["extra_body"] == {
        "reasoning": {"effort": "high"}
    }
    assert primary.fallback is advanced.fallback
    assert primary.fallback.get_config()["model_id"].startswith(
        "global.anthropic.claude-sonnet"
    )
    assert "test-secret" not in repr(primary.get_config())


@pytest.mark.parametrize(
    ("prompt", "candidate_index"),
    [
        ("Summarize these meeting notes.", 0),
        ("Debug this Python API and add unit tests.", 1),
        ("x" * ADVANCED_REQUEST_MIN_CHARS, 1),
    ],
)
def test_task_router_selects_by_request_complexity(
    prompt: str, candidate_index: int
) -> None:
    candidates = (
        RoutingCandidate(FakeModel("routine", []), name="routine"),
        RoutingCandidate(FakeModel("advanced", []), name="advanced"),
    )
    context = RoutingContext(
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        system_prompt=None,
        tool_specs=[],
        candidates=candidates,
        invocation_state={},
    )

    selected = asyncio.run(TaskRoutingStrategy().select(context))

    assert selected is candidates[candidate_index]


def test_task_router_declines_after_a_model_failure() -> None:
    candidates = (
        RoutingCandidate(FakeModel("routine", []), name="routine"),
        RoutingCandidate(FakeModel("advanced", []), name="advanced"),
    )
    context = RoutingContext(
        messages=[{"role": "user", "content": [{"text": "Debug this code."}]}],
        system_prompt=None,
        tool_specs=[],
        candidates=candidates,
        invocation_state={},
        attempts=(RoutingAttempt(candidates[1], RuntimeError("failed")),),
    )

    assert asyncio.run(TaskRoutingStrategy().select(context)) is None


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
    assert config["params"]["extra_body"] == {"reasoning": {"effort": effort}}


def test_openrouter_model_rejects_unsupported_reasoning_effort() -> None:
    with pytest.raises(ValueError, match="reasoning effort"):
        model_loader._load_openrouter_model("test-secret", reasoning_effort="medium")


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


def test_usage_tracker_aggregates_each_model_call() -> None:
    accumulator = model_loader.UsageAccumulator()
    delegate = FakeModel(
        "primary",
        [
            {
                "metadata": {
                    "usage": {
                        "inputTokens": 100,
                        "outputTokens": 25,
                        "totalTokens": 125,
                        "reasoningTokens": 10,
                    },
                    "frogbotProviderCostUsd": "0.000123",
                }
            }
        ],
    )
    model = model_loader.UsageTrackingModel(
        delegate,
        accumulator,
        provider="openrouter",
        model_id="z-ai/glm-5.3-flash",
    )

    asyncio.run(_events(model))
    asyncio.run(_events(model))

    report = accumulator.snapshot()
    assert report["models"] == [
        {
            "provider": "openrouter",
            "modelId": "z-ai/glm-5.3-flash",
            "callCount": 2,
            "inputTokens": 200,
            "outputTokens": 50,
            "totalTokens": 250,
            "reasoningTokens": 20,
            "providerCostUsd": "0.000246",
        }
    ]
    assert report["totals"]["callCount"] == 2
    assert report["totals"]["totalTokens"] == 250


def test_openrouter_model_preserves_provider_cost_and_reasoning_tokens() -> None:
    model = model_loader.OpenRouterUsageModel(
        model_id="z-ai/glm-5.3-flash",
        client_args={"api_key": "test"},
    )
    event = model.format_chunk(
        {
            "chunk_type": "metadata",
            "data": SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=25,
                total_tokens=125,
                prompt_tokens_details=SimpleNamespace(
                    cached_tokens=40, cache_write_tokens=15
                ),
                completion_tokens_details=SimpleNamespace(reasoning_tokens=10),
                cost="0.000123",
            ),
        }
    )

    assert event["metadata"]["frogbotProviderCostUsd"] == "0.000123"
    assert event["metadata"]["usage"]["cacheReadInputTokens"] == 40
    assert event["metadata"]["usage"]["cacheWriteInputTokens"] == 15
    assert event["metadata"]["usage"]["reasoningTokens"] == 10
