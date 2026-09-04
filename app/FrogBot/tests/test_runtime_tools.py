from __future__ import annotations

import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import main


def test_catalog_bindings_select_stan_features_and_local_tools(monkeypatch) -> None:
    class FakeInterpreter:
        def __init__(self, **_kwargs):
            self.code_interpreter = type(
                "Tool", (), {"tool_name": "code_interpreter"}
            )()

    class FakeBrowser:
        def __init__(self, **_kwargs):
            self.browser = type("Tool", (), {"tool_name": "browser"})()

    monkeypatch.setattr(main, "AgentCoreCodeInterpreter", FakeInterpreter)
    monkeypatch.setattr(main, "AgentCoreBrowser", FakeBrowser)
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
                {
                    "id": "browser",
                    "runtime": {"kind": "agentcore", "name": "browser"},
                },
            ],
        }
    }

    _, tools, builtins, _, _, plugins, subagents = main._bot_config(payload)

    assert [tool.tool_name for tool in tools] == ["calculate", "code_interpreter", "browser"]
    assert builtins == ["web_fetch"]
    assert plugins == ["todos"]
    assert subagents == ["generalist"]


def test_catalog_binding_rejects_unreviewed_runtime_features() -> None:
    bot = {
        "toolIds": [],
        "tools": [
            {"id": "shell", "runtime": {"kind": "stan_builtin", "name": "shell"}}
        ],
    }

    try:
        main._tool_bindings(bot)
    except ValueError as error:
        assert "unsupported" in str(error)
    else:
        raise AssertionError("unreviewed runtime binding was accepted")
