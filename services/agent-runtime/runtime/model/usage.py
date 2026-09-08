from __future__ import annotations

import threading
from collections.abc import AsyncGenerator, AsyncIterable
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar, cast

from pydantic import BaseModel
from strands.models import Model
from strands.models.openai import OpenAIModel
from strands.types.content import Messages, SystemContentBlock
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

T = TypeVar("T", bound=BaseModel)
TOKEN_FIELDS = (
    "inputTokens",
    "outputTokens",
    "totalTokens",
    "cacheReadInputTokens",
    "cacheWriteInputTokens",
    "reasoningTokens",
)


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _nonnegative_decimal(value: Any) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except InvalidOperation, TypeError, ValueError:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount


class UsageAccumulator:
    """Collect token and provider-cost metadata for one runtime invocation."""

    def __init__(self) -> None:
        self._models: dict[tuple[str, str], dict[str, Any]] = {}

    def observe(self, provider: str, model_id: str, event: StreamEvent) -> None:
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            return
        usage = metadata.get("usage")
        if not isinstance(usage, dict):
            return

        key = (provider, model_id)
        model = self._models.setdefault(
            key,
            {
                "provider": provider,
                "modelId": model_id,
                "callCount": 0,
                **{field: 0 for field in TOKEN_FIELDS},
                "providerCostUsd": Decimal(0),
                "hasProviderCost": False,
            },
        )
        model["callCount"] += 1
        for field in TOKEN_FIELDS:
            model[field] += _nonnegative_int(usage.get(field))

        provider_cost = _nonnegative_decimal(metadata.get("frogbotProviderCostUsd"))
        if provider_cost is not None:
            model["providerCostUsd"] += provider_cost
            model["hasProviderCost"] = True

    def snapshot(self) -> dict[str, Any]:
        models: list[dict[str, Any]] = []
        totals = {field: 0 for field in TOKEN_FIELDS}
        totals["callCount"] = 0
        for tracked in self._models.values():
            model = {
                "provider": tracked["provider"],
                "modelId": tracked["modelId"],
                "callCount": tracked["callCount"],
            }
            for field in TOKEN_FIELDS:
                value = tracked[field]
                totals[field] += value
                if value:
                    model[field] = value
            totals["callCount"] += tracked["callCount"]
            if tracked["hasProviderCost"]:
                model["providerCostUsd"] = format(tracked["providerCostUsd"], "f")
            models.append(model)
        return {"models": models, "totals": totals}


class OpenRouterUsageModel(OpenAIModel):
    """Preserve OpenRouter accounting fields that Strands does not expose."""

    def format_chunk(self, event: dict[str, Any], **kwargs: Any) -> StreamEvent:
        chunk = super().format_chunk(event, **kwargs)
        if event.get("chunk_type") != "metadata":
            return chunk

        metadata = chunk.get("metadata")
        if not isinstance(metadata, dict):
            return chunk
        raw_usage = event.get("data")

        provider_cost = _nonnegative_decimal(getattr(raw_usage, "cost", None))
        if provider_cost is not None:
            metadata["frogbotProviderCostUsd"] = format(provider_cost, "f")

        usage = metadata.get("usage")
        if isinstance(usage, dict):
            prompt_details = getattr(raw_usage, "prompt_tokens_details", None)
            completion_details = getattr(raw_usage, "completion_tokens_details", None)
            reasoning_tokens = _nonnegative_int(
                getattr(completion_details, "reasoning_tokens", None)
            )
            if reasoning_tokens:
                usage["reasoningTokens"] = reasoning_tokens
            cache_write_tokens = _nonnegative_int(
                getattr(prompt_details, "cache_write_tokens", None)
            )
            if cache_write_tokens:
                usage["cacheWriteInputTokens"] = cache_write_tokens
        return cast(StreamEvent, chunk)


class UsageTrackingModel(Model):
    """Delegate all model behavior while recording every usage metadata event."""

    def __init__(
        self,
        delegate: Model,
        accumulator: UsageAccumulator,
        *,
        provider: str,
        model_id: str,
    ) -> None:
        self.delegate = delegate
        self.accumulator = accumulator
        self.provider = provider
        self.model_id = model_id

    @property
    def stateful(self) -> bool:
        return self.delegate.stateful

    def update_config(self, **model_config: Any) -> None:
        self.delegate.update_config(**model_config)

    def get_config(self) -> Any:
        return self.delegate.get_config()

    async def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, T | Any]]:
        async for event in self.delegate.structured_output(
            output_model,
            prompt,
            system_prompt,
            **kwargs,
        ):
            yield event

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        system_prompt_content: list[SystemContentBlock] | None = None,
        invocation_state: dict[str, Any] | None = None,
        cancel_signal: threading.Event | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[StreamEvent]:
        async for event in self.delegate.stream(
            messages,
            tool_specs,
            system_prompt,
            tool_choice=tool_choice,
            system_prompt_content=system_prompt_content,
            invocation_state=invocation_state,
            cancel_signal=cancel_signal,
            **kwargs,
        ):
            self.accumulator.observe(self.provider, self.model_id, event)
            yield event
