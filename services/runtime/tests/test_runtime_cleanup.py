from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import main as runtime_main
import pytest

from heytim_runtime.configuration import BotConfiguration
from heytim_runtime.memory import BalancedMemoryStore
from model.load import _load_openrouter_model
from model.usage import ProviderCallLimitExceeded


def test_live_harness_accepts_production_overrides():
    model = _load_openrouter_model(
        "test-key-12345678901234567890",
        model_id="openai/gpt-5.6-sol",
        reasoning_effort="high",
        max_tokens=1_000,
        temperature=0.1,
    )
    agent = runtime_main.create_harness(
        model=model,
        effort="auto",
        caching=False,
        builtin_tools=[],
        builtin_plugins=[],
        skills=False,
        memory={"stores": [BalancedMemoryStore("test", [])]},
        context_manager="auto",
        session=False,
    )

    assert agent.memory_manager is not None
    assert agent._session_manager is None


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


def test_home_assistant_quick_route_skips_large_model(monkeypatch):
    monkeypatch.setattr(
        runtime_main, "memory_context_from_payload", lambda _payload: None
    )
    monkeypatch.setattr(
        runtime_main,
        "messages_from_payload",
        lambda _payload, _actor_id: [
            {"role": "user", "content": [{"text": "Turn on the bedroom light"}]}
        ],
    )
    route = AsyncMock(return_value={"pendingApproval": {"id": "review-1"}})
    model = AsyncMock()
    monkeypatch.setattr(runtime_main, "maybe_route_home_assistant", route)
    monkeypatch.setattr(runtime_main, "load_model", model)

    async def collect(payload):
        return [
            event
            async for event in runtime_main.run_agent(
                payload, SimpleNamespace(session_id="session-1")
            )
        ]

    payload = {"homeAssistantHint": {"selectedLabel": "turn_on"}}
    assert asyncio.run(collect(payload)) == [
        {"heytimControl": {"pendingApproval": {"id": "review-1"}}}
    ]
    model.assert_not_awaited()
    route.assert_awaited_once_with(payload, "Turn on the bedroom light")

    route.reset_mock()
    route.return_value = None
    resumed = payload | {
        "actionApproval": {
            "id": "review-1",
            "digest": "old",
            "toolUseId": "ha-fast-call-1",
        }
    }
    result = asyncio.run(collect(resumed))
    assert (
        result[0]["heytimControl"]["terminalError"]["code"] == "HA_APPROVAL_UNAVAILABLE"
    )
    model.assert_not_awaited()


def test_read_only_home_assistant_route_without_model_hint(monkeypatch):
    monkeypatch.setattr(runtime_main, "memory_context_from_payload", lambda _payload: None)
    monkeypatch.setattr(
        runtime_main,
        "messages_from_payload",
        lambda _payload, _actor_id: [
            {"role": "user", "content": [{"text": "What is the current state of Bedroom Light?"}]}
        ],
    )
    route = AsyncMock(return_value={"text": "Home Assistant shows Bedroom Light is on."})
    model = AsyncMock()
    monkeypatch.setattr(runtime_main, "maybe_route_home_assistant", route)
    monkeypatch.setattr(runtime_main, "load_model", model)

    async def collect():
        return [
            event
            async for event in runtime_main.run_agent(
                {}, SimpleNamespace(session_id="session-1")
            )
        ]

    assert asyncio.run(collect())[:3] == [
        {"event": {"messageStart": {"role": "assistant"}}},
        {"event": {"contentBlockDelta": {"delta": {"text": "Home Assistant shows Bedroom Light is on."}}}},
        {"event": {"messageStop": {"stopReason": "end_turn"}}},
    ]
    route.assert_awaited_once_with({}, "What is the current state of Bedroom Light?")
    model.assert_not_awaited()


def test_normal_approval_with_home_hint_resumes_normal_agent(monkeypatch):
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
        lambda _payload, _actor_id: [
            {"role": "user", "content": [{"text": "Turn on the bedroom light"}]}
        ],
    )
    monkeypatch.setattr(runtime_main, "memory_stores", lambda _context: [])
    monkeypatch.setattr(runtime_main, "bot_configuration", lambda *_args: config)
    route = AsyncMock()
    model = AsyncMock(side_effect=RuntimeError("normal model resumed"))
    monkeypatch.setattr(runtime_main, "maybe_route_home_assistant", route)
    monkeypatch.setattr(runtime_main, "load_model", model)

    async def invoke_once():
        stream = runtime_main.run_agent(
            {
                "homeAssistantHint": {"selectedLabel": "turn_on"},
                "actionApproval": {"toolUseId": "normal-tool-call"},
            },
            SimpleNamespace(session_id="session-1"),
        )
        await stream.__anext__()

    with pytest.raises(RuntimeError, match="normal model resumed"):
        asyncio.run(invoke_once())
    route.assert_not_awaited()
    model.assert_awaited_once()


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
        lambda _payload, _actor_id: [{"role": "user", "content": [{"text": "hello"}]}],
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
    monkeypatch.setattr(runtime_main, "create_harness", harness)

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
    assert harness.call_args.kwargs["effort"] == "auto"
    assert harness.call_args.kwargs["skills"] is False
    assert harness.call_args.kwargs["memory"] is False
    assert harness.call_args.kwargs["context_manager"] == "auto"
    assert harness.call_args.kwargs["session"] is False
    capabilities.close.assert_awaited_once()
