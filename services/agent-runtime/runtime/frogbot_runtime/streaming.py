from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from strands.types.exceptions import MaxTokensReachedException

# A tool-heavy change can legitimately need more than two model chunks. Keep the
# cap finite so a model that never concludes still fails instead of looping forever.
MAX_TOKEN_CONTINUATIONS = 3
AGENT_RUN_TIMEOUT_SECONDS = int(
    os.environ.get("FROGBOT_AGENT_RUN_TIMEOUT_SECONDS", "300")
)
if not 30 <= AGENT_RUN_TIMEOUT_SECONDS <= 900:
    raise ValueError("FROGBOT_AGENT_RUN_TIMEOUT_SECONDS must be between 30 and 900")


class AgentRunTimeoutError(TimeoutError):
    """Raised when one complete user turn exceeds its wall-clock budget."""


async def stream_with_token_recovery(
    agent: Any,
    prompt: Any,
    *,
    logger: logging.Logger | None = None,
    timeout_seconds: float = AGENT_RUN_TIMEOUT_SECONDS,
) -> AsyncIterator[Any]:
    """Resume partial model responses without restarting completed tool work."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    continuations = 0
    next_prompt = prompt
    timeout_context = None
    try:
        async with asyncio.timeout(timeout_seconds) as timeout_context:
            while True:
                try:
                    async for event in agent.stream_async(next_prompt):
                        yield event
                    return
                except MaxTokensReachedException:
                    if continuations >= MAX_TOKEN_CONTINUATIONS:
                        raise
                    continuations += 1
                    if logger:
                        logger.warning(
                            "Model reached its output token limit; resuming partial turn (%d/%d)",
                            continuations,
                            MAX_TOKEN_CONTINUATIONS,
                        )
                    # Strands has already added the partial assistant message to
                    # agent.messages. A prompt of None continues that same conversation
                    # without duplicating the request or completed tool calls.
                    next_prompt = None
    except TimeoutError as exc:
        if timeout_context is None or not timeout_context.expired():
            raise
        if logger:
            logger.error(
                "Agent turn exceeded its %g-second wall-clock budget",
                timeout_seconds,
            )
        raise AgentRunTimeoutError(
            f"Agent turn exceeded {timeout_seconds:g} seconds"
        ) from exc
