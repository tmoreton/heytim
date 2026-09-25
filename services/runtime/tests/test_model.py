from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from strands.models import Model

from model import load as model_loader
from model.usage import (
    MODEL_FINALIZATION_INSTRUCTION,
    ProviderCallLimitExceeded,
    ProviderCallLimits,
)


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
        self.last_args: tuple[Any, ...] | None = None

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
    ) -> AsyncGenerator[dict[str, Any]]:
        if self.error:
            raise self.error
        if False:
            yield {}

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[dict[str, Any]]:
        self.calls += 1
        self.last_args = args
        for event in self.events:
            yield event
        if self.error:
            raise self.error


class SequencedFakeModel(FakeModel):
    def __init__(self, responses: list[list[dict[str, Any]] | Exception]) -> None:
        super().__init__("openrouter", [])
        self.responses = responses

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[dict[str, Any]]:
        response = self.responses[self.calls]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        for event in response:
            yield event


async def _events(model: Model) -> list[dict[str, Any]]:
    return [event async for event in model.stream([])]


def test_load_model_uses_deepseek_with_glm_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def key() -> str:
        return "test-secret"

    monkeypatch.setattr(model_loader, "_openrouter_api_key", key)
    model = asyncio.run(model_loader.load_model())

    assert isinstance(model, model_loader.PreResponseFallbackModel)
    primary = model.primary
    fallback = model.fallback
    assert isinstance(primary, model_loader.ResilientOpenRouterModel)
    assert isinstance(fallback, model_loader.ResilientOpenRouterModel)
    assert primary.model.get_config()["model_id"] == "deepseek/deepseek-v4.1-flash"
    assert primary.model.get_config()["params"]["extra_body"] == {
        "reasoning": {"effort": "high"}
    }
    assert fallback.model.get_config()["model_id"] == "z-ai/glm-5.3"
    assert fallback.model.get_config()["params"]["extra_body"] == {
        "reasoning": {"effort": "high"}
    }
    assert "test-secret" not in repr(primary.get_config())


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
    assert model.client_args["max_retries"] == 0


def test_openrouter_model_rejects_unsupported_reasoning_effort() -> None:
    with pytest.raises(ValueError, match="reasoning effort"):
        model_loader._load_openrouter_model("test-secret", reasoning_effort="medium")


def test_load_model_fails_closed_when_openrouter_credential_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def key() -> str:
        raise RuntimeError("unavailable")

    monkeypatch.setattr(model_loader, "_openrouter_api_key", key)
    with pytest.raises(
        model_loader.OpenRouterCredentialError,
        match="OpenRouter credential lookup failed",
    ):
        asyncio.run(model_loader.load_model())


