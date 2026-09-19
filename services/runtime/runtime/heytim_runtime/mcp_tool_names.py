from __future__ import annotations

import hashlib

MAX_TOOL_NAME_CHARS = 64


def _bounded_tool_name(connection_id: str, remote_name: str) -> str:
    prefix = f"c{hashlib.sha256(connection_id.encode()).hexdigest()[:10]}"
    candidate = f"{prefix}_{remote_name}"
    if len(candidate) <= MAX_TOOL_NAME_CHARS:
        return candidate
    suffix = hashlib.sha256(candidate.encode()).hexdigest()[:10]
    return f"{candidate[: MAX_TOOL_NAME_CHARS - len(suffix) - 1]}_{suffix}"


