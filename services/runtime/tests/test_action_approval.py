from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import heytim_runtime.action_approval as action_approval_module
from heytim_runtime.action_approval import (
    ActionApproval,
    _proposal,
    approval_configuration,
    pending_approval,
)
from heytim_runtime.mcp_tool_names import _bounded_tool_name
from heytim_runtime.runtime_jobs import RunState


def test_exact_action_digest_covers_identity_name_and_all_arguments() -> None:
    first = _proposal({"toolUseId": "call-1", "name": "post_issue",
                       "input": {"title": "A", "repository": "one"}})
    reordered = _proposal({"toolUseId": "call-1", "name": "post_issue",
                           "input": {"repository": "one", "title": "A"}})
    changed = _proposal({"toolUseId": "call-1", "name": "post_issue",
                         "input": {"title": "A", "repository": "two"}})
    another_call = _proposal({"toolUseId": "call-2", "name": "post_issue",
                              "input": {"title": "A", "repository": "one"}})
    assert first["digest"] == reordered["digest"]
    assert first["digest"] != changed["digest"]
    assert first["digest"] != another_call["digest"]
    with pytest.raises(ValueError, match="too large"):
        _proposal({"toolUseId": "call-1", "name": "post_issue", "input": {"body": "x" * 9_000}})


def test_only_a_matching_interrupt_is_exposed_as_reviewable() -> None:
    proposal = _proposal({"toolUseId": "call-1", "name": "post_issue", "input": {"title": "A"}})
    interrupt = SimpleNamespace(id="interrupt-1", name="heytim_exact_action", reason=proposal)
    result = SimpleNamespace(stop_reason="interrupt", interrupts=[interrupt])
    exposed = pending_approval(result)
    assert exposed["id"] == "interrupt-1"
    assert exposed["input"] == {"title": "A"}
    interrupt.reason = {**proposal, "digest": "0" * 64}
    with pytest.raises(ValueError, match="proposal"):
        pending_approval(result)


def test_background_job_keeps_approval_pending_without_a_final_answer() -> None:
    state = RunState("2026-09-18T12:00:00+00:00")
    state.observe({"heytimControl": {"pendingApproval": {"id": "interrupt-1"}}})
    state.finish()
    assert state.value["status"] == "COMPLETE"
    assert state.value["pendingApproval"]["id"] == "interrupt-1"
    assert "terminalError" not in state.value


def test_home_assistant_context_read_skips_approval_but_actions_do_not() -> None:
    connection_id = "connection_16b6a400ff0b88df6fb6"
    read_name = _bounded_tool_name(connection_id, "homeassistant__GetLiveContext")
    action_name = _bounded_tool_name(connection_id, "intent__HassTurnOn")
    approval = ActionApproval(read_only_home_tools={read_name})

    read_event = SimpleNamespace(
        tool_use={"toolUseId": "read-1", "name": read_name, "input": {}},
        interrupt=Mock(),
    )
    approval.before_tool(read_event)
    read_event.interrupt.assert_not_called()

    # An unexpected argument must not get the read-only exemption.
    read_with_input = SimpleNamespace(
        tool_use={"toolUseId": "read-2", "name": read_name, "input": {"name": "all"}},
        interrupt=Mock(return_value=None),
        cancel_tool=None,
    )
    approval.before_tool(read_with_input)
    read_with_input.interrupt.assert_called_once()

    action_event = SimpleNamespace(
        tool_use={"toolUseId": "action-1", "name": action_name, "input": {"name": "Bedroom Light"}},
        interrupt=Mock(return_value=None),
        cancel_tool=None,
    )
    approval.before_tool(action_event)
    action_event.interrupt.assert_called_once()


def test_only_interactive_tool_calls_prompt_before_the_persistent_grant() -> None:
    approval = ActionApproval(interactive_names={"browser"})
    read_event = SimpleNamespace(
        tool_use={"toolUseId": "read-1", "name": "calculator", "input": {}},
        interrupt=Mock(),
    )
    approval.before_tool(read_event)
    read_event.interrupt.assert_not_called()
    action_event = SimpleNamespace(
        tool_use={"toolUseId": "action-1", "name": "browser", "input": {}},
        interrupt=Mock(return_value=None), cancel_tool=None,
    )
    approval.before_tool(action_event)
    action_event.interrupt.assert_called_once()


def test_resumed_one_time_grant_allows_subsequent_actions() -> None:
    first = {"toolUseId": "action-1", "name": "browser", "input": {"url": "https://example.com"}}
    proposal = _proposal(first)
    approval = ActionApproval(
        resume={"digest": proposal["digest"], "toolUseId": proposal["toolUseId"]},
        allow_after_resume=True, interactive_names={"browser"},
    )
    resumed = SimpleNamespace(tool_use=first, interrupt=Mock(return_value={
        "digest": proposal["digest"], "toolUseId": proposal["toolUseId"]
    }), cancel_tool=None)
    approval.before_tool(resumed)
    assert resumed.cancel_tool is None
    next_action = SimpleNamespace(tool_use={**first, "toolUseId": "action-2"}, interrupt=Mock())
    approval.before_tool(next_action)
    next_action.interrupt.assert_not_called()


def test_previously_granted_bot_skips_runtime_approval_setup() -> None:
    payload = {"bot": {
        "tools": [{"id": "browser", "risk": "interactive", "runtime": {
            "kind": "agentcore", "name": "browser"
        }}],
        "alwaysAllowedToolIds": ["browser"],
    }}
    assert approval_configuration(payload, None) is None


def test_device_binding_approves_only_declared_interactive_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        action_approval_module,
        "interrupt_session_manager",
        lambda _payload, _actor_id: "snapshot-manager",
    )
    payload = {
        "bot": {
            "tools": [
                {
                    "id": "mac_computer",
                    "risk": "interactive",
                    "runtime": {
                        "kind": "device",
                        "platform": "macos",
                        "operations": [
                            "mac_computer_observe",
                            "mac_computer_act_on_element",
                            "mac_computer_type_into_element",
                        ],
                        "interactiveOperations": [
                            "mac_computer_act_on_element",
                            "mac_computer_type_into_element",
                        ],
                    },
                }
            ],
            "alwaysAllowedToolIds": [],
        }
    }

    configured = approval_configuration(payload, None)
    assert configured is not None
    approval, manager = configured
    assert manager == "snapshot-manager"

    observe = SimpleNamespace(
        tool_use={
            "toolUseId": "observe-1",
            "name": "mac_computer_observe",
            "input": {},
        },
        interrupt=Mock(),
    )
    approval.before_tool(observe)
    observe.interrupt.assert_not_called()

    press = SimpleNamespace(
        tool_use={
            "toolUseId": "press-1",
            "name": "mac_computer_act_on_element",
            "input": {"snapshot_revision": "revision-1", "target_id": "control-1"},
        },
        interrupt=Mock(return_value=None),
        cancel_tool=None,
    )
    approval.before_tool(press)
    press.interrupt.assert_called_once()
    assert press.cancel_tool == "This tool call was not approved."
