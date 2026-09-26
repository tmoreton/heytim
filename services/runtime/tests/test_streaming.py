from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from strands.types.exceptions import MaxTokensReachedException

from heytim_runtime.streaming import (
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


def test_successful_work_resets_token_recovery_streak_without_replaying_prompt() -> (
    None
):
    class WorkingAgent(FakeAgent):
        async def stream_async(self, prompt):
            self.prompts.append(prompt)
            call = len(self.prompts)
            if call < 7:
                yield {"tool_result": {"status": "success", "toolUseId": str(call)}}
                raise MaxTokensReachedException("partial")
            yield {"done": True}

    agent = WorkingAgent(0)
    checkpoint = AsyncMock()
    events = asyncio.run(_events(agent, "original task", checkpoint=checkpoint))
    assert events[-1] == {"done": True}
    assert agent.prompts == ["original task"] + [None] * 6
    assert checkpoint.await_count == 6


def test_failed_tools_do_not_reset_the_no_progress_recovery_limit() -> None:
    class FailingAgent(FakeAgent):
        async def stream_async(self, prompt):
            self.prompts.append(prompt)
            yield {"tool_result": {"status": "error", "toolUseId": "failed"}}
            raise MaxTokensReachedException("partial")

    agent = FailingAgent(0)
    with pytest.raises(MaxTokensReachedException):
        asyncio.run(_events(agent, "task"))
    assert len(agent.prompts) == 4


def test_long_run_slices_checkpoint_and_continue_without_new_user_input() -> None:
    class SlicedAgent:
        def __init__(self):
            self.calls = []

        async def stream_async(self, prompt, *, limits):
            self.calls.append((prompt, limits))
            if len(self.calls) < 4:
                yield {"stop": ("limit_turns", {}, None, {})}
            else:
                yield {"event": {"messageStart": {"role": "assistant"}}}
                yield {"event": {"contentBlockDelta": {"delta": {"text": "Complete."}}}}
                yield {"event": {"messageStop": {"stopReason": "end_turn"}}}

    agent = SlicedAgent()
    checkpoint = AsyncMock()
    events = asyncio.run(
        _events(agent, "task", turn_slice_size=8, checkpoint=checkpoint)
    )
    assert agent.calls == [("task", {"turns": 8})] + [(None, {"turns": 8})] * 3
    assert checkpoint.await_count == 3
    assert events[-1]["event"]["messageStop"]["stopReason"] == "end_turn"


def test_checkpoint_failure_stops_before_starting_another_slice() -> None:
    class SlicedAgent:
        def __init__(self):
            self.calls = 0

        async def stream_async(self, _prompt, *, limits):
            self.calls += 1
            yield {"stop": ("limit_turns", {}, None, {})}

    agent = SlicedAgent()
    checkpoint = AsyncMock(side_effect=RuntimeError("checkpoint unavailable"))
    with pytest.raises(RuntimeError, match="checkpoint unavailable"):
        asyncio.run(_events(agent, "task", turn_slice_size=8, checkpoint=checkpoint))
    assert agent.calls == 1


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
