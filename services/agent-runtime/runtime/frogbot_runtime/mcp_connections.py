from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

import boto3
import httpx
from botocore.config import Config
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp.mcp_agent_tool import MCPAgentTool
from strands.tools.mcp.mcp_client import MCPClient
from strands.types import PaginatedList

SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/connections/[a-f0-9]{24}/"
    r"connection_[a-f0-9]{20}-[a-f0-9]{12}-[A-Za-z0-9]+$"
)
OAUTH_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/google-[A-Za-z0-9]+$"
)
HEADER_PATTERN = re.compile(r"^(Authorization|X-[A-Za-z0-9-]{1,60})$")
GMAIL_MCP_ENDPOINT = "https://gmailmcp.googleapis.com/mcp/v1"
GITHUB_MCP_ENDPOINT = "https://api.githubcopilot.com/mcp/"
GMAIL_MCP_TOOLS = {
    "create_draft",
    "list_drafts",
    "get_draft",
    "get_thread",
    "get_message",
    "search_threads",
    "list_labels",
}
GOOGLE_OAUTH_ENDPOINT = "https://oauth2.googleapis.com/token"
_secrets_manager = None
MAX_TOOL_NAME_CHARS = 64


def _bounded_tool_name(connection_id: str, remote_name: str) -> str:
    prefix = f"c{hashlib.sha256(connection_id.encode()).hexdigest()[:10]}"
    candidate = f"{prefix}_{remote_name}"
    if len(candidate) <= MAX_TOOL_NAME_CHARS:
        return candidate
    suffix = hashlib.sha256(candidate.encode()).hexdigest()[:10]
    return f"{candidate[: MAX_TOOL_NAME_CHARS - len(suffix) - 1]}_{suffix}"


class BoundedMCPClient(MCPClient):
    """Expose stable MCP aliases that every supported text model can accept."""

    def __init__(self, *args: Any, connection_id: str, **kwargs: Any) -> None:
        self._frogbot_connection_id = connection_id
        super().__init__(*args, prefix=None, **kwargs)

    def list_tools_sync(
        self,
        pagination_token: str | None = None,
        prefix: str | None = None,
        tool_filters: Any = None,
    ) -> PaginatedList[MCPAgentTool]:
        page = super().list_tools_sync(
            pagination_token,
            prefix="",
            tool_filters=tool_filters,
        )
        tools = [
            MCPAgentTool(
                tool.mcp_tool,
                self,
                name_override=_bounded_tool_name(
                    self._frogbot_connection_id,
                    tool.mcp_tool.name,
                ),
                timeout=tool.timeout,
            )
            for tool in page
        ]
        return PaginatedList(tools, token=page.pagination_token)


def _validated_endpoint(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("MCP connection endpoint is invalid")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("MCP connection endpoint is invalid")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".local", ".internal")):
        raise ValueError("MCP connection endpoint must be public")
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(
                hostname, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
            )
        }
    except socket.gaierror as exc:
        raise ValueError("MCP connection hostname could not be resolved") from exc
    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ValueError("MCP connection endpoint must resolve publicly")
    return urllib.parse.urlunsplit(("https", hostname, parsed.path or "/", "", ""))


async def _validate_outbound_request(request: httpx.Request) -> None:
    """Re-resolve immediately before connection to narrow DNS-rebinding exposure."""
    _validated_endpoint(str(request.url))


def _secure_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout or httpx.Timeout(30, read=300),
        auth=auth,
        follow_redirects=False,
        event_hooks={"request": [_validate_outbound_request]},
    )


@asynccontextmanager
async def _secure_streamable_http(endpoint: str, headers: dict[str, str] | None):
    async with (
        _secure_http_client(headers=headers) as client,
        streamable_http_client(endpoint, http_client=client) as streams,
    ):
        yield streams


