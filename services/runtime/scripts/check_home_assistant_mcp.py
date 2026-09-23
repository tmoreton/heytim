"""Read-only Home Assistant Assist MCP handshake and tool discovery.

Run with HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN in the environment. The
token is never printed. This script does not call any Home Assistant tool.
"""

from __future__ import annotations

import asyncio
import os
import sys
from urllib.parse import urlsplit, urlunsplit

import httpx
from mcp import ClientSession
from mcp.shared.exceptions import McpError

from heytim_runtime.mcp_connections import _secure_streamable_http, _validated_endpoint
from heytim_runtime.home_assistant_decisions import assist_action_catalog


def assist_capabilities(names: set[str]) -> dict[str, bool]:
    """Report only known Assist capabilities; never infer a callable tool name."""
    def has_tool(expected: str) -> bool:
        return expected in names or any(
            name.endswith(f"__{expected}") for name in names
        )

    return {
        "read current state": has_tool("GetLiveContext") or has_tool("HassGetState"),
        "turn on": has_tool("HassTurnOn"),
        "turn off": has_tool("HassTurnOff"),
    }


def assist_endpoint(instance_url: str) -> str:
    parsed = urlsplit(instance_url.strip())
    if parsed.path.rstrip("/") not in {"", "/api/mcp", "/api/mcp/assist"}:
        raise ValueError("Home Assistant URL must be the instance or Assist MCP endpoint")
    if parsed.query or parsed.fragment:
        raise ValueError("Home Assistant URL cannot contain a query or fragment")
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, "/api/mcp/assist", "", ""))
    return _validated_endpoint(endpoint)


async def check(endpoint: str, token: str) -> None:
    async with _secure_streamable_http(
        endpoint, {"Authorization": f"Bearer {token}"}
    ) as streams, ClientSession(streams[0], streams[1]) as session:
        await session.initialize()
        names: set[str] = set()
        tools = []
        cursor: str | None = None
        for _ in range(10):
            page = await session.list_tools(cursor=cursor)
            names.update(tool.name for tool in page.tools)
            tools.extend(page.tools)
            cursor = page.nextCursor
            if not cursor:
                break
        else:
            raise ValueError("Assist MCP tool listing exceeded ten pages")
        print(f"Assist MCP handshake succeeded; {len(names)} tools listed.")
        for action, available in assist_capabilities(names).items():
            print(f"{action}: {'available' if available else 'not exposed'}")
        catalog = assist_action_catalog(tools)
        print(f"Schema-bearing action candidates: {', '.join(sorted(catalog)) or 'none'}")
        try:
            resources = await session.list_resources()
        except McpError:
            print("Resource listing unavailable; tool discovery still succeeded.")
        else:
            snapshot = any(
                str(resource.uri) == "homeassistant://assist/context-snapshot"
                for resource in resources.resources
            )
            print(f"Context snapshot: {'available' if snapshot else 'not exposed'}")


def main() -> int:
    instance_url = os.environ.get("HOME_ASSISTANT_URL", "")
    token = os.environ.get("HOME_ASSISTANT_TOKEN", "")
    if not instance_url or not token:
        print("Set HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN privately.", file=sys.stderr)
        return 2
    try:
        endpoint = assist_endpoint(instance_url)
        asyncio.run(check(endpoint, token))
    except (ValueError, OSError, McpError, httpx.HTTPError, ExceptionGroup) as exc:
        print(f"Assist MCP check failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
