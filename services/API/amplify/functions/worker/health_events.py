from __future__ import annotations

import hashlib
import json
import logging
import re
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)
_SAFE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SAFE_SOURCE = re.compile(r"[a-z0-9_.-]{1,64}")


def terminal_error_category(message: object) -> str:
    text = str(message).lower()
    if any(
        term in text for term in ("image generation", "image-generator", "image model")
    ):
        return "image"
    if any(
        term in text
        for term in ("browser", "concurrent connection", "session conflict")
    ):
        return "browser"
    if any(
        term in text for term in ("stopped reporting", "eight-hour limit", "heartbeat")
    ):
        return "stalled"
    if any(
        term in text
        for term in (
            "openrouter",
            "bedrock",
            "provider",
            "model",
            "credential",
            "rate limit",
        )
    ):
        return "provider"
    return "other"


def _terminal_error_code(message: object) -> str:
    if not isinstance(message, dict):
        return (
            "UNEXPECTED_EXCEPTION"
            if isinstance(message, BaseException)
            else "TERMINAL_ERROR"
        )
    value = message.get("code")
    return (
        value
        if isinstance(value, str) and _SAFE_CODE.fullmatch(value)
        else "TERMINAL_ERROR"
    )


def _exception_location(message: object) -> str:
    if not isinstance(message, BaseException) or message.__traceback__ is None:
        return "worker"
    frame = traceback.extract_tb(message.__traceback__)[-1]
    filename = Path(frame.filename).name
    function = re.sub(r"[^A-Za-z0-9_]", "_", frame.name)[:80] or "unknown"
    return f"{filename}:{function}:{max(0, frame.lineno)}"


def terminal_error_event(
    message: object, *, source: str = "worker"
) -> dict[str, object]:
    safe_source = source if _SAFE_SOURCE.fullmatch(source) else "worker"
    event: dict[str, object] = {
        "schema": 1,
        "source": safe_source,
        "category": terminal_error_category(message),
        "code": _terminal_error_code(message),
        "exception": type(message).__name__
        if isinstance(message, BaseException)
        else "TerminalError",
        "location": _exception_location(message),
    }
    fingerprint_input = json.dumps(event, sort_keys=True, separators=(",", ":"))
    event["fingerprint"] = hashlib.sha256(fingerprint_input.encode()).hexdigest()[:24]
    return event


def record_terminal_error(message: object, *, source: str = "worker") -> None:
    # This marker intentionally excludes exception messages, user text, tool
    # arguments, and identifiers. The repair workflow receives only these
    # bounded structural fields.
    logger.error(
        "HEYTIM_TERMINAL_ERROR %s",
        json.dumps(
            terminal_error_event(message, source=source),
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
