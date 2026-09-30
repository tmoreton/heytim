from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import main as runtime_main
import pytest
from strands.agent.agent_result import AgentResult
from strands.interrupt import Interrupt
from strands.telemetry.metrics import EventLoopMetrics
from strands.types.exceptions import MaxTokensReachedException

from heytim_runtime.action_approval import _proposal
from heytim_runtime.configuration import BotConfiguration
from heytim_runtime.device_tools import _request
from heytim_runtime.memory import BalancedMemoryStore
from model.load import _load_openrouter_model
from model.usage import ProviderCallLimitExceeded


@pytest.fixture(autouse=True)
def authorized_runtime_for_cleanup_tests(monkeypatch):
    async def authorized(_payload):
        return None

    monkeypatch.setattr(runtime_main, "check_ai_consent", authorized)


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
        lambda _payload, _session_id, _actor_id, _messages, _usage, **_kwargs: config,
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


def test_home_assistant_request_uses_normal_agent(monkeypatch):
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
    monkeypatch.setattr(runtime_main, "bot_configuration", lambda *_args, **_kwargs: config)
    model = AsyncMock(side_effect=RuntimeError("normal model resumed"))
    monkeypatch.setattr(runtime_main, "load_model", model)

    async def invoke_once():
        stream = runtime_main.run_agent(
            {
                "homeAssistantHint": {"selectedLabel": "turn_on"},
            },
            SimpleNamespace(session_id="session-1"),
        )
        await stream.__anext__()

    with pytest.raises(RuntimeError, match="normal model resumed"):
        asyncio.run(invoke_once())
    model.assert_awaited_once()


@pytest.mark.parametrize(
    "error,code",
    [
        (ProviderCallLimitExceeded("model-call safety limit"), "PROVIDER_CALL_LIMIT"),
        (MaxTokensReachedException("output exhausted"), "OUTPUT_TOKEN_LIMIT"),
    ],
)
def test_known_limit_becomes_terminal_result_without_retry(monkeypatch, error, code):
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
        lambda _payload, _session_id, _actor_id, _messages, _usage, **_kwargs: config,
    )
    monkeypatch.setattr(runtime_main, "load_model", AsyncMock(return_value=object()))
    agent = SimpleNamespace(messages=[], memory_manager=None)
    harness = MagicMock(return_value=agent)
    monkeypatch.setattr(runtime_main, "create_harness", harness)

    async def over_limit(*_args, **_kwargs):
        if False:
            yield {}
        raise error

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
    assert terminal["code"] == code
    assert "unexpected" not in terminal["message"]
    assert harness.call_args.kwargs["effort"] == "auto"
    assert harness.call_args.kwargs["skills"] is False
    assert harness.call_args.kwargs["memory"] is False
    assert harness.call_args.kwargs["context_manager"] == "auto"
    assert harness.call_args.kwargs["session"] is False
    capabilities.close.assert_awaited_once()


def test_wrapped_provider_call_limit_becomes_terminal_result(monkeypatch):
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
    monkeypatch.setattr(runtime_main, "bot_configuration", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(runtime_main, "load_model", AsyncMock(return_value=object()))
    monkeypatch.setattr(
        runtime_main,
        "create_harness",
        MagicMock(return_value=SimpleNamespace(messages=[], memory_manager=None)),
    )

    async def wrapped_limit(*_args, **_kwargs):
        if False:
            yield {}
        try:
            raise ProviderCallLimitExceeded("model-call safety limit")
        except ProviderCallLimitExceeded as cause:
            raise RuntimeError("event loop failed") from cause

    monkeypatch.setattr(runtime_main, "stream_with_token_recovery", wrapped_limit)

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
    capabilities.close.assert_awaited_once()


@pytest.mark.parametrize("kind", ["approval", "device"])
def test_public_result_event_saves_and_exposes_pending_interrupt(monkeypatch, kind):
    config = BotConfiguration(
        instructions="",
        tools=[],
        builtin_tools=[],
        plugins=[],
        builtin_plugins=[],
        background_work=SimpleNamespace(pending=[]),
        capability_configuration=SimpleNamespace(
            close=AsyncMock(), bot_mutations=SimpleNamespace(pending=[])
        ),
    )
    session = SimpleNamespace(save_snapshot=AsyncMock())
    agent = SimpleNamespace(messages=[], memory_manager=None)
    monkeypatch.setattr(runtime_main, "memory_context_from_payload", lambda _: None)
    monkeypatch.setattr(runtime_main, "memory_stores", lambda _: [])
    monkeypatch.setattr(
        runtime_main,
        "messages_from_payload",
        lambda *_: [{"role": "user", "content": [{"text": "Complete the task"}]}],
    )
    monkeypatch.setattr(runtime_main, "bot_configuration", lambda *_, **_kwargs: config)
    monkeypatch.setattr(runtime_main, "load_model", AsyncMock(return_value=object()))
    harness = MagicMock(return_value=agent)
    monkeypatch.setattr(runtime_main, "create_harness", harness)
    monkeypatch.setattr(runtime_main, "interrupt_session_manager", lambda *_: session)
    monkeypatch.setattr(
        runtime_main,
        "approval_configuration",
        lambda *_: (object(), session) if kind == "approval" else None,
    )
    if kind == "approval":
        proposal = _proposal(
            {"toolUseId": "call-1", "name": "update_record", "input": {"id": "1"}}
        )
        interrupt_name, control_key = "heytim_exact_action", "pendingApproval"
    else:
        proposal = _request(
            {"toolUseId": "call-1", "name": "apple_health_steps", "input": {"days": 7}},
            platform="ios",
            tool_id="apple_health",
        )
        interrupt_name, control_key = "heytim_device_call", "pendingDeviceCall"
    result = AgentResult(
        stop_reason="interrupt",
        message={"role": "assistant", "content": []},
        metrics=EventLoopMetrics(),
        state={},
        interrupts=[Interrupt("interrupt-1", interrupt_name, proposal)],
    )

    async def interrupted(_agent, _prompt, **kwargs):
        assert kwargs["turn_slice_size"] == 8
        assert kwargs["checkpoint"] is not None
        yield {"result": result}

    monkeypatch.setattr(runtime_main, "stream_with_token_recovery", interrupted)

    async def collect():
        return [
            event
            async for event in runtime_main.run_agent(
                {"runtimeJob": {"id": "job-1"}, "memory": {"eventId": "turn-1"}},
                SimpleNamespace(session_id="session-1"),
            )
        ]

    events = asyncio.run(collect())
    control = events[-1]["heytimControl"]
    assert control[control_key]["id"] == "interrupt-1"
    assert control[control_key]["digest"] == proposal["digest"]
    assert "terminalError" not in control
    session.save_snapshot.assert_awaited_once_with(agent, is_latest=True)
    assert harness.call_args.kwargs["callback_handler"] is None
    config.capability_configuration.close.assert_awaited_once()
