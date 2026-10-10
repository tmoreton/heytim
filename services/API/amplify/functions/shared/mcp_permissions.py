"""Preserve reviewed MCP permissions across catalog serialization."""
from __future__ import annotations

import re


def anonymous_credential(item: dict | None) -> bool:
    return bool(item and item.get("provider") == "mcp_server"
                and item.get("runtime", {}).get("authType") == "none"
                and isinstance(item.get("secretArn"), str)
                and re.fullmatch(r"anonymous:[a-f0-9]{32}", item["secretArn"]))


def reviewed_binding(binding: dict, value: dict, error: type[Exception]) -> dict:
    if "approvedTools" not in value:
        return binding
    tools = value["approvedTools"]
    if (binding.get("authType") not in {"bearer_token", "none"}
            or not isinstance(tools, dict) or not 1 <= len(tools) <= 100
            or any(not isinstance(k, str) or not 1 <= len(k) <= 128
                   or not isinstance(v, str) or not re.fullmatch(r"[a-f0-9]{64}", v)
                   for k, v in tools.items())):
        raise error("MCP reviewed tools are invalid")
    return {**binding, "approvedTools": tools, "requireActionApproval": True}


def public_mcp_metadata(item: dict) -> dict:
    if not item.get("mcpVerifiedAt"):
        return {"connectionStatus": "saved"}
    return {"connectionStatus": "tested", **{
        key: item[key] for key in ("mcpVerifiedAt", "mcpToolCount", "mcpServerName")
        if key in item
    }}
