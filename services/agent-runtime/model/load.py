from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any, TypeVar

from bedrock_agentcore.identity.auth import requires_api_key
from pydantic import BaseModel
from strands.models import CacheConfig, CacheToolsConfig, Model
from strands.models.bedrock import BedrockModel
from strands.models.openai import OpenAIModel
from strands.types.content import Messages, SystemContentBlock
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

PRIMARY_MODEL_ID = os.environ.get("FROGBOT_PRIMARY_MODEL_ID", "z-ai/glm-5.3-flash")
FALLBACK_MODEL_ID = os.environ.get(
    "FROGBOT_FALLBACK_MODEL_ID",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
)
OPENROUTER_BASE_URL = os.environ.get(
    "FROGBOT_OPENROUTER_BASE_URL",
    "https://openrouter.ai/api/v1",
)
OPENROUTER_CREDENTIAL_PROVIDER = os.environ.get(
    "FROGBOT_OPENROUTER_CREDENTIAL_PROVIDER",
    "FrogBot_OpenRouter",
)


class PrimaryFallbackModel(Model):
    """Use the primary provider unless it fails before emitting a response."""

    def __init__(self, primary: Model, fallback: Model) -> None:
        self.primary = primary
        self.fallback = fallback

    @property
    def stateful(self) -> bool:
        return self.primary.stateful or self.fallback.stateful

    def update_config(self, **model_config: Any) -> None:
        self.primary.update_config(**model_config)

    def get_config(self) -> Any:
        return self.primary.get_config()

    async def structured_output(
        self,
        output_model: type[T],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, T | Any], None]:
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
            _log_fallback(error)
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
        buffered: list[StreamEvent] = []
        committed = False
        try:
            async for event in self.primary.stream(
                messages, tool_specs, system_prompt, **call
            ):
                if committed:
                    yield event
                    continue
                buffered.append(event)
                if _starts_response(event):
                    committed = True
                    log.info(
                        "Primary model %s began streaming a response", PRIMARY_MODEL_ID
                    )
                    for buffered_event in buffered:
                        yield buffered_event
                    buffered.clear()
            if not committed:
                for buffered_event in buffered:
                    yield buffered_event
        except Exception as error:
            if committed:
                raise
            _log_fallback(error)
            async for event in self.fallback.stream(
                messages, tool_specs, system_prompt, **call
            ):
                yield event


def _starts_response(event: StreamEvent) -> bool:
    return "contentBlockDelta" in event or "messageStop" in event


def _log_fallback(error: Exception) -> None:
    log.warning(
        "Primary model failed before streaming content; using Bedrock fallback (%s)",
        type(error).__name__,
    )


@requires_api_key(provider_name=OPENROUTER_CREDENTIAL_PROVIDER)
async def _openrouter_api_key(*, api_key: str) -> str:
    return api_key


def load_bedrock_model() -> BedrockModel:
    return BedrockModel(
        model_id=FALLBACK_MODEL_ID,
        max_tokens=4096,
        temperature=0.3,
        cache_config=CacheConfig(strategy="auto", ttl="1h"),
        cache_tools=CacheToolsConfig(type="default", ttl="1h"),
    )


def _load_openrouter_model(api_key: str) -> OpenAIModel:
    return OpenAIModel(
        model_id=PRIMARY_MODEL_ID,
        context_window_limit=200_000,
        params={"max_tokens": 4096, "temperature": 0.3},
        client_args={
            "api_key": api_key,
            "base_url": OPENROUTER_BASE_URL,
            "default_headers": {
                "HTTP-Referer": "https://froggybot.com",
                "X-OpenRouter-Title": "FroggyBot",
            },
        },
    )


async def load_model() -> Model:
    """Load OpenRouter as primary and Bedrock as a safe fallback."""
    fallback = load_bedrock_model()
    try:
        api_key = await _openrouter_api_key()
    except Exception as error:  # noqa: BLE001
        # Credential lookup failures are provider failures and should not block Bedrock.
        _log_fallback(error)
        return fallback
    log.info(
        "Configured primary model %s with Bedrock fallback %s",
        PRIMARY_MODEL_ID,
        FALLBACK_MODEL_ID,
    )
    return PrimaryFallbackModel(_load_openrouter_model(api_key), fallback)
