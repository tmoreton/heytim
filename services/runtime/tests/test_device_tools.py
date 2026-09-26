from __future__ import annotations

from types import SimpleNamespace

import pytest

from heytim_runtime.device_tools import (
    DEVICE_TOOL_SPECS,
    _device_result,
    _request,
    has_device_tools,
    pending_device_call,
    validated_device_resume,
)
from heytim_runtime.runtime_jobs import RunState


def _proposal(arguments: dict | None = None) -> dict:
    return _request(
        {
            "toolUseId": "tool-use-1",
            "name": "apple_health_steps",
            "input": arguments or {"days": 7},
        },
        platform="ios",
        tool_id="apple_health",
    )


def test_device_digest_binds_tool_identity_platform_and_exact_arguments() -> None:
    first = _proposal({"days": 7})
    same = _proposal({"days": 7})
    changed = _proposal({"days": 8})
    other_platform = _request(
        {
            "toolUseId": "tool-use-1",
            "name": "apple_health_steps",
            "input": {"days": 7},
        },
        platform="macos",
        tool_id="apple_health",
    )

    assert first["digest"] == same["digest"]
    assert first["digest"] != changed["digest"]
    assert first["digest"] != other_platform["digest"]


def test_device_result_must_match_the_exact_interrupted_call() -> None:
    proposal = _proposal()
    response = {
        "digest": proposal["digest"],
        "toolUseId": proposal["toolUseId"],
        "status": "success",
        "result": {"days": [{"date": "2026-09-25", "steps": 8_000}]},
    }
    assert _device_result(proposal, response) == response["result"]

    with pytest.raises(ValueError, match="does not match"):
        _device_result(proposal, {**response, "digest": "0" * 64})
    with pytest.raises(RuntimeError, match="permission was revoked"):
        _device_result(
            proposal,
            {
                "digest": proposal["digest"],
                "toolUseId": proposal["toolUseId"],
                "status": "error",
                "error": "Health permission was revoked",
            },
        )


def test_only_one_well_formed_device_interrupt_can_pause_a_turn() -> None:
    proposal = _proposal()
    interrupt = SimpleNamespace(
        id="interrupt-1", name="heytim_device_call", reason=proposal
    )
    exposed = pending_device_call(
        SimpleNamespace(stop_reason="interrupt", interrupts=[interrupt])
    )
    assert exposed["id"] == "interrupt-1"
    assert exposed["toolId"] == "apple_health"
    assert exposed["input"] == {"days": 7}

    interrupt.reason = {**proposal, "digest": "0" * 64}
    with pytest.raises(ValueError, match="digest"):
        pending_device_call(
            SimpleNamespace(stop_reason="interrupt", interrupts=[interrupt])
        )


def test_resume_payload_is_closed_and_size_bounded() -> None:
    proposal = _proposal()
    value = validated_device_resume(
        {
            "id": "interrupt-1",
            "digest": proposal["digest"],
            "toolUseId": proposal["toolUseId"],
            "status": "success",
            "result": {"steps": 8_000},
        }
    )
    assert value and value["result"] == {"steps": 8_000}
    with pytest.raises(ValueError, match="response"):
        validated_device_resume({**value, "unexpected": True})
    with pytest.raises(ValueError, match="too large"):
        validated_device_resume({**value, "result": "x" * 65_000})


def test_device_tools_are_detected_and_background_jobs_remain_paused() -> None:
    payload = {
        "bot": {
            "tools": [
                {
                    "id": "apple_health",
                    "runtime": {"kind": "device", "platform": "ios"},
                }
            ]
        }
    }
    assert has_device_tools(payload)
    state = RunState("2026-09-25T12:00:00+00:00")
    state.observe({"heytimControl": {"pendingDeviceCall": {"id": "interrupt-1"}}})
    state.finish()
    assert state.value["pendingDeviceCall"] == {"id": "interrupt-1"}
    assert "terminalError" not in state.value


def test_mac_computer_v2_operations_are_closed_and_bounded() -> None:
    action = DEVICE_TOOL_SPECS["mac_computer_act_on_element"]["inputSchema"]["json"]
    scroll = DEVICE_TOOL_SPECS["mac_computer_scroll"]["inputSchema"]["json"]

    assert action["additionalProperties"] is False
    assert action["properties"]["action"]["enum"] == [
        "press",
        "increment",
        "decrement",
        "show_menu",
    ]
    assert scroll["additionalProperties"] is False
    assert scroll["properties"]["direction"]["enum"] == [
        "up",
        "down",
        "left",
        "right",
    ]
    assert scroll["properties"]["amount"]["enum"] == ["line", "page"]
