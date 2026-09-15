from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from frogbot_runtime import agentcore_adapters, capabilities, gateway_tools
from frogbot_runtime.background_work import (
    BackgroundWorkTracker,
    start_background_command,
)
from frogbot_runtime.capability_contract import tool_bindings
from frogbot_runtime.configuration import bot_configuration
from frogbot_runtime.local_tools import calculate
from model.usage import (
    YOUTUBE_QUOTA_TIME_ZONE,
    ProviderCallLimitExceeded,
    ProviderCallLimits,
    UsageAccumulator,
)


def _youtube_quota() -> dict:
    day = datetime.now(UTC).astimezone(YOUTUBE_QUOTA_TIME_ZONE).date().isoformat()
    return {"day": day, "maxCalls": 3}


def test_catalog_bindings_select_stan_features_and_local_tools(monkeypatch) -> None:
    class FakeInterpreter:
        def __init__(self, **_kwargs):
            self.code_interpreter = type(
                "Tool", (), {"tool_name": "code_interpreter"}
            )()

    class FakeBrowser:
        def __init__(self, **_kwargs):
            self.browser = type("Tool", (), {"tool_name": "browser"})()
            self.capture_points_screenshot = type(
                "Tool", (), {"tool_name": "capture_points_screenshot"}
            )()

    monkeypatch.setattr(
        agentcore_adapters, "PersistentAgentCoreCodeInterpreter", FakeInterpreter
    )
    monkeypatch.setattr(agentcore_adapters, "PersistentAgentCoreBrowser", FakeBrowser)
    payload = {
        "bot": {
            "name": "Researcher",
            "prompt": "Research carefully.",
            "skillIds": [],
            "skills": [],
            "tools": [
                {
                    "id": "calculator",
                    "runtime": {"kind": "local", "name": "calculator"},
                },
                {"id": "web", "runtime": {"kind": "stan_builtin", "name": "web_fetch"}},
                {
                    "id": "task_list",
                    "runtime": {"kind": "stan_plugin", "name": "todos"},
                },
                {
                    "id": "delegate",
                    "runtime": {"kind": "stan_subagent", "name": "generalist"},
                },
                {
                    "id": "code_interpreter",
                    "runtime": {"kind": "agentcore", "name": "code_interpreter"},
                },
                {"id": "browser", "runtime": {"kind": "agentcore", "name": "browser"}},
            ],
        }
    }

    config = bot_configuration(payload)

    assert [tool.tool_name for tool in config.tools] == [
        "calculate",
        "code_interpreter",
        "background_command",
        "browser",
    ]
    assert config.builtin_tools == ["web_fetch", "subagent"]
    assert config.builtin_plugins == ["todos"]
    assert "does not need to name a skill or tool" in config.instructions
    assert "activate it with the skills tool" in config.instructions
    assert "actually activated or called it" in config.instructions
    assert "Never invent decision-changing facts" in config.instructions
    assert "ask only the necessary questions and stop" in config.instructions
    assert "For intake, use only a brief acknowledgment" in config.instructions
    assert "do not present model memory as confirmed" in config.instructions
    background = next(
        tool for tool in config.tools if tool.tool_name == "background_command"
    )
    assert "platform resumes this conversation" in background.tool_spec["description"]
    assert "call init_session once" in agentcore_adapters.MANAGED_BROWSER_GUIDANCE
    assert "open tabs instead of another session" in (
        agentcore_adapters.MANAGED_BROWSER_GUIDANCE
    )
    assert "background_command" not in config.instructions
    assert "private browser" not in config.instructions


def test_team_roster_is_validated_and_added_as_context() -> None:
    config = bot_configuration(
        {
            "bot": {
                "name": "Chief",
                "prompt": "Route work to the right teammate.",
                "toolIds": [],
                "tools": [],
                "skillIds": [],
                "skills": [],
            },
            "team": [
                {"name": "Chief", "tagline": "Coordinates.", "isCurrent": True},
                {
                    "name": "Research & Reports",
                    "tagline": "Analyzes data and writes reports.",
                    "isCurrent": False,
                },
            ],
        }
    )

    assert '"name":"Research & Reports"' in config.instructions
    assert "exact best-matching roster name" in config.instructions
    assert "Do not invent a specialist" in config.instructions


def test_team_roster_requires_exactly_one_current_bot() -> None:
    with pytest.raises(ValueError, match="exactly one current bot"):
        bot_configuration(
            {
                "bot": {
                    "name": "Chief",
                    "prompt": "Coordinate.",
                    "toolIds": [],
                    "tools": [],
                    "skillIds": [],
                    "skills": [],
                },
                "team": [{"name": "Chief", "isCurrent": False}],
            }
        )


