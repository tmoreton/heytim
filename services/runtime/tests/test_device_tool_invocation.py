from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from heytim_runtime.device_tools import _request, device_tools

VALID_CALLS = [
    ("mac_terminal", "mac_terminal_list_sessions", {}),
    ("mac_terminal", "mac_terminal_read_session", {"sessionId": "tab-1"}),
    ("mac_terminal", "mac_terminal_read_session", {
        "sessionId": "tab-1", "maxCharacters": 20_000,
    }),
    ("mac_terminal", "mac_terminal_execute_command", {
        "sessionId": "tab-1", "revision": "revision-1", "command": "pwd",
    }),
    ("mac_terminal", "mac_terminal_execute_command", {
        "sessionId": "tab-1", "revision": "revision-1", "command": "pwd", "waitSeconds": 0,
    }),
    ("mac_computer", "mac_computer_observe", {}),
    ("mac_computer", "mac_computer_observe", {
        "application": "Terminal", "include_ocr": True,
    }),
    ("mac_computer", "mac_computer_act_on_element", {
        "snapshot_revision": "snapshot-1", "target_id": "target-1", "action": "press",
    }),
    ("mac_computer", "mac_computer_type_into_element", {
        "snapshot_revision": "snapshot-1", "target_id": "target-1", "text": "hello",
    }),
    ("mac_computer", "mac_computer_wait_for_state", {"snapshot_revision": "snapshot-1"}),
    ("mac_computer", "mac_computer_scroll", {
        "snapshot_revision": "snapshot-1", "target_id": "target-1", "direction": "down",
        "amount": "page",
    }),
]


def _tool(tool_id: str, operation: str):
    return device_tools([{
        "id": tool_id, "kind": "device", "platform": "macos", "operations": [operation],
    }])[0]


def _stream(tool, tool_use: dict, agent: SimpleNamespace) -> list:
    async def collect() -> list:
        # Exercise the SDK's signature validation, context injection, and result
        # handling, rather than calling the decorated Python function directly.
        return [event async for event in tool.stream(tool_use, {"agent": agent})]

    return asyncio.run(collect())


@pytest.mark.parametrize("tool_id,operation,arguments", VALID_CALLS)
def test_flat_device_input_interrupts_and_resumes_through_strands(
    tool_id: str, operation: str, arguments: dict,
) -> None:
    tool = _tool(tool_id, operation)
    tool_use = {"toolUseId": "device-call-1", "name": operation, "input": arguments}
    agent = SimpleNamespace(_interrupt_state=SimpleNamespace(interrupts={}))

    events = _stream(tool, tool_use, agent)

    assert len(events) == 1
    assert "tool_interrupt_event" in events[0], events[0]
    interrupt = events[0].interrupts[0]
    assert interrupt.name == "heytim_device_call"
    assert interrupt.reason == _request(tool_use, platform="macos", tool_id=tool_id)
    # Optional defaults and SDK coercions must not change the signed proposal.
    assert interrupt.reason["input"] is arguments
    result = {"verified": True}
    interrupt.response = {
        "digest": interrupt.reason["digest"], "toolUseId": "device-call-1",
        "status": "success", "result": result,
    }

    resumed = _stream(tool, tool_use, agent)

    assert len(resumed) == 1
    assert resumed[0]["tool_result"]["toolUseId"] == "device-call-1"
    assert resumed[0]["tool_result"]["status"] == "success"
    assert json.loads(resumed[0]["tool_result"]["content"][0]["text"]) == result
    assert len(agent._interrupt_state.interrupts) == 1


@pytest.mark.parametrize("tool_id,operation,arguments", [
    ("mac_terminal", "mac_terminal_list_sessions", {"arguments": {}}),
    ("mac_terminal", "mac_terminal_read_session", {}),
    ("mac_terminal", "mac_terminal_read_session", {"sessionId": "tab-1", "maxCharacters": 999}),
    ("mac_terminal", "mac_terminal_read_session", {"sessionId": "tab-1", "maxCharacters": "12000"}),
    ("mac_terminal", "mac_terminal_execute_command", {"sessionId": "tab-1", "command": "pwd"}),
    ("mac_terminal", "mac_terminal_execute_command", {
        "sessionId": "tab-1", "revision": "revision-1", "command": "pwd\nwhoami",
    }),
    ("mac_terminal", "mac_terminal_execute_command", {
        "sessionId": "tab-1", "revision": "revision-1", "command": "pwd\x03",
    }),
    ("mac_terminal", "mac_terminal_execute_command", {
        "sessionId": "tab-1", "revision": "revision-1", "command": "pwd\u2028whoami",
    }),
    ("mac_terminal", "mac_terminal_execute_command", {
        "sessionId": "tab-1", "revision": "revision-1", "command": "pwd", "waitSeconds": 11,
    }),
    ("mac_computer", "mac_computer_observe", {"include_ocr": "true"}),
    ("mac_computer", "mac_computer_act_on_element", {
        "snapshot_revision": "snapshot-1", "target_id": "target-1", "action": "delete",
    }),
    ("mac_computer", "mac_computer_type_into_element", {
        "snapshot_revision": "snapshot-1", "target_id": "target-1", "text": "x" * 4_001,
    }),
    ("mac_computer", "mac_computer_wait_for_state", {
        "snapshot_revision": "snapshot-1", "seconds": True,
    }),
    ("mac_computer", "mac_computer_scroll", {
        "snapshot_revision": "snapshot-1", "target_id": "target-1", "direction": "diagonal",
    }),
])
def test_invalid_device_input_is_rejected_before_interrupt(
    tool_id: str, operation: str, arguments: dict,
) -> None:
    tool_use = {"toolUseId": "invalid-call-1", "name": operation, "input": arguments}
    agent = SimpleNamespace(_interrupt_state=SimpleNamespace(interrupts={}))

    events = _stream(_tool(tool_id, operation), tool_use, agent)

    assert len(events) == 1
    assert events[0]["tool_result"]["status"] == "error"
    assert "Invalid device tool input" in events[0]["tool_result"]["content"][0]["text"]
    assert agent._interrupt_state.interrupts == {}
