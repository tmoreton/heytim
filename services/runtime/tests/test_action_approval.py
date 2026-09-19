from __future__ import annotations

from types import SimpleNamespace

import pytest

from heytim_runtime.action_approval import _proposal, pending_approval
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
