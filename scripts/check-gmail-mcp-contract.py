"""Fail when Google's preview Gmail MCP no longer matches FroggyBot's safe contract."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

GMAIL_MCP_ENDPOINT = "https://gmailmcp.googleapis.com/mcp/v1"
ALLOWED_TOOLS = {
    "create_draft",
    "get_draft",
    "get_message",
    "get_thread",
    "list_drafts",
    "list_labels",
    "search_threads",
}
READ_ONLY_TOOLS = ALLOWED_TOOLS - {"create_draft"}


def _catalog() -> list[dict[str, Any]]:
    request = urllib.request.Request(
        GMAIL_MCP_ENDPOINT,
        data=json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        ).encode("utf-8"),
        headers={
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "user-agent": "FroggyBot-provider-contract/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - fixed Google MCP endpoint.
            request, timeout=20
        ) as response:
            value = json.loads(response.read(10_000_001).decode("utf-8"))
    except (OSError, UnicodeError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError("Gmail MCP tools/list could not be read") from exc
    tools = value.get("result", {}).get("tools") if isinstance(value, dict) else None
    if not isinstance(tools, list) or not tools:
        raise RuntimeError("Gmail MCP tools/list returned an invalid catalog")
    return tools


def validate(tools: list[dict[str, Any]]) -> list[str]:
    problems = []
    by_name = {
        item.get("name"): item
        for item in tools
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    missing = sorted(ALLOWED_TOOLS - set(by_name))
    if missing:
        problems.append(f"missing required tools: {', '.join(missing)}")
    for name in sorted(ALLOWED_TOOLS & set(by_name)):
        item = by_name[name]
        annotations = item.get("annotations")
        if not isinstance(item.get("inputSchema"), dict):
            problems.append(f"{name} has no input schema")
        if not isinstance(annotations, dict):
            problems.append(f"{name} has no safety annotations")
            continue
        if annotations.get("destructiveHint") is not False:
            problems.append(f"{name} is no longer explicitly non-destructive")
        if annotations.get("openWorldHint") is not False:
            problems.append(f"{name} unexpectedly has open-world side effects")
        expected_read_only = name in READ_ONLY_TOOLS
        if annotations.get("readOnlyHint") is not expected_read_only:
            problems.append(
                f"{name} read-only annotation changed; expected {expected_read_only}"
            )
    return problems


def main() -> int:
    try:
        tools = _catalog()
        problems = validate(tools)
    except RuntimeError as exc:
        print(f"Gmail MCP contract check failed: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("Gmail MCP contract check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print(
        "Gmail MCP contract is compatible: all seven allowed tools retain their "
        "read/draft-only safety annotations."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