def test_retry_discards_incomplete_openrouter_stream() -> None:
    complete_events = [
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "hello"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    delegate = SequencedFakeModel([[{"messageStart": {}}], complete_events])

    events = asyncio.run(_events(model_loader.ResilientOpenRouterModel(delegate)))

    assert events == complete_events
    assert delegate.calls == 2


def test_retry_replaces_an_empty_openrouter_response() -> None:
    empty = [{"messageStart": {}}, {"messageStop": {"stopReason": "end_turn"}}]
    complete = [
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "complete"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    delegate = SequencedFakeModel([empty, complete])

    events = asyncio.run(_events(model_loader.ResilientOpenRouterModel(delegate)))

    assert events == complete
    assert delegate.calls == 2


def test_retry_does_not_repeat_a_completed_openrouter_response() -> None:
    primary_events = [
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "complete"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    delegate = FakeModel("openrouter", primary_events, RuntimeError("late failure"))

    with pytest.raises(RuntimeError, match="late failure"):
        asyncio.run(_events(model_loader.ResilientOpenRouterModel(delegate)))

    assert delegate.calls == 1


def test_in_flight_budget_waits_for_openrouter_retry_after(monkeypatch) -> None:
    class BudgetError(RuntimeError):
        status_code = 402
        response = SimpleNamespace(headers={"Retry-After": "120"})

        def __str__(self) -> str:
            return "in_flight_budget_exhausted"

    complete = [
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "complete"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    delegate = SequencedFakeModel([BudgetError(), complete])
    sleeps = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(model_loader.asyncio, "sleep", sleep)

    events = asyncio.run(_events(model_loader.ResilientOpenRouterModel(delegate)))

    assert events == complete
    assert sleeps == [120.0]


def test_retry_reads_throttling_details_from_wrapped_error(monkeypatch) -> None:
    class ProviderError(RuntimeError):
        status_code = 429
        response = SimpleNamespace(headers={"Retry-After": "3"})

    class ModelThrottledException(RuntimeError):
        pass

    provider_error = ProviderError("rate limited")
    wrapped_error = ModelThrottledException("model throttled")
    wrapped_error.__cause__ = provider_error
    complete = [
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "complete"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    delegate = SequencedFakeModel([wrapped_error, complete])
    sleeps = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(model_loader.asyncio, "sleep", sleep)

    events = asyncio.run(_events(model_loader.ResilientOpenRouterModel(delegate)))

    assert events == complete
    assert sleeps == [3.0]


def test_retry_handles_streamed_provider_error_without_status(monkeypatch) -> None:
    class APIError(RuntimeError):
        pass

    complete = [
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "complete"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    delegate = SequencedFakeModel([APIError("Provider returned error"), complete])
    sleeps = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(model_loader.asyncio, "sleep", sleep)

    events = asyncio.run(_events(model_loader.ResilientOpenRouterModel(delegate)))

    assert events == complete
    assert delegate.calls == 2
    assert sleeps == [1.0]


def test_deepseek_failure_uses_glm_before_any_response_is_returned() -> None:
    primary = FakeModel("deepseek/deepseek-v4.1-flash", [], RuntimeError("down"))
    fallback_events = [
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "from glm"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    fallback = FakeModel("z-ai/glm-5.3", fallback_events)

    events = asyncio.run(
        _events(
            model_loader.PreResponseFallbackModel(
                primary, fallback, fallback_name="GLM on OpenRouter"
            )
        )
    )

    assert events == fallback_events
    assert primary.calls == 1
    assert fallback.calls == 1


def test_glm_fallback_never_repeats_a_started_deepseek_response() -> None:
    primary_events = [
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "started"}}},
    ]
    primary = FakeModel(
        "deepseek/deepseek-v4.1-flash",
        primary_events,
        RuntimeError("late failure"),
    )
    fallback = FakeModel("z-ai/glm-5.3", [])

    with pytest.raises(RuntimeError, match="late failure"):
        asyncio.run(
            _events(
                model_loader.PreResponseFallbackModel(
                    primary, fallback, fallback_name="GLM on OpenRouter"
                )
            )
        )

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
                    "heytimProviderCostUsd": "0.000123",
                }
            }
        ],
    )
    model = model_loader.UsageTrackingModel(
        delegate,
        accumulator,
        provider="openrouter",
        model_id="deepseek/deepseek-v4.1-flash",
    )

    asyncio.run(_events(model))
    asyncio.run(_events(model))

    report = accumulator.snapshot()
    assert report["models"] == [
        {
            "provider": "openrouter",
            "modelId": "deepseek/deepseek-v4.1-flash",
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


def test_usage_tracker_observes_structured_output_metadata() -> None:
    accumulator = model_loader.UsageAccumulator()
    delegate = FakeModel("primary", [])

    async def structured_output(*_args, **_kwargs):
        yield {
            "metadata": {
                "usage": {
                    "inputTokens": 40,
                    "outputTokens": 10,
                    "totalTokens": 50,
                },
                "heytimProviderCostUsd": "0.00005",
            }
        }

    delegate.structured_output = structured_output  # type: ignore[method-assign]
    model = model_loader.UsageTrackingModel(
        delegate,
        accumulator,
        provider="openrouter",
        model_id="deepseek/deepseek-v4.1-flash",
    )

    async def collect():
        return [
            event
            async for event in model.structured_output(
                BaseModel, [{"role": "user", "content": [{"text": "test"}]}]
            )
        ]

    events = asyncio.run(collect())

    assert len(events) == 1
    assert accumulator.snapshot()["models"][0]["totalTokens"] == 50


def test_model_dispatch_limit_is_enforced_before_provider_call() -> None:
    accumulator = model_loader.UsageAccumulator(
        ProviderCallLimits(
            model_calls=1,
            provider_tool_calls=10,
            image_calls=2,
        )
    )
    delegate = FakeModel("primary", [])
    model = model_loader.UsageTrackingModel(
        delegate,
        accumulator,
        provider="openrouter",
        model_id="deepseek/deepseek-v4.1-flash",
    )

    asyncio.run(_events(model))
    with pytest.raises(
        ProviderCallLimitExceeded,
        match="model-call safety limit",
    ):
        asyncio.run(_events(model))

    assert delegate.calls == 1
    assert accumulator.snapshot()["totals"]["modelDispatchCount"] == 1


def test_usage_tracker_reserves_final_calls_for_a_tool_free_answer() -> None:
    accumulator = model_loader.UsageAccumulator(
        ProviderCallLimits(
            model_calls=6,
            provider_tool_calls=10,
            image_calls=2,
        )
    )
    delegate = FakeModel("primary", [])
    model = model_loader.UsageTrackingModel(
        delegate,
        accumulator,
        provider="openrouter",
        model_id="deepseek/deepseek-v4.1-flash",
    )

    async def call_with_tools():
        return [
            event
            async for event in model.stream(
                [],
                [
                    {
                        "name": "gmail_search",
                        "description": "search",
                        "inputSchema": {"json": {}},
                    }
                ],
                "base instructions",
            )
        ]

    for _ in range(4):
        asyncio.run(call_with_tools())

    assert delegate.last_args is not None
    assert delegate.last_args[1] == []
    assert MODEL_FINALIZATION_INSTRUCTION in delegate.last_args[2]


def test_openrouter_model_preserves_provider_cost_and_reasoning_tokens() -> None:
    model = model_loader.OpenRouterUsageModel(
        model_id="deepseek/deepseek-v4.1-flash",
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

    assert event["metadata"]["heytimProviderCostUsd"] == "0.000123"
    assert event["metadata"]["usage"]["cacheReadInputTokens"] == 40
    assert event["metadata"]["usage"]["cacheWriteInputTokens"] == 15
    assert event["metadata"]["usage"]["reasoningTokens"] == 10
