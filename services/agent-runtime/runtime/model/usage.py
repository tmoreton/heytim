from __future__ import annotations

import os
import threading
from collections.abc import AsyncGenerator, AsyncIterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar, cast
from zoneinfo import ZoneInfo

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
IMAGE_OPERATIONS = {"generate_image", "create_youtube_thumbnail"}
YOUTUBE_SEARCH_OPERATION = "youtube_search"
YOUTUBE_SEARCH_MAX_CALLS = 3
YOUTUBE_QUOTA_TIME_ZONE = ZoneInfo("America/Los_Angeles")


def _bounded_integer_environment(
    name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class ProviderCallLimits:
    model_calls: int
    provider_tool_calls: int
    image_calls: int
    youtube_search_calls: int = YOUTUBE_SEARCH_MAX_CALLS


PROVIDER_CALL_LIMITS = ProviderCallLimits(
    model_calls=_bounded_integer_environment(
        "FROGBOT_MAX_MODEL_CALLS_PER_RUNTIME_RUN", 24, 1, 100
    ),
    provider_tool_calls=_bounded_integer_environment(
        "FROGBOT_MAX_PROVIDER_TOOL_CALLS_PER_RUNTIME_RUN", 24, 1, 100
    ),
    image_calls=_bounded_integer_environment(
        "FROGBOT_MAX_IMAGE_CALLS_PER_RUNTIME_RUN", 2, 1, 10
    ),
    youtube_search_calls=YOUTUBE_SEARCH_MAX_CALLS,
)


class ProviderCallLimitExceeded(RuntimeError):
    """Raised before a paid provider dispatch would exceed a run-local cap."""


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

    def __init__(
        self,
        limits: ProviderCallLimits = PROVIDER_CALL_LIMITS,
        *,
        youtube_search_quota: dict[str, Any] | None = None,
    ) -> None:
        self._models: dict[tuple[str, str], dict[str, Any]] = {}
        self._tools: dict[tuple[str, str], int] = {}
        self._model_dispatches = 0
        self._image_dispatches = 0
        self._limits = limits
        self._youtube_search_quota = self._validate_youtube_search_quota(
            youtube_search_quota
        )
        self._lock = threading.Lock()

    @staticmethod
    def _validate_youtube_search_quota(
        quota: dict[str, Any] | None,
    ) -> tuple[str, int] | None:
        if quota is None:
            return None
        if not isinstance(quota, dict):
            raise TypeError("YouTube search quota lease is invalid")
        day = quota.get("day")
        max_calls = quota.get("maxCalls")
        try:
            parsed_day = date.fromisoformat(day) if isinstance(day, str) else None
        except ValueError as exc:
            raise ValueError("YouTube search quota lease date is invalid") from exc
        if parsed_day is None or parsed_day.isoformat() != day:
            raise ValueError("YouTube search quota lease date is invalid")
        if (
            isinstance(max_calls, bool)
            or not isinstance(max_calls, int)
            or not 1 <= max_calls <= YOUTUBE_SEARCH_MAX_CALLS
        ):
            raise ValueError("YouTube search quota lease call limit is invalid")
        return day, max_calls

    @staticmethod
    def _youtube_quota_day() -> str:
        return (
            datetime.now(UTC)
            .astimezone(YOUTUBE_QUOTA_TIME_ZONE)
            .date()
            .isoformat()
        )

    def reserve_model(self, provider: str, model_id: str) -> None:
        """Reserve one provider model dispatch before any network request."""
        with self._lock:
            if self._model_dispatches >= self._limits.model_calls:
                raise ProviderCallLimitExceeded(
                    "This run reached its model-call safety limit."
                )
            self._model_dispatches += 1

    def observe(self, provider: str, model_id: str, event: StreamEvent) -> None:
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            return
        usage = metadata.get("usage")
        if not isinstance(usage, dict):
            return

        with self._lock:
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

            provider_cost = _nonnegative_decimal(
                metadata.get("frogbotProviderCostUsd")
            )
            if provider_cost is not None:
                model["providerCostUsd"] += provider_cost
                model["hasProviderCost"] = True

    def observe_tool(self, provider: str, operation: str) -> None:
        """Reserve and count a provider tool dispatch without its arguments."""
        if not provider or not operation:
            return
        with self._lock:
            tool_dispatches = sum(self._tools.values())
            if tool_dispatches >= self._limits.provider_tool_calls:
                raise ProviderCallLimitExceeded(
                    "This run reached its provider-tool safety limit."
                )
            is_image = provider == "openrouter" and operation in IMAGE_OPERATIONS
            if is_image and self._image_dispatches >= self._limits.image_calls:
                raise ProviderCallLimitExceeded(
                    "This run reached its image-generation safety limit."
                )
            key = (provider[:32], operation[:128])
            is_youtube_search = (
                provider == "agentcore-gateway"
                and operation == YOUTUBE_SEARCH_OPERATION
            )
            if is_youtube_search:
                if self._youtube_search_quota is None:
                    raise ProviderCallLimitExceeded(
                        "YouTube search has no reserved shared quota."
                    )
                quota_day, lease_calls = self._youtube_search_quota
                if quota_day != self._youtube_quota_day():
                    raise ProviderCallLimitExceeded(
                        "The YouTube search quota reservation has expired."
                    )
                youtube_limit = min(
                    lease_calls, self._limits.youtube_search_calls
                )
                if self._tools.get(key, 0) >= youtube_limit:
                    raise ProviderCallLimitExceeded(
                        "This run reached its YouTube search safety limit."
                    )
            self._tools[key] = self._tools.get(key, 0) + 1
            if is_image:
                self._image_dispatches += 1

    def snapshot(self) -> dict[str, Any]:
        models: list[dict[str, Any]] = []
        totals = {field: 0 for field in TOKEN_FIELDS}
        totals["callCount"] = 0
        with self._lock:
            tracked_models = [dict(item) for item in self._models.values()]
            tracked_tools = list(self._tools.items())
            model_dispatches = self._model_dispatches
        for tracked in tracked_models:
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
        tools = [
            {"provider": provider, "operation": operation, "callCount": count}
            for (provider, operation), count in tracked_tools
        ]
        totals["toolCallCount"] = sum(item["callCount"] for item in tools)
        totals["modelDispatchCount"] = model_dispatches
        return {"models": models, "tools": tools, "totals": totals}


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
        self.accumulator.reserve_model(self.provider, self.model_id)
        async for event in self.delegate.structured_output(
            output_model,
            prompt,
            system_prompt,
            **kwargs,
        ):
            if isinstance(event, dict):
                self.accumulator.observe(
                    self.provider,
                    self.model_id,
                    cast(StreamEvent, event),
                )
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
        self.accumulator.reserve_model(self.provider, self.model_id)
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
