from __future__ import annotations

import sys
from pathlib import Path

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

    monkeypatch.setattr(capabilities, "AgentCoreCodeInterpreter", FakeInterpreter)
    monkeypatch.setattr(capabilities, "AgentCoreBrowser", FakeBrowser)
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