def test_background_command_records_durable_task_identity() -> None:
    class FakeClient:
        identifier = "aws.codeinterpreter.v1"

        def invoke(self, name: str, arguments: dict) -> dict:
            assert name == "startCommandExecution"
            assert arguments == {"command": "npm test"}
            return {
                "stream": iter(
                    [
                        {
                            "result": {
                                "structuredContent": {
                                    "taskId": "task-123",
                                    "taskStatus": "submitted",
                                }
                            }
                        }
                    ]
                )
            }

    session = SimpleNamespace(session_id="session-123", client=FakeClient())

    class FakeInterpreter:
        def __init__(self):
            self._sessions = {"conversation": session}

        def _ensure_session(self, _name):
            return "conversation", None

    tracker = BackgroundWorkTracker()

    result = start_background_command(
        FakeInterpreter(), tracker, " npm test ", "  Run   tests "
    )

    assert result["status"] == "success"
    pending = tracker.pending[0]
    assert {key: pending[key] for key in pending if key != "startedAt"} == {
        "provider": "agentcore_code_interpreter",
        "resourceId": "aws.codeinterpreter.v1",
        "sessionId": "session-123",
        "taskId": "task-123",
        "label": "Run tests",
    }


def test_completed_background_work_cannot_restart_during_resume(monkeypatch) -> None:
    class FakeInterpreter:
        def __init__(self, **_kwargs):
            self.code_interpreter = type(
                "Tool", (), {"tool_name": "code_interpreter"}
            )()

    monkeypatch.setattr(
        agentcore_adapters, "PersistentAgentCoreCodeInterpreter", FakeInterpreter
    )
    config = bot_configuration(
        {
            "bot": {
                "name": "Builder",
                "prompt": "Build and verify code.",
                "skillIds": [],
                "skills": [],
                "tools": [
                    {
                        "id": "code_interpreter",
                        "runtime": {
                            "kind": "agentcore",
                            "name": "code_interpreter",
                        },
                    }
                ],
            },
            "continuation": [
                {
                    "label": "Run tests",
                    "status": "completed",
                    "exitCode": 0,
                    "stdout": "47 passed",
                    "stderr": "",
                }
            ],
        }
    )

    assert [tool.tool_name for tool in config.tools] == ["code_interpreter"]
    assert "Do not rerun a completed command" in config.instructions


def test_catalog_binding_rejects_unreviewed_runtime_features() -> None:
    bot = {
        "toolIds": [],
        "tools": [
            {"id": "shell", "runtime": {"kind": "stan_builtin", "name": "shell"}}
        ],
    }

    try:
        tool_bindings(bot)
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("unreviewed runtime binding was accepted")


def test_runtime_rejects_unresolved_catalog_capabilities() -> None:
    for bot, message in (
        ({"toolIds": [], "skills": []}, "bot.tools"),
        ({"toolIds": [], "tools": [], "skillIds": []}, "bot.skills"),
    ):
        try:
            capabilities.resolve_capabilities(bot, "test-session")
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError("runtime accepted unresolved catalog capabilities")


def test_calculator_accepts_arithmetic_and_rejects_code() -> None:
    assert calculate("(8 + 4) / 3") == "4.0"
    try:
        calculate("__import__('os').getcwd()")
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("calculator accepted executable code")


def test_gateway_dispatches_are_counted_without_arguments(monkeypatch) -> None:
    accumulator = UsageAccumulator(youtube_search_quota=_youtube_quota())
    client = object.__new__(gateway_tools.MeteredMCPClient)
    client._frogbot_usage = accumulator

    monkeypatch.setattr(
        gateway_tools.MCPClient,
        "call_tool_sync",
        lambda *_args, **_kwargs: "sync-result",
    )

    async def call_async(*_args, **_kwargs):
        return "async-result"

    monkeypatch.setattr(gateway_tools.MCPClient, "call_tool_async", call_async)

    assert (
        client.call_tool_sync("use-1", "target___youtube_search", {"q": "x"})
        == "sync-result"
    )
    assert (
        asyncio.run(
            client.call_tool_async("use-2", "target___youtube_search", {"q": "private"})
        )
        == "async-result"
    )

    assert accumulator.snapshot()["tools"] == [
        {
            "provider": "agentcore-gateway",
            "operation": "youtube_search",
            "callCount": 2,
        }
    ]


def test_gateway_dispatch_limit_blocks_before_provider_call(monkeypatch) -> None:
    accumulator = UsageAccumulator(
        ProviderCallLimits(
            model_calls=10,
            provider_tool_calls=1,
            image_calls=1,
        ),
        youtube_search_quota=_youtube_quota(),
    )
    client = object.__new__(gateway_tools.MeteredMCPClient)
    client._frogbot_usage = accumulator
    provider_calls = []
    monkeypatch.setattr(
        gateway_tools.MCPClient,
        "call_tool_sync",
        lambda *_args, **_kwargs: provider_calls.append(True) or "result",
    )

    assert client.call_tool_sync("use-1", "target___youtube_search", {}) == "result"
    with pytest.raises(ProviderCallLimitExceeded, match="provider-tool"):
        client.call_tool_sync("use-2", "target___youtube_search", {})

    assert provider_calls == [True]


