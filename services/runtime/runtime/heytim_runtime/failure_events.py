from __future__ import annotations

import hashlib
import json
import logging
import re
import traceback
from pathlib import Path

_SAFE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


def _error_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _category(chain: list[BaseException]) -> str:
    names = " ".join(type(item).__name__.lower() for item in chain)
    detail = " ".join(str(item).lower() for item in chain)
    if "image" in names or "image generation" in detail:
        return "image"
    if "browser" in names or "browser" in detail:
        return "browser"
    if "openrouter" in names or any(
        term in detail for term in ("openrouter", "rate limit", "in_flight_budget")
    ):
        return "provider"
    return "other"


def _location(error: BaseException) -> str:
    if error.__traceback__ is None:
        return "runtime"
    frame = traceback.extract_tb(error.__traceback__)[-1]
    filename = Path(frame.filename).name
    function = re.sub(r"[^A-Za-z0-9_]", "_", frame.name)[:80] or "unknown"
    return f"{filename}:{function}:{max(0, frame.lineno)}"


def runtime_failure_event(error: BaseException) -> dict[str, object]:
    chain = _error_chain(error)
    code = getattr(error, "code", "UNEXPECTED_EXCEPTION")
    if not isinstance(code, str) or not _SAFE_CODE.fullmatch(code):
        code = "UNEXPECTED_EXCEPTION"
    event: dict[str, object] = {
        "schema": 1,
        "source": "agentcore-runtime",
        "category": _category(chain),
        "code": code,
        "exception": type(error).__name__,
        "location": _location(error),
    }
    fingerprint_input = json.dumps(event, sort_keys=True, separators=(",", ":"))
    event["fingerprint"] = hashlib.sha256(fingerprint_input.encode()).hexdigest()[:24]
    return event


def record_runtime_failure(logger: logging.Logger, error: BaseException) -> None:
    # Never put the exception message, prompt, tool input, or user identity in
    # the machine-triggering event. The normal traceback remains in the
    # encrypted production log group for human diagnosis.
    logger.error(
        "HEYTIM_TERMINAL_ERROR %s",
        json.dumps(runtime_failure_event(error), sort_keys=True, separators=(",", ":")),
    )


__all__ = ["record_runtime_failure", "runtime_failure_event"]
