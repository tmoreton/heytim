"""Bounded, non-mutating discovery of untrusted remote MCP servers."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import time
import urllib.parse

from .catalog_rules import CatalogError, _validate_mcp_endpoint

MAX_TOOLS = 100
MAX_PAGES = 8
MAX_RESPONSE_BYTES = 256_000
DISCOVERY_SECONDS = 12
PROTOCOL = "2025-11-25"


def tool_digest(tool: dict) -> str:
    """Bind permission to the actual executable schema, not a server's risk claim."""
    contract = {key: tool[key] for key in (
        "name", "inputSchema", "outputSchema", "annotations", "execution"
    ) if tool.get(key) is not None}
    return hashlib.sha256(json.dumps(
        contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()).hexdigest()


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        # Resolve once and connect to that address. TLS still verifies the hostname.
        addresses = socket.getaddrinfo(self.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise CatalogError("MCP endpoint must resolve to a public address")
        self.sock = socket.create_connection((addresses[0][4][0], 443), self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class MCPDiscovery:
    def __init__(self, endpoint: str, token: str | None):
        self.endpoint = _validate_mcp_endpoint(endpoint)
        self.token = token
        self.session: str | None = None
        self.deadline = time.monotonic() + DISCOVERY_SECONDS
        self.protocol = PROTOCOL

    def post(self, method: str, params: dict, request_id: int | None = None) -> dict:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CatalogError("MCP discovery timed out")
        parsed = urllib.parse.urlsplit(self.endpoint)
        connection = PublicHTTPSConnection(parsed.hostname, timeout=min(3, remaining),
                                           context=ssl.create_default_context())
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": self.protocol}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        try:
            connection.request("POST", parsed.path or "/", json.dumps(message).encode(), headers)
            response = connection.getresponse()
            if response.status in {401, 403}:
                raise CatalogError("MCP authentication failed. Check the token or server sign-in requirements.")
            if response.status == 404:
                raise CatalogError("MCP endpoint not found. Check the full MCP URL.")
            if response.status not in {200, 202, 204}:
                raise CatalogError("MCP server rejected discovery. Redirects are not followed.")
            session = response.getheader("Mcp-Session-Id")
            if session:
                if len(session) > 200 or not all(33 <= ord(c) <= 126 for c in session):
                    raise CatalogError("MCP server returned an invalid session")
                self.session = session
            if request_id is None:
                return {}
            content_type = response.getheader("Content-Type", "").split(";")[0].strip()
            if content_type == "text/event-stream":
                data, total, pending = [], 0, b""
                while time.monotonic() < self.deadline:
                    chunk = response.read1(min(8192, MAX_RESPONSE_BYTES - total + 1))
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise CatalogError("MCP discovery response is too large")
                    if not chunk:
                        break
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        if line.startswith(b"data:"):
                            data.append(line[5:].strip())
                        elif not line.strip() and data:
                            value = json.loads(b"\n".join(data))
                            data = []
                            if isinstance(value, dict) and value.get("id") == request_id:
                                return self.result(value, request_id)
                raise CatalogError("MCP server did not finish discovery")
            if content_type != "application/json":
                raise CatalogError("MCP endpoint did not return JSON or an event stream")
            body = b""
            while time.monotonic() < self.deadline:
                chunk = response.read1(min(8192, MAX_RESPONSE_BYTES - len(body) + 1))
                body += chunk
                if len(body) > MAX_RESPONSE_BYTES:
                    raise CatalogError("MCP discovery response is too large")
                if not chunk:
                    break
            else:
                raise CatalogError("MCP discovery timed out")
            return self.result(json.loads(body), request_id)
        except CatalogError:
            raise
        except (OSError, ValueError, http.client.HTTPException) as exc:
            # Do not include remote response bodies, credentials or URLs in errors.
            raise CatalogError("MCP discovery failed. Check the URL, credentials and server availability.") from exc
        finally:
            connection.close()

    @staticmethod
    def result(value: dict, request_id: int) -> dict:
        if (not isinstance(value, dict) or value.get("jsonrpc") != "2.0"
                or value.get("id") != request_id or "error" in value
                or not isinstance(value.get("result"), dict)):
            raise CatalogError("MCP server returned an invalid discovery result")
        return value["result"]

    def discover(self) -> dict:
        started = self.post("initialize", {
            "protocolVersion": PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "HeyTim", "version": "1"},
        }, 1)
        if started.get("protocolVersion") not in {"2025-03-26", "2025-06-18", PROTOCOL}:
            raise CatalogError("This MCP protocol version is not supported yet")
        self.protocol = started["protocolVersion"]
        self.post("notifications/initialized", {})
        tools, cursors, names, cursor = [], set(), set(), None
        for page in range(MAX_PAGES):
            result = self.post("tools/list", {"cursor": cursor} if cursor else {}, page + 2)
            values = result.get("tools")
            if not isinstance(values, list) or len(tools) + len(values) > MAX_TOOLS:
                raise CatalogError("MCP server exceeds the tool discovery limit")
            for tool in values:
                if (not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                        or not 1 <= len(tool["name"]) <= 128 or tool["name"] in names
                        or not isinstance(tool.get("inputSchema"), dict)):
                    raise CatalogError("MCP server returned an invalid or duplicate tool")
                if len(json.dumps(tool).encode()) > 32_000:
                    raise CatalogError("MCP tool schema is too large")
                names.add(tool["name"])
                tools.append({"name": tool["name"], "description": str(tool.get("description", ""))[:500],
                              "digest": tool_digest(tool)})
            cursor = result.get("nextCursor")
            if cursor is None:
                server = started.get("serverInfo", {})
                if not isinstance(server, dict):
                    raise CatalogError("MCP server identity is invalid")
                return {"serverName": str(server.get("name", "MCP server"))[:120],
                        "serverVersion": str(server.get("version", ""))[:80],
                        "protocolVersion": self.protocol, "tools": tools}
            if not isinstance(cursor, str) or not cursor or len(cursor) > 1000 or cursor in cursors:
                raise CatalogError("MCP server returned an invalid discovery cursor")
            cursors.add(cursor)
        raise CatalogError("MCP server exceeds the discovery page limit")

    def close(self) -> None:
        if not self.session:
            return
        parsed = urllib.parse.urlsplit(self.endpoint)
        connection = PublicHTTPSConnection(parsed.hostname, timeout=1,
                                           context=ssl.create_default_context())
        headers = {"Mcp-Session-Id": self.session, "MCP-Protocol-Version": self.protocol}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        try:
            # Release the temporary protocol session, never invoke a business tool.
            connection.request("DELETE", parsed.path or "/", headers=headers)
            connection.getresponse()
        except (OSError, ValueError, http.client.HTTPException):
            # Session deletion is optional in MCP; cleanup cannot hide the probe result.
            pass
        finally:
            self.session = None
            connection.close()


def discover_mcp_server(endpoint: str, token: str | None) -> dict:
    discovery = MCPDiscovery(endpoint, token)
    try:
        return discovery.discover()
    finally:
        discovery.close()
