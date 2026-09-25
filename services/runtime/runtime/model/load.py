from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any, TypeVar

from bedrock_agentcore.identity.auth import requires_api_key
from pydantic import BaseModel
from strands.models import Model
from strands.models.openai import OpenAIModel
from strands.types.content import Messages, SystemContentBlock
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

from model.usage import OpenRouterUsageModel, UsageAccumulator, UsageTrackingModel

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

PRIMARY_MODEL_ID = os.environ.get(
    "HEYTIM_PRIMARY_MODEL_ID", "deepseek/deepseek-v4.1-flash"
)
PRIMARY_REASONING_EFFORT = os.environ.get("HEYTIM_REASONING_EFFORT", "high")
FALLBACK_MODEL_ID = os.environ.get("HEYTIM_FALLBACK_MODEL_ID", "z-ai/glm-5.3")
FALLBACK_REASONING_EFFORT = os.environ.get(
    "HEYTIM_FALLBACK_REASONING_EFFORT", "high"
)
OPENROUTER_BASE_URL = os.environ.get(
    "HEYTIM_OPENROUTER_BASE_URL",
    "https://openrouter.ai/api/v1",
)
OPENROUTER_CREDENTIAL_PROVIDER = os.environ.get(
    "HEYTIM_OPENROUTER_CREDENTIAL_PROVIDER",
    "HeyTim_OpenRouter",
)
SUPPORTED_REASONING_EFFORTS = {"low", "high", "max"}
PRIMARY_RESPONSE_TIMEOUT_SECONDS = int(
    os.environ.get("HEYTIM_PRIMARY_RESPONSE_TIMEOUT_SECONDS", "120")
)
if not 15 <= PRIMARY_RESPONSE_TIMEOUT_SECONDS <= 600:
    raise ValueError(
        "HEYTIM_PRIMARY_RESPONSE_TIMEOUT_SECONDS must be between 15 and 600"
    )
OPENROUTER_MAX_ATTEMPTS = int(
    os.environ.get("HEYTIM_OPENROUTER_MAX_ATTEMPTS", "2")
)
if not 1 <= OPENROUTER_MAX_ATTEMPTS <= 4:
    raise ValueError("HEYTIM_OPENROUTER_MAX_ATTEMPTS must be between 1 and 4")
MAX_RETRY_AFTER_SECONDS = 150.0


class IncompleteOpenRouterResponseError(RuntimeError):
    """Raised when OpenRouter ends a response before returning useful output."""


class OpenRouterCredentialError(RuntimeError):
    """Raised when the OpenRouter credential cannot be loaded."""


