"""A user-activated entry point into secure native connection setup."""
from __future__ import annotations

import urllib.parse

from strands import tool


@tool
def request_integration_setup(name: str = "MCP server", server_url: str = "") -> str:
    """Offer a Connect link when the user asks to add an integration or MCP server.

    This opens secure setup after the user clicks. It does not connect or grant
    tools. Never request credentials in chat. For APIs without MCP, explain that
    a compatible MCP server or reviewed adapter is needed. Local/private servers
    need a supported remote route; do not suggest exposing a local service.
    Include the returned Markdown link unchanged in the reply.
    """
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Server name must be 1–80 characters")
    if not isinstance(server_url, str) or len(server_url) > 500:
        raise ValueError("MCP URL is invalid")
    if server_url:
        value = urllib.parse.urlsplit(server_url)
        if (value.scheme != "https" or not value.hostname or value.username is not None
                or value.password is not None or value.query or value.fragment
                or value.port not in {None, 443}):
            raise ValueError("Use a public HTTPS MCP URL without credentials")
    query = urllib.parse.urlencode({"name": name.strip(), "url": server_url}, quote_via=urllib.parse.quote)
    return f"[Connect {name.strip().replace('[', '').replace(']', '')}](heytim://connect-mcp?{query})"
