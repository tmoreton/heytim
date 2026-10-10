"""Validate and enforce the reviewed executable surface of custom MCP servers."""
from __future__ import annotations

import hashlib
import json
import re


def reviewed_binding(value: dict) -> dict:
    if "approvedTools" not in value:
        return {}
    tools = value["approvedTools"]
    if (value.get("authType", "none") not in {"bearer_token", "none"}
            or not isinstance(tools, dict) or not 1 <= len(tools) <= 100
            or any(not isinstance(k, str) or not 1 <= len(k) <= 128
                   or not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v)
                   for k, v in tools.items())):
        raise ValueError("MCP reviewed tools are invalid")
    return {"approvedTools": tools, "requireActionApproval": True}


def tool_digest(tool: dict) -> str:
    contract = {key: tool[key] for key in (
        "name", "inputSchema", "outputSchema", "annotations", "execution"
    ) if tool.get(key) is not None}
    return hashlib.sha256(json.dumps(
        contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()).hexdigest()
