from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from heytim_runtime.action_approval import ActionApproval, _proposal, pending_approval
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
