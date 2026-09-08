from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from strands.types.exceptions import MaxTokensReachedException

# A tool-heavy change can legitimately need more than two model chunks. Keep the
# cap finite so a model that never concludes still fails instead of looping forever.
MAX_TOKEN_CONTINUATIONS = 3


async def stream_with_token_recovery(
    agent: Any,
    prompt: Any,
    *,
    logger: logging.Logger | None = None,
) -> AsyncIterator[Any]:
    """Resume partial model responses without restarting completed tool work."""
    continuations = 0
    next_prompt = prompt
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
            # Strands has already added the partial assistant message to agent.messages.
            # A prompt of None continues that same conversation without duplicating the
            # user's request or rerunning tool calls that already completed.
            next_prompt = None
