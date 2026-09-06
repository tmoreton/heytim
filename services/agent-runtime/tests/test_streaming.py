from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from strands.types.exceptions import MaxTokensReachedException

from frogbot_runtime.streaming import stream_with_token_recovery


class FakeAgent:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.prompts: list[Any] = []

    async def stream_async(self, prompt: Any) -> AsyncGenerator[dict, None]:
        self.prompts.append(prompt)
        yield {"attempt": len(self.prompts)}
        if len(self.prompts) <= self.failures:
            raise MaxTokensReachedException("partial")


async def _events(agent: FakeAgent, prompt: Any) -> list[dict]:
    return [event async for event in stream_with_token_recovery(agent, prompt)]


def test_resumes_one_partial_turn_without_repeating_the_prompt() -> None:
    agent = FakeAgent(failures=1)

    events = asyncio.run(_events(agent, [{"role": "user"}]))

    assert events == [{"attempt": 1}, {"attempt": 2}]
    assert agent.prompts == [[{"role": "user"}], None]


def test_second_token_limit_is_propagated() -> None:
    agent = FakeAgent(failures=2)

    with pytest.raises(MaxTokensReachedException, match="partial"):
        asyncio.run(_events(agent, "hello"))

    assert agent.prompts == ["hello", None]
