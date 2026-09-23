"""Read-only discovery of schema-bearing Home Assistant Assist MCP tools."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_ACTION_TOOL_NAMES = {
    "turn_on": ("HassTurnOn",),
    "turn_off": ("HassTurnOff",),
    "read_state": ("HassGetState", "GetLiveContext"),
}


def assist_action_catalog(tools: Iterable[Any]) -> dict[str, str]:
    """Map only discovered, schema-bearing Assist tools to abstract labels."""
    discovered: dict[str, dict[str, list[str]]] = {
        label: {expected: [] for expected in expected_names}
        for label, expected_names in _ACTION_TOOL_NAMES.items()
    }
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)
        schema = (
            tool.get("inputSchema") if isinstance(tool, dict)
            else getattr(tool, "inputSchema", None)
        )
        if not isinstance(name, str) or not isinstance(schema, dict):
            continue
        if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
            continue
        for label, expected_names in _ACTION_TOOL_NAMES.items():
            for expected_name in expected_names:
                if name == expected_name or name.endswith(f"__{expected_name}"):
                    discovered[label][expected_name].append(name)
    result = {}
    for label, expected_names in _ACTION_TOOL_NAMES.items():
        for expected_name in expected_names:
            names = discovered[label][expected_name]
            if len(names) == 1:
                result[label] = names[0]
                break
            if len(names) > 1:
                # Duplicate aliases for the preferred tool are ambiguous.
                break
    return result
