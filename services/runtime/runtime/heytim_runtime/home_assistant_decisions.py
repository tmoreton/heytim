"""Grounded, non-executing Home Assistant action candidates for Laya evaluation.

This module never calls MCP tools. A model answer is only an advisory result;
production execution also needs fresh entity resolution, schema validation,
the bot's grant, exact-action approval, and a persisted result.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_ACTION_TOOL_NAMES = {
    "turn_on": ("HassTurnOn",),
    "turn_off": ("HassTurnOff",),
    "read_state": ("HassGetState", "GetLiveContext"),
}
_ENTITY_ID = re.compile(r"[a-z][a-z0-9_]*\.[a-z0-9_]+\Z")


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


def single_entity_request(request: str, entity_alias: str) -> str | None:
    """Recognize only one explicit, present-tense command to a known alias."""
    if (
        not isinstance(request, str) or len(request) > 180 or "\n" in request
        or any(mark in request for mark in ('"', "“", "”", ";"))
        or not isinstance(entity_alias, str) or not entity_alias.strip()
    ):
        return None
    alias = re.escape(entity_alias.strip())
    prefix = r"(?:please\s+)?"
    for label, pattern in (
        ("turn_on", rf"{prefix}turn\s+on\s+(?:the\s+)?{alias}[.!]?"),
        ("turn_off", rf"{prefix}turn\s+off\s+(?:the\s+)?{alias}[.!]?"),
        ("read_state", rf"is\s+(?:the\s+)?{alias}\s+on\?"),
    ):
        if re.fullmatch(pattern, request.strip(), flags=re.IGNORECASE):
            return label
    return None


def laya_advisory_candidate(
    *, request: str, entity_alias: str, entity_id: str, exposed_to_assist: bool,
    discovered_tools: Iterable[Any], selected_label: str, confidence: float,
    action_probability: float, truncated: bool,
) -> dict[str, str] | None:
    """Score a Laya answer against hard gates; never return executable arguments."""
    # The caller must resolve the alias and ID as one fresh, trusted pair from
    # Assist context; this function deliberately does not infer the mapping.
    if not exposed_to_assist or not isinstance(entity_id, str) or not _ENTITY_ID.fullmatch(entity_id):
        return None
    expected = single_entity_request(request, entity_alias)
    if expected is None or selected_label != expected or truncated:
        return None
    if confidence < 0.85 or action_probability < 0.95:
        return None
    tool_name = assist_action_catalog(discovered_tools).get(expected)
    if tool_name is None:
        return None
    return {"abstractAction": expected, "discoveredTool": tool_name, "entityId": entity_id}
