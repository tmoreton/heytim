from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import main as runtime_main
import pytest

from heytim_runtime.configuration import BotConfiguration
from model.usage import ProviderCallLimitExceeded


def test_run_agent_releases_capabilities_when_setup_fails(monkeypatch):
    capabilities = SimpleNamespace(close=AsyncMock())
    config = BotConfiguration(
        instructions="",
        tools=[],
        builtin_tools=[],
        plugins=[],
        builtin_plugins=[],
        background_work=SimpleNamespace(pending=[]),
        capability_configuration=capabilities,
    )
    monkeypatch.setattr(
        runtime_main, "memory_context_from_payload", lambda _payload: None
    )
    monkeypatch.setattr(
        runtime_main,
        "messages_from_payload",
        lambda _payload, _actor_id: [{"role": "user", "content": [{"text": "hello"}]}],
    )
    monkeypatch.setattr(runtime_main, "memory_stores", lambda _context: [])
    monkeypatch.setattr(
        runtime_main,
        "bot_configuration",
        lambda _payload, _session_id, _actor_id, _messages, _usage: config,
    )
    monkeypatch.setattr(
        runtime_main,
        "load_model",
        AsyncMock(side_effect=RuntimeError("model setup failed")),
    )

    async def invoke_once():
        stream = runtime_main.run_agent({}, SimpleNamespace(session_id="session-1"))
        await stream.__anext__()

    with pytest.raises(RuntimeError, match="model setup failed"):
        asyncio.run(invoke_once())

    capabilities.close.assert_awaited_once()


def test_provider_call_limit_becomes_terminal_result_without_retry(monkeypatch):
    capabilities = SimpleNamespace(
        close=AsyncMock(),
        bot_mutations=SimpleNamespace(pending=[]),
    )
    config = BotConfiguration(
        instructions="",
        tools=[],
        builtin_tools=[],
        plugins=[],
        builtin_plugins=[],
        background_work=SimpleNamespace(pending=[]),
        capability_configuration=capabilities,
    )
    monkeypatch.setattr(
        runtime_main, "memory_context_from_payload", lambda _payload: None
    )
    monkeypatch.setattr(
        runtime_main,
        "messages_from_payload",
        lambda _payload, _actor_id: [
            {"role": "user", "content": [{"text": "hello"}]}
        ],
    )
    monkeypatch.setattr(runtime_main, "memory_stores", lambda _context: [])
    monkeypatch.setattr(
        runtime_main,
        "bot_configuration",
        lambda _payload, _session_id, _actor_id, _messages, _usage: config,
    )
    monkeypatch.setattr(runtime_main, "load_model", AsyncMock(return_value=object()))
    agent = SimpleNamespace(messages=[], memory_manager=None)
    harness = MagicMock(return_value=agent)
    monkeypatch.setattr(runtime_main, "harness_agent", harness)

    async def over_limit(*_args, **_kwargs):
        if False:
            yield {}
        raise ProviderCallLimitExceeded("model-call safety limit")

    monkeypatch.setattr(runtime_main, "stream_with_token_recovery", over_limit)

    async def collect():
        return [
            event
            async for event in runtime_main.run_agent(
                {}, SimpleNamespace(session_id="session-1")
            )
        ]

    events = asyncio.run(collect())

    terminal = next(
        event["heytimControl"]["terminalError"]
        for event in events
        if "terminalError" in event.get("heytimControl", {})
    )
    assert terminal["code"] == "PROVIDER_CALL_LIMIT"
    assert "provider-call safety limit" in terminal["message"]
    assert harness.call_args.kwargs["skills_dir"] is None
    capabilities.close.assert_awaited_once()