def validated_connection_binding(tool_id: str, runtime: dict) -> dict:
    endpoint = _validated_endpoint(runtime.get("endpoint"))
    auth_type = runtime.get("authType", "none")
    binding = {
        "id": tool_id,
        "kind": "mcp",
        "endpoint": endpoint,
        "authType": auth_type,
    }
    if auth_type == "none":
        return binding
    secret_arn = runtime.get("secretArn")
    if auth_type == "oauth":
        client_secret_arn = runtime.get("oauthClientSecretArn")
        allowed_tools = runtime.get("allowedTools")
        if (
            endpoint != GMAIL_MCP_ENDPOINT
            or runtime.get("oauthProvider") != "google"
            or not isinstance(secret_arn, str)
            or not SECRET_ARN_PATTERN.fullmatch(secret_arn)
            or not isinstance(client_secret_arn, str)
            or not OAUTH_CLIENT_SECRET_ARN_PATTERN.fullmatch(client_secret_arn)
            or not isinstance(allowed_tools, list)
            or not allowed_tools
            or len(allowed_tools) != len(set(allowed_tools))
            or not set(allowed_tools).issubset(GMAIL_MCP_TOOLS)
        ):
            raise ValueError(f"OAuth MCP connection is invalid: {tool_id}")
        return {
            **binding,
            "oauthProvider": "google",
            "secretArn": secret_arn,
            "oauthClientSecretArn": client_secret_arn,
            "allowedTools": allowed_tools,
        }
    header_name = runtime.get("headerName")
    header_prefix = runtime.get("headerPrefix", "")
    if (
        auth_type not in {"bearer", "api_key"}
        or not isinstance(secret_arn, str)
        or not SECRET_ARN_PATTERN.fullmatch(secret_arn)
        or not isinstance(header_name, str)
        or not HEADER_PATTERN.fullmatch(header_name)
        or header_prefix not in {"", "Bearer "}
    ):
        raise ValueError(f"MCP connection authentication is invalid: {tool_id}")
    return {
        **binding,
        "secretArn": secret_arn,
        "headerName": header_name,
        "headerPrefix": header_prefix,
    }


def _secret_value(secret_arn: str) -> str:
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = boto3.client(
            "secretsmanager",
            config=Config(
                retries={"total_max_attempts": 4, "mode": "adaptive"},
                connect_timeout=3,
                read_timeout=10,
            ),
        )
    response = _secrets_manager.get_secret_value(SecretId=secret_arn)
    value = response.get("SecretString")
    if not isinstance(value, str) or not value:
        raise ValueError("MCP connection credential is unavailable")
    return value


def connection_credential(binding: dict) -> str:
    if binding.get("authType") not in {"bearer", "api_key"}:
        raise ValueError("Connection does not use a reusable API credential")
    return _secret_value(binding["secretArn"])


def _json_secret(secret_arn: str) -> dict:
    try:
        value = json.loads(_secret_value(secret_arn))
    except json.JSONDecodeError as exc:
        raise ValueError("OAuth credential is invalid") from exc
    if not isinstance(value, dict):
        raise TypeError("OAuth credential is invalid")
    return value


def _google_access_token(binding: dict) -> str:
    credential = _json_secret(binding["secretArn"])
    client_document = _json_secret(binding["oauthClientSecretArn"])
    client = client_document.get("web", client_document)
    refresh_token = credential.get("refreshToken")
    client_id = client.get("client_id") if isinstance(client, dict) else None
    client_secret = client.get("client_secret") if isinstance(client, dict) else None
    if not all(
        isinstance(value, str) and value
        for value in (
            refresh_token,
            client_id,
            client_secret,
        )
    ):
        raise ValueError("OAuth credential is invalid")
    request = urllib.request.Request(
        GOOGLE_OAUTH_ENDPOINT,
        data=urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8"),
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
            value = json.loads(response.read(100_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("OAuth access token is unavailable") from exc
    access_token = value.get("access_token") if isinstance(value, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("OAuth access token is unavailable")
    return access_token


def connection_client(binding: dict) -> MCPClient:
    headers = None
    if binding["authType"] == "oauth":
        headers = {"Authorization": f"Bearer {_google_access_token(binding)}"}
    elif binding["authType"] != "none":
        credential = _secret_value(binding["secretArn"])
        headers = {binding["headerName"]: f"{binding['headerPrefix']}{credential}"}
    options = {
        "connection_id": binding["id"],
        "startup_timeout": 15,
        "continue_on_error": False,
        "application_name": "FroggyBot",
    }
    if binding["authType"] == "oauth":
        options["tool_filters"] = {"allowed": binding["allowedTools"]}
    return BoundedMCPClient(
        partial(_secure_streamable_http, binding["endpoint"], headers),
        **options,
    )
