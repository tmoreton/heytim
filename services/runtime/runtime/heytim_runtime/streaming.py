from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from strands.types.exceptions import MaxTokensReachedException

from model.load import increase_output_budget

# Limit consecutive truncations without completed work. Successful tool results
# reset this streak; the shared model-call cap and deadline still bound the run.
MAX_TOKEN_CONTINUATIONS = 3
MAX_INCOMPLETE_TURN_CONTINUATIONS = 1
AGENT_RUN_TIMEOUT_SECONDS = int(
    os.environ.get("HEYTIM_AGENT_RUN_TIMEOUT_SECONDS", "720")
)
if not 30 <= AGENT_RUN_TIMEOUT_SECONDS <= 28800:
    raise ValueError("HEYTIM_AGENT_RUN_TIMEOUT_SECONDS must be between 30 and 28800")
AGENT_IDLE_TIMEOUT_SECONDS = int(
    os.environ.get("HEYTIM_AGENT_IDLE_TIMEOUT_SECONDS", "180")
)
if not 30 <= AGENT_IDLE_TIMEOUT_SECONDS <= 600:
    raise ValueError("HEYTIM_AGENT_IDLE_TIMEOUT_SECONDS must be between 30 and 600")

INCOMPLETE_TURN_CONTINUATION_PROMPT = (
    "Continue the same request now. Your previous response ended by announcing "
    "unfinished work. Perform the promised actions with the available tools before "
    "answering. Do not repeat the plan. Finish with the concrete outcome and verified "
    "evidence, or state the exact blocker and the action you attempted."
)
_ACTION_VERBS = (
    r"fetch|retrieve|inspect|read|edit|create|update|write|change|run|test|"
    r"validate|push|commit|open|submit|deploy|check|finish|complete|implement|fix"
)
_INCOMPLETE_END_PATTERNS = (
    re.compile(
        rf"(?:^|[.!?]\s+|\n)\s*(?:now\s+)?(?:let\s+me|next\s*,?\s*(?:i|we)(?:'ll|\s+will)|"
        rf"(?:i|we)(?:'ll|\s+will))\s+(?:just\s+)?(?:{_ACTION_VERBS})\b[^.!?]*[.!?]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"(?:^|[.!?]\s+|\n)\s*(?:now\s+)?(?:i|we)\s+(?:still\s+)?(?:need|have|must)\s+"
        rf"(?:to\s+)?(?:{_ACTION_VERBS})\b[^.!?]*[.!?]?\s*$",
        re.IGNORECASE,
    ),
)


class AgentRunTimeoutError(TimeoutError):
    """Raised when one complete user turn exceeds its wall-clock budget."""


class AgentRunStalledError(TimeoutError):
    """Raised when a running agent emits no stream activity for too long."""


class AgentIncompleteTurnError(RuntimeError):
    """Raised when an agent repeatedly ends while promising unfinished work."""