class PreResponseFallbackModel(Model):
    """Use a fallback only when the current provider has not completed a response."""

    def __init__(
        self, primary: Model, fallback: Model, *, fallback_name: str
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.fallback_name = fallback_name

    @property
    def stateful(self) -> bool:
        return self.primary.stateful or self.fallback.stateful

    def update_config(self, **model_config: Any) -> None:
        self.primary.update_config(**model_config)
        self.fallback.update_config(**model_config)

    def get_config(self) -> Any:
        return self.primary.get_config()

    async def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, T | Any]]:
        emitted = False
        try:
            async for event in self.primary.structured_output(
                output_model,
                prompt,
                system_prompt,
                **kwargs,
            ):
                emitted = True
                yield event
        except Exception as error:
            if emitted:
                raise
            _log_fallback(error, self.fallback_name)
            async for event in self.fallback.structured_output(
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
        call = {
            "tool_choice": tool_choice,
            "system_prompt_content": system_prompt_content,
            "invocation_state": invocation_state,
            "cancel_signal": cancel_signal,
            **kwargs,
        }
        emitted = False
        try:
            async for event in self.primary.stream(
                messages, tool_specs, system_prompt, **call
            ):
                emitted = True
                yield event
        except Exception as error:
            if emitted:
                raise
            _log_fallback(error, self.fallback_name)
            async for event in self.fallback.stream(
                messages, tool_specs, system_prompt, **call
            ):
                yield event


class ResilientOpenRouterModel(Model):
    """Retry an OpenRouter response only before any model output is committed."""

    def __init__(self, model: Model) -> None:
        self.model = model

    @property
    def stateful(self) -> bool:
        return self.model.stateful

    def update_config(self, **model_config: Any) -> None:
        self.model.update_config(**model_config)

    def get_config(self) -> Any:
        return self.model.get_config()

    async def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, T | Any]]:
        for attempt in range(1, OPENROUTER_MAX_ATTEMPTS + 1):
            emitted = False
            try:
                async with asyncio.timeout(PRIMARY_RESPONSE_TIMEOUT_SECONDS):
                    async for event in self.model.structured_output(
                        output_model,
                        prompt,
                        system_prompt,
                        **kwargs,
                    ):
                        emitted = True
                        yield event
                return
            except Exception as error:
                delay = _retry_delay_seconds(error, attempt)
                if emitted or delay is None:
                    raise
                _log_retry(error, attempt, delay)
                await asyncio.sleep(delay)

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
        call = {
            "tool_choice": tool_choice,
            "system_prompt_content": system_prompt_content,
            "invocation_state": invocation_state,
            "cancel_signal": cancel_signal,
            **kwargs,
        }
        for attempt in range(1, OPENROUTER_MAX_ATTEMPTS + 1):
            buffered: list[StreamEvent] = []
            committed = False
            try:
                async with asyncio.timeout(PRIMARY_RESPONSE_TIMEOUT_SECONDS):
                    async for event in self.model.stream(
                        messages, tool_specs, system_prompt, **call
                    ):
                        if committed:
                            yield event
                            continue
                        buffered.append(event)
                        if _completes_response(event):
                            if not _usable_response(buffered):
                                raise IncompleteOpenRouterResponseError(
                                    "OpenRouter returned an empty response"
                                )
                            committed = True
                            log.info(
                                "OpenRouter model %s completed a response",
                                self.model.get_config().get("model_id", "unknown"),
                            )
                            for buffered_event in buffered:
                                yield buffered_event
                            buffered.clear()
                if not committed:
                    raise IncompleteOpenRouterResponseError(
                        "OpenRouter stream ended before messageStop"
                    )
                return
            except Exception as error:
                if committed:
                    raise
                delay = _retry_delay_seconds(error, attempt)
                if delay is None:
                    raise
                _log_retry(error, attempt, delay)
                await asyncio.sleep(delay)


def _completes_response(event: StreamEvent) -> bool:
    return "messageStop" in event


def _usable_response(events: list[StreamEvent]) -> bool:
    stop_reason = None
    has_text = False
    has_tool = False
    for event in events:
        reason = event.get("messageStop", {}).get("stopReason")
        if isinstance(reason, str):
            stop_reason = reason
        start = event.get("contentBlockStart", {}).get("start", {})
        has_tool = has_tool or isinstance(start.get("toolUse"), dict)
        text = event.get("contentBlockDelta", {}).get("delta", {}).get("text")
        has_text = has_text or (isinstance(text, str) and bool(text.strip()))
    if stop_reason == "end_turn":
        return has_text
    if stop_reason == "tool_use":
        return has_tool
    return stop_reason is not None


def _exception_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _retry_after_seconds(error: Exception) -> float | None:
    for item in _exception_chain(error):
        response = getattr(item, "response", None)
        headers = getattr(response, "headers", None)
        raw = headers.get("Retry-After") if headers is not None else None
        if raw is None:
            body = getattr(item, "body", None)
            metadata = body.get("metadata") if isinstance(body, dict) else None
            nested_headers = (
                metadata.get("headers") if isinstance(metadata, dict) else None
            )
            raw = (
                nested_headers.get("Retry-After")
                if isinstance(nested_headers, dict)
                else None
            )
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            continue
        return min(MAX_RETRY_AFTER_SECONDS, max(0.0, seconds))
    return None


def _retry_delay_seconds(error: Exception, attempt: int) -> float | None:
    if attempt >= OPENROUTER_MAX_ATTEMPTS:
        return None
    chain = _exception_chain(error)
    if any(isinstance(item, IncompleteOpenRouterResponseError) for item in chain):
        return 0.0
    status_codes = {getattr(item, "status_code", None) for item in chain}
    message = " ".join(str(item) for item in chain)
    if 402 in status_codes and "in_flight_budget_exhausted" in message:
        return _retry_after_seconds(error) or 120.0
    if status_codes.intersection({408, 409, 429, 500, 502, 503, 504}) or any(
        type(item).__name__ == "ModelThrottledException" for item in chain
    ):
        return _retry_after_seconds(error) or float(2 ** (attempt - 1))
    if any(
        isinstance(item, TimeoutError)
        or type(item).__name__
        in {"APIConnectionError", "APITimeoutError", "ConnectError", "ReadTimeout"}
        for item in chain
    ):
        return float(2 ** (attempt - 1))
    retryable_provider_error = any(
        type(item).__name__ == "APIError" for item in chain
    ) and any(
        marker in message.lower()
        for marker in (
            "provider returned error",
            "upstream provider error",
            "temporarily unavailable",
        )
    )
    if retryable_provider_error:
        return _retry_after_seconds(error) or float(2 ** (attempt - 1))
    return None


