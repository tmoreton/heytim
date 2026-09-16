from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from strands.types.exceptions import MaxTokensReachedException

from frogbot_runtime.streaming import (
    INCOMPLETE_TURN_CONTINUATION_PROMPT,
    AgentIncompleteTurnError,
    AgentRunStalledError,
    AgentRunTimeoutError,
    looks_like_incomplete_turn,
    stream_with_token_recovery,
)


class FakeAgent:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.prompts: list[Any] = []

    async def stream_async(self, prompt: Any) -> AsyncGenerator[dict]:
        self.prompts.append(prompt)
        yield {"attempt": len(self.prompts)}
        if len(self.prompts) <= self.failures:
            raise MaxTokensReachedException("partial")


async def _events(agent: Any, prompt: Any, **kwargs: Any) -> list[dict]:
    return [
        event async for event in stream_with_token_recovery(agent, prompt, **kwargs)
    ]


class ResponseAgent:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[Any] = []

    async def stream_async(self, prompt: Any) -> AsyncGenerator[dict]:
        self.prompts.append(prompt)
        response = self.responses[len(self.prompts) - 1]
        yield {"event": {"messageStart": {"role": "assistant"}}}
        yield {"event": {"contentBlockDelta": {"delta": {"text": response}}}}
        yield {"event": {"messageStop": {"stopReason": "end_turn"}}}


def test_resumes_repeated_partial_turns_without_repeating_the_prompt() -> None:
    agent = FakeAgent(failures=3)

    events = asyncio.run(_events(agent, [{"role": "user"}]))

    assert events == [
        {"attempt": 1},
        {"attempt": 2},
        {"attempt": 3},
        {"attempt": 4},
    ]
    assert agent.prompts == [[{"role": "user"}], None, None, None]


def test_token_limit_after_final_continuation_is_propagated() -> None:
    agent = FakeAgent(failures=4)

    with pytest.raises(MaxTokensReachedException, match="partial"):
        asyncio.run(_events(agent, "hello"))

    assert agent.prompts == ["hello", None, None, None]


def test_complete_turn_has_a_wall_clock_deadline() -> None:
    class SlowAgent:
        async def stream_async(self, _prompt: Any) -> AsyncGenerator[dict]:
            await asyncio.sleep(1)
            yield {"too": "late"}

    async def run() -> None:
        async for _event in stream_with_token_recovery(
            SlowAgent(), "hello", timeout_seconds=0.01
        ):
            pass

    with pytest.raises(AgentRunTimeoutError, match="0.01 seconds"):
        asyncio.run(run())


def test_unfinished_final_answer_is_continued_automatically() -> None:
    agent = ResponseAgent(
        [
            "I have the branch. Now I need to fetch marketplace.json. Let me fetch it in the sandbox.",
            "Done. The marketplace entry was validated, pushed, and opened as PR #123.",
        ]
    )

    events = asyncio.run(_events(agent, "finish the task"))

    assert len(events) == 6
    assert agent.prompts == ["finish the task", INCOMPLETE_TURN_CONTINUATION_PROMPT]


def test_repeated_unfinished_final_answer_is_not_marked_complete() -> None:
    agent = ResponseAgent(
        [
            "Now I need to validate the files.",
            "I will push the branch next.",
        ]
    )

    with pytest.raises(AgentIncompleteTurnError, match="promised work"):
        asyncio.run(_events(agent, "finish the task"))

    assert agent.prompts == ["finish the task", INCOMPLETE_TURN_CONTINUATION_PROMPT]


def test_conditional_follow_up_offer_is_not_treated_as_unfinished() -> None:
    text = "The requested change is deployed and verified. If you want, I can add another test."

    assert not looks_like_incomplete_turn(text)


def test_no_stream_activity_has_a_separate_deadline() -> None:
    class StalledAgent:
        async def stream_async(self, _prompt: Any) -> AsyncGenerator[dict]:
            await asyncio.sleep(1)
            yield {"event": {"messageStart": {"role": "assistant"}}}

    with pytest.raises(AgentRunStalledError, match="no activity"):
        asyncio.run(
            _events(
                StalledAgent(),
                "hello",
                timeout_seconds=1,
                idle_timeout_seconds=0.01,
            )
        )