def _event_payload(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    event = value.get("event", value)
    return event if isinstance(event, dict) else {}


def _completed_tool_work(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    results = [event.get("tool_result")]
    # The public SDK stream emits the assembled message, not its internal
    # ToolResultEvent. Support both shapes so completed work resets recovery.
    message = event.get("message")
    if isinstance(message, dict) and message.get("role") == "user":
        results.extend(
            block.get("toolResult")
            for block in message.get("content", [])
            if isinstance(block, dict)
        )
    return any(
        isinstance(result, dict) and result.get("status") == "success"
        for result in results
    )


class _CompletionTracker:
    def __init__(self) -> None:
        self._chunks: list[str] = []
        self.final_text = ""

    def observe(self, value: Any) -> None:
        event = _event_payload(value)
        if "messageStart" in event:
            self._chunks = []
        block_delta = event.get("contentBlockDelta")
        delta = block_delta.get("delta") if isinstance(block_delta, dict) else None
        text = delta.get("text") if isinstance(delta, dict) else None
        if isinstance(text, str):
            self._chunks.append(text)
        message_stop = event.get("messageStop")
        if not isinstance(message_stop, dict):
            return
        if message_stop.get("stopReason") == "end_turn":
            self.final_text = "".join(self._chunks).strip()
        self._chunks = []


def looks_like_incomplete_turn(text: str) -> bool:
    """Conservatively detect a final answer that is really a progress update."""
    tail = text.strip()[-800:]
    if not tail or re.search(
        r"\bif\s+you\s+(?:want|would\s+like)\b", tail, re.IGNORECASE
    ):
        return False
    return any(pattern.search(tail) for pattern in _INCOMPLETE_END_PATTERNS)


async def _next_with_idle_timeout(
    iterator: Any,
    timeout_seconds: float,
) -> Any:
    timeout_context = None
    try:
        async with asyncio.timeout(timeout_seconds) as timeout_context:
            return await anext(iterator)
    except TimeoutError as exc:
        if timeout_context is None or not timeout_context.expired():
            raise
        raise AgentRunStalledError(
            f"Agent emitted no activity for {timeout_seconds:g} seconds"
        ) from exc


async def stream_with_token_recovery(
    agent: Any,
    prompt: Any,
    *,
    logger: logging.Logger | None = None,
    timeout_seconds: float = AGENT_RUN_TIMEOUT_SECONDS,
    idle_timeout_seconds: float = AGENT_IDLE_TIMEOUT_SECONDS,
    turn_slice_size: int | None = None,
    checkpoint: Callable[[Any], Awaitable[None]] | None = None,
) -> AsyncIterator[Any]:
    """Resume partial or prematurely-ended responses within bounded budgets."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if idle_timeout_seconds <= 0:
        raise ValueError("idle_timeout_seconds must be positive")
    if turn_slice_size is not None and (
        type(turn_slice_size) is not int or turn_slice_size < 1
    ):
        raise ValueError("turn_slice_size must be a positive integer")
    token_continuations = 0
    incomplete_turn_continuations = 0
    next_prompt = prompt
    timeout_context = None
    try:
        async with asyncio.timeout(timeout_seconds) as timeout_context:
            while True:
                tracker = _CompletionTracker()
                stop_reason = None
                try:
                    stream = agent.stream_async(
                        next_prompt,
                        **(
                            {"limits": {"turns": turn_slice_size}}
                            if turn_slice_size
                            else {}
                        ),
                    )
                    iterator = stream.__aiter__()
                    while True:
                        try:
                            event = await _next_with_idle_timeout(
                                iterator, idle_timeout_seconds
                            )
                        except StopAsyncIteration:
                            break
                        tracker.observe(event)
                        if isinstance(event, dict) and event.get("stop"):
                            stop_reason = event["stop"][0]
                        if isinstance(event, dict) and event.get("result") is not None:
                            stop_reason = getattr(
                                event["result"], "stop_reason", stop_reason
                            )
                        if _completed_tool_work(event):
                            token_continuations = 0
                        yield event
                except MaxTokensReachedException:
                    if token_continuations >= MAX_TOKEN_CONTINUATIONS:
                        raise
                    token_continuations += 1
                    increase_output_budget(getattr(agent, "model", None))
                    if checkpoint is not None:
                        await checkpoint(agent)
                    if logger:
                        logger.warning(
                            "Model reached its output token limit; resuming partial turn (%d/%d)",
                            token_continuations,
                            MAX_TOKEN_CONTINUATIONS,
                        )
                    # Strands has already added the partial assistant message to
                    # agent.messages. A prompt of None continues that same conversation
                    # without duplicating the request or completed tool calls.
                    next_prompt = None
                    continue
                except AgentRunStalledError:
                    if logger:
                        logger.error(
                            "Agent emitted no stream activity for %g seconds",
                            idle_timeout_seconds,
                        )
                    raise

                if stop_reason == "limit_turns":
                    # Strands stops between complete tool batches with valid
                    # history. Continue that history, never the original prompt.
                    if checkpoint is not None:
                        await checkpoint(agent)
                    next_prompt = None
                    if logger:
                        logger.info("Saved long-running task checkpoint; continuing")
                    continue

                if not looks_like_incomplete_turn(tracker.final_text):
                    return
                if incomplete_turn_continuations >= MAX_INCOMPLETE_TURN_CONTINUATIONS:
                    if logger:
                        logger.error(
                            "Agent repeatedly ended with an unfinished-action promise"
                        )
                    raise AgentIncompleteTurnError(
                        "Agent repeatedly ended before completing promised work"
                    )
                incomplete_turn_continuations += 1
                if logger:
                    logger.warning(
                        "Agent ended with unfinished work; automatically continuing (%d/%d)",
                        incomplete_turn_continuations,
                        MAX_INCOMPLETE_TURN_CONTINUATIONS,
                    )
                next_prompt = INCOMPLETE_TURN_CONTINUATION_PROMPT
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