def _log_retry(error: Exception, attempt: int, delay: float) -> None:
    log.warning(
        "OpenRouter response failed before completion (%s); retrying in %.1fs (%d/%d)",
        type(error).__name__,
        delay,
        attempt + 1,
        OPENROUTER_MAX_ATTEMPTS,
    )


def _log_fallback(error: Exception, fallback_name: str) -> None:
    log.warning(
        "Model route failed before returning a response; using %s fallback (%s)",
        fallback_name,
        type(error).__name__,
    )


@requires_api_key(provider_name=OPENROUTER_CREDENTIAL_PROVIDER)
async def _openrouter_api_key(*, api_key: str) -> str:
    return api_key


def _load_openrouter_model(
    api_key: str,
    *,
    model_id: str = PRIMARY_MODEL_ID,
    reasoning_effort: str = PRIMARY_REASONING_EFFORT,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> OpenAIModel:
    if reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
        supported = ", ".join(sorted(SUPPORTED_REASONING_EFFORTS))
        raise ValueError(f"reasoning effort must be one of: {supported}")
    if (
        not isinstance(max_tokens, int)
        or isinstance(max_tokens, bool)
        or max_tokens < 1
    ):
        raise ValueError("max_tokens must be a positive integer")
    return OpenRouterUsageModel(
        model_id=model_id,
        context_window_limit=200_000,
        params={
            "max_tokens": max_tokens,
            "temperature": temperature,
            # Model defaults vary, so production uses an explicit deploy-time
            # effort that both DeepSeek V4.1 Flash and GLM 5.3 support.
            # OpenRouter-specific parameters must travel through the OpenAI
            # SDK's extra_body escape hatch rather than as top-level kwargs.
            "extra_body": {"reasoning": {"effort": reasoning_effort}},
        },
        client_args={
            "api_key": api_key,
            "base_url": OPENROUTER_BASE_URL,
            # HeyTim owns retries so every paid HTTP attempt is reserved by
            # UsageTrackingModel before dispatch.
            "max_retries": 0,
            "default_headers": {
                "HTTP-Referer": "https://heytim.ai",
                "X-OpenRouter-Title": "HeyTim",
            },
        },
    )


def _tracked(
    model: Model,
    usage: UsageAccumulator | None,
    *,
    provider: str,
    model_id: str,
) -> Model:
    if usage is None:
        return model
    return UsageTrackingModel(
        model,
        usage,
        provider=provider,
        model_id=model_id,
    )


async def load_model(usage: UsageAccumulator | None = None) -> Model:
    """Load DeepSeek with GLM as its OpenRouter-only fallback."""
    try:
        api_key = await _openrouter_api_key()
    except Exception as error:
        raise OpenRouterCredentialError(
            "OpenRouter credential lookup failed"
        ) from error
    log.info(
        "Configured OpenRouter primary %s/%s with fallback %s/%s",
        PRIMARY_MODEL_ID,
        PRIMARY_REASONING_EFFORT,
        FALLBACK_MODEL_ID,
        FALLBACK_REASONING_EFFORT,
    )
    primary = ResilientOpenRouterModel(
        _tracked(
            _load_openrouter_model(api_key),
            usage,
            provider="openrouter",
            model_id=PRIMARY_MODEL_ID,
        )
    )
    fallback = ResilientOpenRouterModel(
        _tracked(
            _load_openrouter_model(
                api_key,
                model_id=FALLBACK_MODEL_ID,
                reasoning_effort=FALLBACK_REASONING_EFFORT,
            ),
            usage,
            provider="openrouter",
            model_id=FALLBACK_MODEL_ID,
        )
    )
    return PreResponseFallbackModel(
        primary,
        fallback,
        fallback_name="GLM on OpenRouter",
    )
