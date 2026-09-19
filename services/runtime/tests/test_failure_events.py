from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

from heytim_runtime.failure_events import record_runtime_failure, runtime_failure_event


def _failure(message: str) -> RuntimeError:
    try:
        raise RuntimeError(message)
    except RuntimeError as error:
        return error


def test_runtime_failure_event_excludes_raw_exception_text() -> None:
    first = runtime_failure_event(_failure("private prompt one"))
    second = runtime_failure_event(_failure("private prompt two"))

    assert first == second
    assert first["exception"] == "RuntimeError"
    assert first["location"].startswith("test_failure_events.py:")
    assert "private" not in json.dumps(first)


def test_runtime_failure_marker_contains_only_sanitized_json() -> None:
    logger = MagicMock(spec=logging.Logger)
    record_runtime_failure(logger, _failure("secret-bearing failure"))

    rendered = json.dumps(logger.error.call_args.args)
    assert "HEYTIM_TERMINAL_ERROR" in rendered
    assert "secret-bearing" not in rendered