def test_youtube_search_lease_blocks_fourth_dispatch(monkeypatch) -> None:
    accumulator = UsageAccumulator(youtube_search_quota=_youtube_quota())
    client = object.__new__(gateway_tools.MeteredMCPClient)
    client._frogbot_usage = accumulator
    provider_calls = []
    monkeypatch.setattr(
        gateway_tools.MCPClient,
        "call_tool_sync",
        lambda *_args, **_kwargs: provider_calls.append(True) or "result",
    )

    for index in range(3):
        assert (
            client.call_tool_sync(f"use-{index}", "target___youtube_search", {})
            == "result"
        )
    with pytest.raises(ProviderCallLimitExceeded, match="YouTube search"):
        client.call_tool_sync("use-4", "target___youtube_search", {})

    assert provider_calls == [True, True, True]


def test_youtube_search_requires_current_reserved_day(monkeypatch) -> None:
    quota = _youtube_quota()
    accumulator = UsageAccumulator(youtube_search_quota=quota)
    accumulator._youtube_quota_day = lambda: "2099-01-01"
    client = object.__new__(gateway_tools.MeteredMCPClient)
    client._frogbot_usage = accumulator
    provider_calls = []
    monkeypatch.setattr(
        gateway_tools.MCPClient,
        "call_tool_sync",
        lambda *_args, **_kwargs: provider_calls.append(True) or "result",
    )

    with pytest.raises(ProviderCallLimitExceeded, match="expired"):
        client.call_tool_sync("use-1", "target___youtube_search", {})

    assert provider_calls == []


def test_connected_youtube_tools_share_the_project_quota_lease() -> None:
    accumulator = UsageAccumulator(youtube_search_quota=_youtube_quota())

    accumulator.observe_tool("youtube", "youtube_my_channel")
    accumulator.observe_tool("youtube", "youtube_my_videos")
    accumulator.observe_tool("agentcore-gateway", "youtube_search")
    with pytest.raises(ProviderCallLimitExceeded, match="YouTube search"):
        accumulator.observe_tool("youtube", "youtube_my_channel")


def test_code_interpreter_reconnects_ready_session_after_cold_start(
    monkeypatch,
) -> None:
    class FakeClient:
        def __init__(self, **_kwargs):
            self.identifier = None
            self.session_id = None

        def list_sessions(self, **kwargs):
            assert kwargs["interpreter_id"] == "aws.codeinterpreter.v1"
            assert kwargs["status"] == "READY"
            return {
                "items": [
                    {
                        "name": "frogbot-conversation-1",
                        "codeInterpreterIdentifier": "aws.codeinterpreter.v1",
                        "sessionId": "session-123",
                    }
                ]
            }

    monkeypatch.setattr(agentcore_adapters, "CodeInterpreterClient", FakeClient)
    interpreter = agentcore_adapters.PersistentAgentCoreCodeInterpreter(
        region="us-east-1",
        session_name="frogbot-conversation-1",
    )

    session_name, error = interpreter._ensure_session(None)

    assert session_name == "frogbot-conversation-1"
    assert error is None
    session = interpreter._sessions[session_name]
    assert session.session_id == "session-123"
    assert session.client.identifier == "aws.codeinterpreter.v1"
    assert session.client.session_id == "session-123"


def test_browser_reconnects_ready_session_after_cold_start(monkeypatch) -> None:
    clients = []

    class FakeClient:
        def __init__(self, **_kwargs):
            self.identifier = None
            self.session_id = None
            clients.append(self)

        def list_sessions(self, **kwargs):
            assert kwargs["browser_id"] == "aws.browser.v1"
            assert kwargs["status"] == "READY"
            return {
                "items": [
                    {
                        "name": "frogbot-conversation-1",
                        "browserIdentifier": "aws.browser.v1",
                        "sessionId": "browser-session-123",
                    }
                ]
            }

        def start(self, **_kwargs):
            raise AssertionError("a second browser session was started")

        def generate_ws_headers(self):
            return "wss://browser.example", {"x-session": "browser-session-123"}

    class FakeChromium:
        async def connect_over_cdp(self, *, endpoint_url, headers):
            assert endpoint_url == "wss://browser.example"
            assert headers == {"x-session": "browser-session-123"}
            return "connected-browser"

    monkeypatch.setattr(agentcore_adapters, "BrowserClient", FakeClient)
    browser = agentcore_adapters.PersistentAgentCoreBrowser(
        region="us-east-1",
        session_name="frogbot-conversation-1",
        session_timeout=7200,
    )
    browser._playwright = SimpleNamespace(chromium=FakeChromium())

    connected = asyncio.run(browser.create_browser_session())

    assert connected == "connected-browser"
    assert clients[0].identifier == "aws.browser.v1"
    assert clients[0].session_id == "browser-session-123"
