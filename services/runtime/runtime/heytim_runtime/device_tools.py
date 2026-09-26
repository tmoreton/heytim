"""Model-visible tools that execute on an authorized HeyTim Apple client."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from strands import tool
from strands.agent.agent_result import AgentResult
from strands.types.tools import ToolContext

MAX_DEVICE_INPUT_BYTES = 8_000
MAX_DEVICE_RESULT_BYTES = 64_000
DEVICE_CALL_LIFETIME_MINUTES = 5


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "json": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        }
    }


DEVICE_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "mac_computer_observe": {
        "platform": "macos",
        "description": (
            "Inspect the focused window of one running Mac app through Accessibility. "
            "Returns an ephemeral snapshot revision and semantic target IDs. Use those "
            "IDs for later actions; never guess coordinates or reuse an old revision."
        ),
        "inputSchema": _schema(
            {
                "application": {
                    "type": "string",
                    "maxLength": 120,
                    "description": "App name or bundle identifier. Omit for the frontmost app.",
                },
                "include_ocr": {
                    "type": "boolean",
                    "description": "Also run local OCR on the selected app window when semantic labels are insufficient.",
                },
            }
        ),
    },
    "mac_computer_act_on_element": {
        "platform": "macos",
        "description": (
            "Perform one supported semantic action on a Mac control from a fresh "
            "mac_computer_observe result. Use the control's supportedActions value; "
            "The client rejects stale revisions, changed windows, secure fields, and "
            "high-impact controls such as purchase, send, publish, delete, or credential actions."
        ),
        "inputSchema": _schema(
            {
                "snapshot_revision": {"type": "string", "maxLength": 64},
                "target_id": {"type": "string", "maxLength": 64},
                "action": {
                    "type": "string",
                    "enum": ["press", "increment", "decrement", "show_menu"],
                    "description": "Semantic action to perform. Defaults to press.",
                },
            },
            ["snapshot_revision", "target_id"],
        ),
    },
    "mac_computer_type_into_element": {
        "platform": "macos",
        "description": (
            "Replace the value of one non-secure editable field from a fresh Mac "
            "snapshot. The client revalidates the app, window, target, and revision."
        ),
        "inputSchema": _schema(
            {
                "snapshot_revision": {"type": "string", "maxLength": 64},
                "target_id": {"type": "string", "maxLength": 64},
                "text": {"type": "string", "maxLength": 4_000},
            },
            ["snapshot_revision", "target_id", "text"],
        ),
    },
    "mac_computer_wait_for_state": {
        "platform": "macos",
        "description": (
            "Wait briefly and observe the same Mac app again. Use this after an action "
            "to verify the resulting UI state instead of assuming success."
        ),
        "inputSchema": _schema(
            {
                "snapshot_revision": {"type": "string", "maxLength": 64},
                "seconds": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            ["snapshot_revision"],
        ),
    },
    "mac_computer_scroll": {
        "platform": "macos",
        "description": (
            "Scroll one semantic container from a fresh Mac snapshot. The client "
            "revalidates the app, window, target, and revision, pauses if the user "
            "takes over, and observes the resulting state."
        ),
        "inputSchema": _schema(
            {
                "snapshot_revision": {"type": "string", "maxLength": 64},
                "target_id": {"type": "string", "maxLength": 64},
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                },
                "amount": {
                    "type": "string",
                    "enum": ["line", "page"],
                },
            },
            ["snapshot_revision", "target_id", "direction"],
        ),
    },
    "apple_health_activity_summary": {
        "platform": "ios",
        "description": (
            "Read on-device Apple Health activity-ring summaries for a bounded recent "
            "period. Returns daily aggregates only, never routes or individual sensor samples."
        ),
        "inputSchema": _schema(
            {"days": {"type": "integer", "minimum": 1, "maximum": 31}}
        ),
    },
    "apple_health_workouts": {
        "platform": "ios",
        "description": (
            "Read a bounded list of recent workouts from Apple Health without routes, "
            "heart-rate samples, clinical records, or other sensitive sample streams."
        ),
        "inputSchema": _schema(
            {
                "days": {"type": "integer", "minimum": 1, "maximum": 90},
                "activity": {
                    "type": "string",
                    "enum": ["all", "running", "walking", "cycling", "swimming"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            }
        ),
    },
    "apple_health_running_totals": {
        "platform": "ios",
        "description": (
            "Aggregate recent Apple Health running workouts into totals and weekly "
            "trends on the device. Does not return route or sensor samples."
        ),
        "inputSchema": _schema(
            {"days": {"type": "integer", "minimum": 1, "maximum": 180}}
        ),
    },
    "apple_health_steps": {
        "platform": "ios",
        "description": (
            "Read daily step-count aggregates from Apple Health for a bounded recent period."
        ),
        "inputSchema": _schema(
            {"days": {"type": "integer", "minimum": 1, "maximum": 31}}
        ),
    },
}


def _encoded_size(value: Any) -> int:
    try:
        return len(
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Device tool data must be JSON-compatible") from exc


def _request(tool_use: dict, *, platform: str, tool_id: str) -> dict:
    name = tool_use.get("name")
    arguments = tool_use.get("input")
    tool_use_id = tool_use.get("toolUseId")
    if (
        not isinstance(name, str)
        or name not in DEVICE_TOOL_SPECS
        or not isinstance(arguments, dict)
        or not isinstance(tool_use_id, str)
        or not tool_use_id
    ):
        raise ValueError("Device tool identity is invalid")
    if _encoded_size(arguments) > MAX_DEVICE_INPUT_BYTES:
        raise ValueError("Device tool input is too large")
    digest = hashlib.sha256(
        json.dumps(
            [tool_use_id, name, arguments, platform, tool_id],
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "toolUseId": tool_use_id,
        "toolName": name,
        "input": arguments,
        "platform": platform,
        "toolId": tool_id,
        "digest": digest,
    }


def _device_result(proposal: dict, response: Any) -> Any:
    if (
        not isinstance(response, dict)
        or response.get("digest") != proposal["digest"]
        or response.get("toolUseId") != proposal["toolUseId"]
        or response.get("status") not in {"success", "error"}
    ):
        raise ValueError("Device result does not match the requested tool call")
    if response["status"] == "error":
        message = response.get("error")
        if not isinstance(message, str) or not message.strip() or len(message) > 1_000:
            raise ValueError("Device error is invalid")
        raise RuntimeError(message.strip())
    result = response.get("result")
    if _encoded_size(result) > MAX_DEVICE_RESULT_BYTES:
        raise ValueError("Device result is too large")
    return result


def _device_tool(operation: str, platform: str, tool_id: str) -> Any:
    spec = DEVICE_TOOL_SPECS[operation]

    @tool(
        name=operation,
        description=spec["description"],
        inputSchema=spec["inputSchema"],
        context=True,
    )
    def invoke_device(tool_context: ToolContext, **arguments) -> Any:
        # Strands supplies the validated public arguments in tool_use. Use
        # those exact bytes for the digest rather than closure kwargs.
        proposal = _request(
            tool_context.tool_use,
            platform=platform,
            tool_id=tool_id,
        )
        response = tool_context.interrupt("heytim_device_call", reason=proposal)
        return _device_result(proposal, response)

    return invoke_device


def device_tools(bindings: list[dict]) -> list[Any]:
    return [
        _device_tool(operation, binding["platform"], binding["id"])
        for binding in bindings
        if binding.get("kind") == "device"
        for operation in binding["operations"]
    ]


def has_device_tools(payload: dict) -> bool:
    return any(
        isinstance(item, dict)
        and isinstance(item.get("runtime"), dict)
        and item["runtime"].get("kind") == "device"
        for item in payload.get("bot", {}).get("tools", [])
    )


def pending_device_call(result: AgentResult) -> dict | None:
    if getattr(result, "stop_reason", None) != "interrupt":
        return None
    interrupts = getattr(result, "interrupts", None) or []
    matching = [item for item in interrupts if item.name == "heytim_device_call"]
    if not matching:
        return None
    if len(interrupts) != 1 or len(matching) != 1:
        raise ValueError("Unexpected runtime interrupt")
    proposal = matching[0].reason
    if not isinstance(proposal, dict) or set(proposal) != {
        "toolUseId",
        "toolName",
        "input",
        "platform",
        "toolId",
        "digest",
    }:
        raise ValueError("Device proposal is invalid")
    if proposal != _request(
        {
            "toolUseId": proposal.get("toolUseId"),
            "name": proposal.get("toolName"),
            "input": proposal.get("input"),
        },
        platform=proposal.get("platform"),
        tool_id=proposal.get("toolId"),
    ):
        raise ValueError("Device proposal digest is invalid")
    return {
        **proposal,
        "id": matching[0].id,
        "expiresAt": (
            datetime.now(UTC) + timedelta(minutes=DEVICE_CALL_LIFETIME_MINUTES)
        ).isoformat(timespec="seconds"),
    }


def validated_device_resume(value: Any) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("Device response is invalid")
    keys = set(value)
    if keys not in (
        {"id", "digest", "toolUseId", "status", "result"},
        {"id", "digest", "toolUseId", "status", "error"},
    ):
        raise ValueError("Device response is invalid")
    if not all(
        isinstance(value.get(key), str) and value[key]
        for key in ("id", "digest", "toolUseId", "status")
    ):
        raise ValueError("Device response identity is invalid")
    if value["status"] == "success" and "result" in value:
        if _encoded_size(value["result"]) > MAX_DEVICE_RESULT_BYTES:
            raise ValueError("Device result is too large")
    elif value["status"] == "error" and isinstance(value.get("error"), str):
        if not value["error"].strip() or len(value["error"]) > 1_000:
            raise ValueError("Device error is invalid")
    else:
        raise ValueError("Device response outcome is invalid")
    return value


__all__ = [
    "DEVICE_TOOL_SPECS",
    "device_tools",
    "has_device_tools",
    "pending_device_call",
    "validated_device_resume",
]
