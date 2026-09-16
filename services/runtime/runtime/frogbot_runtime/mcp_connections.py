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

from .github_app import (
    GITHUB_API_URL,
    GITHUB_API_VERSION,
    GITHUB_APP_PERMISSIONS,
    GITHUB_MCP_ENDPOINT,
    github_app_config,
    github_app_jwt,
    validate_installation_grant,
)

SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/connections/[a-f0-9]{24}/"
    r"connection_[a-f0-9]{20}-[a-f0-9]{12}-[A-Za-z0-9]+$"
)
OAUTH_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/google-[A-Za-z0-9-]+$"
)
GITHUB_APP_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/github-[A-Za-z0-9-]+$"
)
GMAIL_MCP_ENDPOINT = "https://gmailmcp.googleapis.com/mcp/v1"
GMAIL_MCP_TOOLS = {
    "create_draft",
    "list_drafts",
    "get_draft",
    "get_thread",
    "get_message",
    "search_threads",
    "list_labels",
}
GOOGLE_WORKSPACE_MCP_SERVERS = {
    "https://drivemcp.googleapis.com/mcp/v1": {
        "download_file_content",
        "get_file_metadata",
        "get_file_permissions",
        "list_recent_files",
        "read_file_content",
        "search_files",
    },
    "https://docsmcp.googleapis.com/mcp/v1": {"read_doc"},
    "https://calendarmcp.googleapis.com/mcp/v1": {
        "get_event",
        "list_calendars",
        "list_events",
        "search_events",
        "suggest_time",
    },
}
GOOGLE_WORKSPACE_SCOPES = {
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
    "https://www.googleapis.com/auth/calendar.events.readonly",
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
    app_secret_arn = runtime.get("appSecretArn")
    if (
        auth_type != "github_app"
        or endpoint.rstrip("/") != GITHUB_MCP_ENDPOINT.rstrip("/")
        or not isinstance(secret_arn, str)
        or not SECRET_ARN_PATTERN.fullmatch(secret_arn)
        or not isinstance(app_secret_arn, str)
        or not GITHUB_APP_SECRET_ARN_PATTERN.fullmatch(app_secret_arn)
    ):
        raise ValueError(f"MCP connection authentication is invalid: {tool_id}")
    return {
        **binding,
        "secretArn": secret_arn,
        "appSecretArn": app_secret_arn,
    }


def validated_connection_bundle_binding(tool_id: str, runtime: dict) -> dict:
    secret_arn = runtime.get("secretArn")
    client_secret_arn = runtime.get("oauthClientSecretArn")
    scopes = runtime.get("scopes")
    servers = runtime.get("servers")
    if (
        runtime.get("authType") != "oauth"
        or runtime.get("oauthProvider") != "google"
        or not isinstance(secret_arn, str)
        or not SECRET_ARN_PATTERN.fullmatch(secret_arn)
        or not isinstance(client_secret_arn, str)
        or not OAUTH_CLIENT_SECRET_ARN_PATTERN.fullmatch(client_secret_arn)
        or not isinstance(scopes, list)
        or set(scopes) != GOOGLE_WORKSPACE_SCOPES
        or len(scopes) != len(set(scopes))
        or not isinstance(servers, list)
        or len(servers) != len(GOOGLE_WORKSPACE_MCP_SERVERS)
    ):
        raise ValueError(f"Google Workspace MCP connection is invalid: {tool_id}")

    normalized_servers = []
    seen = set()
    for server in servers:
        if not isinstance(server, dict):
            raise TypeError(
                f"Google Workspace MCP connection is invalid: {tool_id}"
            )
        endpoint = _validated_endpoint(server.get("endpoint"))
        allowed_tools = server.get("allowedTools")
        expected_tools = GOOGLE_WORKSPACE_MCP_SERVERS.get(endpoint)
        if (
            endpoint in seen
            or expected_tools is None
            or not isinstance(allowed_tools, list)
            or set(allowed_tools) != expected_tools
            or len(allowed_tools) != len(set(allowed_tools))
        ):
            raise ValueError(
                f"Google Workspace MCP connection is invalid: {tool_id}"
            )
        seen.add(endpoint)
        normalized_servers.append(
            {"endpoint": endpoint, "allowedTools": allowed_tools}
        )
    if seen != set(GOOGLE_WORKSPACE_MCP_SERVERS):
        raise ValueError(f"Google Workspace MCP connection is invalid: {tool_id}")
    return {
        "id": tool_id,
        "kind": "mcp_bundle",
        "authType": "oauth",
        "oauthProvider": "google",
        "secretArn": secret_arn,
        "oauthClientSecretArn": client_secret_arn,
        "scopes": scopes,
        "servers": normalized_servers,
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


def github_installation_token(binding: dict) -> str:
    if binding.get("authType") != "github_app":
        raise ValueError("Connection does not use a GitHub App installation")
    grant = validate_installation_grant(_json_secret(binding["secretArn"]))
    config = github_app_config(_json_secret(binding["appSecretArn"]))
    request = urllib.request.Request(
        (f"{GITHUB_API_URL}/app/installations/{grant['installationId']}/access_tokens"),
        data=json.dumps(
            {
                "repository_ids": grant["repositoryIds"],
                "permissions": {
                    name: value
                    for name, value in grant["permissions"].items()
                    if name in GITHUB_APP_PERMISSIONS
                },
            },
            separators=(",", ":"),
        ).encode("utf-8"),
        headers={
            "accept": "application/vnd.github+json",
            "authorization": (
                f"Bearer {github_app_jwt(config['appId'], config['privateKey'])}"
            ),
            "content-type": "application/json",
            "user-agent": "FroggyBot/1.0",
            "x-github-api-version": GITHUB_API_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - fixed GitHub API endpoint.
            request, timeout=10
        ) as response:
            value = json.loads(response.read(100_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("GitHub installation access is unavailable") from exc
    token = value.get("token") if isinstance(value, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("GitHub installation access is unavailable")
    return token


def connection_client(binding: dict) -> MCPClient:
    headers = None
    if binding["authType"] == "oauth":
        headers = {"Authorization": f"Bearer {_google_access_token(binding)}"}
    elif binding["authType"] == "github_app":
        headers = {"Authorization": f"Bearer {github_installation_token(binding)}"}
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


def connection_clients(binding: dict) -> list[MCPClient]:
    if binding["kind"] == "mcp":
        return [connection_client(binding)]
    if binding["kind"] != "mcp_bundle" or binding["authType"] != "oauth":
        raise ValueError("MCP connection bundle is invalid")
    headers = {"Authorization": f"Bearer {_google_access_token(binding)}"}
    clients = []
    for server in binding["servers"]:
        hostname = urllib.parse.urlsplit(server["endpoint"]).hostname or "mcp"
        clients.append(
            BoundedMCPClient(
                partial(_secure_streamable_http, server["endpoint"], headers),
                connection_id=f"{binding['id']}:{hostname}",
                startup_timeout=15,
                continue_on_error=False,
                application_name="FroggyBot",
                tool_filters={"allowed": server["allowedTools"]},
            )
        )
    return clients
