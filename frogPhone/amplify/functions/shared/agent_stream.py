from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

ProgressCallback = Callable[[list[str]], None]


def _clean_step(value: str) -> str:
    return " ".join(value.split()).strip()[:600]


def _tool_step(tool_name: str) -> str:
    friendly_name = tool_name.replace("_", " ").replace("-", " ").strip()
    return f"Using {friendly_name}" if friendly_name else "Using a tool"


def _event_payload(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    event = value.get("event", value)
    return event if isinstance(event, dict) else {}


def _parse_line(raw_line: Any) -> dict:
    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
    if line.startswith("data:"):
        line = line[5:].strip()
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return {}
    if isinstance(value, dict) and isinstance(value.get("data"), str):
        try:
            value = json.loads(value["data"])
        except json.JSONDecodeError:
            return {}
    return _event_payload(value)


def read_agent_stream(lines: Iterable[Any], on_progress: ProgressCallback | None = None) -> str:
    """Return only the final assistant message and emit completed tool-use narration."""
    progress: list[str] = []
    message_chunks: list[str] = []
    fallback_chunks: list[str] = []
    tool_names: list[str] = []
    final_text = ""

    for raw_line in lines:
        if not raw_line:
            continue
        event = _parse_line(raw_line)
        if not event:
            continue

        if "messageStart" in event:
            message_chunks = []
            tool_names = []

        block_start = event.get("contentBlockStart", {})
        start = block_start.get("start", {}) if isinstance(block_start, dict) else {}
        tool_use = start.get("toolUse", {}) if isinstance(start, dict) else {}
        if isinstance(tool_use, dict) and isinstance(tool_use.get("name"), str):
            tool_names.append(tool_use["name"])

        block_delta = event.get("contentBlockDelta", {})
        delta = block_delta.get("delta", {}) if isinstance(block_delta, dict) else {}
        text = delta.get("text") if isinstance(delta, dict) else None
        if isinstance(text, str):
            message_chunks.append(text)
            fallback_chunks.append(text)

        message_stop = event.get("messageStop")
        if not isinstance(message_stop, dict):
            continue
        message_text = "".join(message_chunks).strip()
        stop_reason = message_stop.get("stopReason")
        if stop_reason == "tool_use":
            step = _clean_step(message_text)
            if not step and tool_names:
                step = _tool_step(tool_names[-1])
            if step and (not progress or progress[-1] != step):
                progress.append(step)
                progress = progress[-12:]
                if on_progress:
                    on_progress(list(progress))
        elif message_text:
            final_text = message_text
        message_chunks = []
        tool_names = []

    result = final_text.strip() or "".join(message_chunks).strip()
    if not result:
        result = "".join(fallback_chunks).strip()
    if not result:
        raise ValueError("AgentCore returned no assistant text")
    return result
