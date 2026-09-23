"""Opt-in Laya-assisted Home Assistant route for one grounded Assist entity.

The Mac's model output is untrusted advisory data. This module independently
checks the bot grant, live Assist context, discovered tool schema, and exact
approval before it sends a state-changing MCP call.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp import ClientSession
from mcp.shared.exceptions import McpError
from pydantic import AnyUrl

from .action_approval import APPROVAL_LIFETIME_MINUTES, _proposal
from .capability_contract import tool_bindings
from .home_assistant_decisions import assist_action_catalog, single_entity_request
from .mcp_connections import _home_assistant_access_token, _secure_streamable_http

SNAPSHOT_URI = "homeassistant://assist/context-snapshot"
MAX_SNAPSHOT_CHARS = 100_000
_ENTRY = re.compile(r"^- names: (.+)$")
_FIELD = re.compile(r"^  (domain|state): (.+)$")
_SAFE_NAME = re.compile(r"[\w][\w .'-]{0,79}\Z", re.UNICODE)
_SAFE_STATE = {"on", "off"}
_ROUTE_LABELS = {"turn_on", "turn_off", "read_state"}


def _hint_label(hint: Any) -> str | None:
    if not isinstance(hint, dict) or set(hint) != {
        "selectedLabel",
        "confidence",
        "actionProbability",
        "truncated",
    }:
        return None
    label = hint.get("selectedLabel")
    confidence = hint.get("confidence")
    probability = hint.get("actionProbability")
    if (
        label not in _ROUTE_LABELS
        or type(confidence) not in (int, float)
        or type(probability) not in (int, float)
        or not (0.20 if label == "read_state" else 0.85) <= confidence <= 1
        or not 0.95 <= probability <= 1
        or hint.get("truncated") is not False
    ):
        return None
    return label


def _matching_entity(snapshot: str, request: str, label: str) -> dict | None:
    """Match one complete Assist name, never a substring, area, or floor."""
    if not isinstance(snapshot, str) or len(snapshot) > MAX_SNAPSHOT_CHARS:
        return None
    entries: list[dict] = []
    current: dict | None = None
    for line in snapshot.splitlines():
        start = _ENTRY.fullmatch(line)
        if start:
            current = {"names": start.group(1), "domain": None, "state": None}
            entries.append(current)
            continue
        field = _FIELD.fullmatch(line)
        if field and current is not None:
            current[field.group(1)] = field.group(2)
    matches = []
    for entry in entries:
        domain = entry["domain"]
        if domain not in {"light", "switch"}:
            continue
        state = entry["state"]
        if (
            isinstance(state, str)
            and len(state) >= 2
            and state[0] in {"'", '"'}
            and state[-1] == state[0]
        ):
            state = state[1:-1]
        for name in entry["names"].split(","):
            name = name.strip()
            if not _SAFE_NAME.fullmatch(name):
                continue
            if single_entity_request(request, name) == label:
                matches.append(
                    {"name": name, "domain": domain, "state": state}
                )
    return matches[0] if len(matches) == 1 else None


def _action_tool(tools: list[Any], label: str) -> str | None:
    name = assist_action_catalog(tools).get(label)
    if not name or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", name):
        return None
    matching = [tool for tool in tools if tool.name == name]
    if len(matching) != 1:
        return None
    schema = matching[0].inputSchema
    if not isinstance(schema, dict):
        return None
    properties = schema.get("properties")
    required = schema.get("required", [])
    if (
        not isinstance(properties, dict)
        or not isinstance(properties.get("name"), dict)
        or properties["name"].get("type") != "string"
        or not isinstance(required, list)
        or any(not isinstance(item, str) for item in required)
        or not set(required).issubset({"name"})
    ):
        return None
    return name


def _proposal_for(event_id: str, name: str, arguments: dict) -> dict:
    proposal = _proposal(
        {
            "toolUseId": "ha-fast-"
            + str(uuid.uuid5(uuid.NAMESPACE_URL, f"heytim-ha:{event_id}")),
            "name": name,
            "input": arguments,
        }
    )
    return {
        **proposal,
        "id": str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"heytim-ha:{event_id}:{proposal['digest']}")
        ),
        "expiresAt": (
            datetime.now(UTC) + timedelta(minutes=APPROVAL_LIFETIME_MINUTES)
        ).isoformat(timespec="seconds"),
    }


def _tool_result(result: Any) -> dict | None:
    if getattr(result, "isError", True):
        return None
    content = getattr(result, "content", None)
    if not isinstance(content, list) or len(content) != 1:
        return None
    raw = getattr(content[0], "text", None)
    if not isinstance(raw, str) or len(raw) > 20_000:
        return None
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) and body.get("success") is True else None


async def _snapshot(session: ClientSession, tools: list[Any]) -> str | None:
    try:
        resources = await session.list_resources()
        if any(str(item.uri) == SNAPSHOT_URI for item in resources.resources):
            result = await session.read_resource(AnyUrl(SNAPSHOT_URI))
            if len(result.contents) == 1:
                text = getattr(result.contents[0], "text", None)
                if isinstance(text, str):
                    return text
    except McpError:
        # Older Home Assistant versions expose the same context only as a tool.
        pass
    name = assist_action_catalog(tools).get("read_state")
    if not name or not name.endswith("GetLiveContext"):
        return None
    result = _tool_result(await session.call_tool(name, {}))
    return (
        result.get("result")
        if result and isinstance(result.get("result"), str)
        else None
    )


async def maybe_route_home_assistant(payload: dict, request: str) -> dict | None:
    """Return a final text/approval control or None to use the normal bot."""
    hint = payload.get("homeAssistantHint")
    label = _hint_label(hint)
    if label is None or payload.get("group") is not None or payload.get("continuation"):
        return None
    bot = payload.get("bot")
    if not isinstance(bot, dict) or not isinstance(request, str):
        return None
    bindings = [
        binding
        for binding in tool_bindings(bot)
        if binding.get("authType") == "home_assistant_token"
        and any(
            item.get("id") == binding["id"] and item.get("risk") == "interactive"
            for item in bot.get("tools", [])
        )
    ]
    if len(bindings) != 1:
        return None
    memory = payload.get("memory")
    event_id = memory.get("eventId") if isinstance(memory, dict) else None
    if not isinstance(event_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", event_id):
        return None
    binding = bindings[0]
    token = _home_assistant_access_token(binding)
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        _secure_streamable_http(binding["endpoint"], headers) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        tools = []
        cursor = None
        for _ in range(10):
            page = await session.list_tools(cursor=cursor)
            tools.extend(page.tools)
            cursor = page.nextCursor
            if not cursor:
                break
        else:
            return None
        snapshot = await _snapshot(session, tools)
        entity = _matching_entity(snapshot, request, label) if snapshot else None
        if not entity:
            return None
        if label == "read_state":
            if entity["state"] not in _SAFE_STATE:
                return None
            return {
                "text": f"Home Assistant shows {entity['name']} is {entity['state']}."
            }
        tool_name = _action_tool(tools, label)
        if not tool_name:
            return None
        proposal = _proposal_for(event_id, tool_name, {"name": entity["name"]})
        decision = payload.get("actionApproval")
        if decision is None:
            return {"pendingApproval": proposal}
        if not isinstance(decision, dict) or any(
            decision.get(key) != proposal[key] for key in ("id", "digest", "toolUseId")
        ):
            return {
                "terminalError": {
                    "code": "HA_APPROVAL_CHANGED",
                    "message": "The Home Assistant action changed after approval. No command was sent.",
                }
            }
        result = _tool_result(
            await session.call_tool(tool_name, {"name": entity["name"]})
        )
        if result is None:
            return {
                "terminalError": {
                    "code": "HA_ACTION_UNCONFIRMED",
                    "message": "Home Assistant did not confirm the action. Check the device before trying again.",
                }
            }
        desired = "on" if label == "turn_on" else "off"
        refreshed = await _snapshot(session, tools)
        observed = _matching_entity(refreshed, request, label) if refreshed else None
        if observed and observed["state"] == desired:
            return {
                "text": f"{entity['name']} is {desired}, confirmed by Home Assistant."
            }
        return {
            "text": (
                f"Home Assistant accepted the request to turn {desired} {entity['name']}, "
                "but I could not confirm its new state."
            )
        }
