from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import main as runtime_main
import pytest

from frogbot_runtime.configuration import BotConfiguration


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
        lambda _payload, _session_id, _actor_id, _messages: config,
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
