from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from frogbot_runtime import capabilities
from frogbot_runtime.configuration import bot_configuration


def test_catalog_bindings_select_stan_features_and_local_tools(monkeypatch) -> None:
    class FakeInterpreter:
        def __init__(self, **_kwargs):
            self.code_interpreter = type(
                "Tool", (), {"tool_name": "code_interpreter"}
            )()

    class FakeBrowser:
        def __init__(self, **_kwargs):
            self.browser = type("Tool", (), {"tool_name": "browser"})()

    monkeypatch.setattr(
        capabilities, "PersistentAgentCoreCodeInterpreter", FakeInterpreter
    )
    monkeypatch.setattr(capabilities, "PersistentAgentCoreBrowser", FakeBrowser)
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
        "browser",
    ]
    assert config.builtin_tools == ["web_fetch"]
    assert config.builtin_plugins == ["todos"]
    assert config.builtin_subagents == ["generalist"]
    assert "does not need to name a skill or tool" in config.instructions
    assert "activate it with the skills tool" in config.instructions
    assert "actually activated or called it" in config.instructions


def test_catalog_binding_rejects_unreviewed_runtime_features() -> None:
    bot = {
        "toolIds": [],
        "tools": [
            {"id": "shell", "runtime": {"kind": "stan_builtin", "name": "shell"}}
        ],
    }

    try:
        capabilities.tool_bindings(bot)
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("unreviewed runtime binding was accepted")


def test_calculator_accepts_arithmetic_and_rejects_code() -> None:
    assert capabilities.calculate("(8 + 4) / 3") == "4.0"
    try:
        capabilities.calculate("__import__('os').getcwd()")
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("calculator accepted executable code")


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

    monkeypatch.setattr(capabilities, "CodeInterpreterClient", FakeClient)
    interpreter = capabilities.PersistentAgentCoreCodeInterpreter(
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

    monkeypatch.setattr(capabilities, "BrowserClient", FakeClient)
    browser = capabilities.PersistentAgentCoreBrowser(
        region="us-east-1",
        session_name="frogbot-conversation-1",
        session_timeout=7200,
    )
    browser._playwright = SimpleNamespace(chromium=FakeChromium())

    connected = asyncio.run(browser.create_browser_session())

    assert connected == "connected-browser"
    assert clients[0].identifier == "aws.browser.v1"
    assert clients[0].session_id == "browser-session-123"
