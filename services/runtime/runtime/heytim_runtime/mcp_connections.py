from __future__ import annotations

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
from .mcp_tool_catalog import (
    GMAIL_MCP_ENDPOINT,
    GMAIL_MCP_TOOLS,
    GOOGLE_WORKSPACE_MCP_SERVERS,
    GOOGLE_WORKSPACE_SCOPES,
    SCOPED_GOOGLE_TOOLS,
)
from .mcp_tool_names import _bounded_tool_name

SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:heytim/connections/[a-f0-9]{24}/"
    r"connection_[a-f0-9]{20}-[a-f0-9]{12}-[A-Za-z0-9]+$"
)
OAUTH_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:heytim/oauth/google-[A-Za-z0-9-]+$"
)
GITHUB_APP_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:heytim/oauth/github-[A-Za-z0-9-]+$"
)
GOOGLE_OAUTH_ENDPOINT = "https://oauth2.googleapis.com/token"
_secrets_manager = None


class ConnectionCredentialUnavailable(ValueError):
    """A saved connection needs to be reauthenticated before it can be used."""


class LabeledMCPAgentTool(MCPAgentTool):
    def __init__(self, *args: Any, account_label: str | None = None, **kwargs: Any) -> None:
        self._heytim_account_label = account_label
        super().__init__(*args, **kwargs)

    @property
    def tool_spec(self):
        spec = super().tool_spec
        if self._heytim_account_label:
            spec["description"] += f" Connected account: {self._heytim_account_label}."
        return spec


class BoundedMCPClient(MCPClient):
    """Expose stable MCP aliases that every supported text model can accept."""

    def __init__(
        self, *args: Any, connection_id: str,
        resource_ids: set[str] | None = None,
        resource_server: str | None = None,
        account_label: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._heytim_connection_id = connection_id
        self._heytim_resource_ids = resource_ids
        self._heytim_resource_server = resource_server
        self._heytim_account_label = account_label
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
            LabeledMCPAgentTool(
                tool.mcp_tool,
                self,
                account_label=self._heytim_account_label,
                name_override=_bounded_tool_name(
                    self._heytim_connection_id,
                    tool.mcp_tool.name,
                ),
                timeout=tool.timeout,
            )
            for tool in page
            if self._heytim_resource_ids is None
            or tool.mcp_tool.name in SCOPED_GOOGLE_TOOLS.get(
                self._heytim_resource_server or "", {}
            )
        ]
        return PaginatedList(tools, token=page.pagination_token)

    async def call_tool_async(
        self, tool_use_id: str, name: str,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        if self._heytim_resource_ids is not None:
            field = SCOPED_GOOGLE_TOOLS.get(
                self._heytim_resource_server or "", {}
            ).get(name)
            resource = arguments.get(field) if isinstance(arguments, dict) and field else None
            if not isinstance(resource, str) or resource not in self._heytim_resource_ids:
                return {
                    "toolUseId": tool_use_id,
                    "status": "error",
                    "content": [{"text": "This bot is not assigned that Workspace resource"}],
                }
        return await super().call_tool_async(
            tool_use_id, name, arguments=arguments, **kwargs
        )


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
    account_label = runtime.get("accountLabel")
    if account_label is not None:
        if not isinstance(account_label, str) or not account_label.strip() or len(account_label) > 160:
            raise ValueError(f"MCP account label is invalid: {tool_id}")
        binding["accountLabel"] = account_label.strip()
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
    if auth_type == "home_assistant_token":
        if (
            urllib.parse.urlsplit(endpoint).path != "/api/mcp/assist"
            or not isinstance(secret_arn, str)
            or not SECRET_ARN_PATTERN.fullmatch(secret_arn)
        ):
            raise ValueError(f"Home Assistant MCP connection is invalid: {tool_id}")
        return {**binding, "secretArn": secret_arn}
    if auth_type == "bearer_token":
        if not isinstance(secret_arn, str) or not SECRET_ARN_PATTERN.fullmatch(secret_arn):
            raise ValueError(f"MCP server credential is invalid: {tool_id}")
        return {**binding, "secretArn": secret_arn}
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
    repository_ids = runtime.get("repositoryIds")
    if repository_ids is not None and (
        not isinstance(repository_ids, list)
        or not 1 <= len(repository_ids) <= 500
        or any(type(value) is not int or value <= 0 for value in repository_ids)
        or len(repository_ids) != len(set(repository_ids))
    ):
        raise ValueError(f"GitHub repository access is invalid: {tool_id}")
    return {
        **binding,
        "secretArn": secret_arn,
        "appSecretArn": app_secret_arn,
        **({"repositoryIds": repository_ids} if repository_ids is not None else {}),
    }


def validated_connection_bundle_binding(tool_id: str, runtime: dict) -> dict:
    secret_arn = runtime.get("secretArn")
    client_secret_arn = runtime.get("oauthClientSecretArn")
    scopes = runtime.get("scopes")
    servers = runtime.get("servers")
    resource_ids = runtime.get("resourceIds")
    account_label = runtime.get("accountLabel")
    if account_label is not None and (
        not isinstance(account_label, str) or not account_label.strip() or len(account_label) > 160
    ):
        raise ValueError(f"Workspace account label is invalid: {tool_id}")
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
        or len(servers) not in {
            len(GOOGLE_WORKSPACE_MCP_SERVERS),
            len(GOOGLE_WORKSPACE_MCP_SERVERS) - 1,
        }
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
    legacy_servers = set(GOOGLE_WORKSPACE_MCP_SERVERS) - {
        "https://sheetsmcp.googleapis.com/mcp/v1"
    }
    if frozenset(seen) not in {
        frozenset(GOOGLE_WORKSPACE_MCP_SERVERS),
        frozenset(legacy_servers),
    }:
        raise ValueError(f"Google Workspace MCP connection is invalid: {tool_id}")
    if resource_ids is not None and (
        not isinstance(resource_ids, list)
        or not 1 <= len(resource_ids) <= 100
        or any(
            not isinstance(item, str)
            or not re.fullmatch(
                r"(?:file|sheet):[A-Za-z0-9_-]{8,256}|calendar:[A-Za-z0-9_.@%+\-]{1,256}",
                item,
            )
            for item in resource_ids
        )
        or len(resource_ids) != len(set(resource_ids))
    ):
        raise ValueError(f"Workspace resource access is invalid: {tool_id}")
    return {
        "id": tool_id,
        "kind": "mcp_bundle",
        "authType": "oauth",
        "oauthProvider": "google",
        "secretArn": secret_arn,
        "oauthClientSecretArn": client_secret_arn,
        "scopes": scopes,
        "servers": normalized_servers,
        **({"accountLabel": account_label.strip()} if account_label is not None else {}),
        **({"resourceIds": resource_ids} if resource_ids is not None else {}),
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
        raise ConnectionCredentialUnavailable(
            "MCP connection credential is unavailable"
        )
    return value


def _json_secret(secret_arn: str) -> dict:
    try:
        value = json.loads(_secret_value(secret_arn))
    except json.JSONDecodeError as exc:
        raise ConnectionCredentialUnavailable("OAuth credential is invalid") from exc
    if not isinstance(value, dict):
        raise ConnectionCredentialUnavailable("OAuth credential is invalid")
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
        raise ConnectionCredentialUnavailable("OAuth credential is invalid")
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
        raise ConnectionCredentialUnavailable(
            "OAuth access token is unavailable"
        ) from exc
    access_token = value.get("access_token") if isinstance(value, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise ConnectionCredentialUnavailable("OAuth access token is unavailable")
    return access_token


def _home_assistant_access_token(binding: dict) -> str:
    token = _json_secret(binding["secretArn"]).get("accessToken")
    if (
        not isinstance(token, str)
        or not 20 <= len(token) <= 4096
        or not re.fullmatch(r"[A-Za-z0-9._~=-]+", token)
    ):
        raise ConnectionCredentialUnavailable(
            "Home Assistant access token is unavailable"
        )
    return token


def _mcp_access_token(binding: dict) -> str:
    token = _json_secret(binding["secretArn"]).get("accessToken")
    if (
        not isinstance(token, str)
        or not 20 <= len(token) <= 4096
        or not re.fullmatch(r"[A-Za-z0-9._~+/-]+={0,3}", token)
    ):
        raise ConnectionCredentialUnavailable(
            "MCP server access token is unavailable"
        )
    return token


def github_installation_token(binding: dict) -> str:
    if binding.get("authType") != "github_app":
        raise ValueError("Connection does not use a GitHub App installation")
    grant = validate_installation_grant(_json_secret(binding["secretArn"]))
    repository_ids = binding.get("repositoryIds")
    if repository_ids is not None:
        repository_ids = [
            value for value in repository_ids if value in grant["repositoryIds"]
        ]
        if not repository_ids:
            raise ValueError("The bot no longer has access to a connected repository")
    else:
        repository_ids = grant["repositoryIds"]
    config = github_app_config(_json_secret(binding["appSecretArn"]))
    request = urllib.request.Request(
        (f"{GITHUB_API_URL}/app/installations/{grant['installationId']}/access_tokens"),
        data=json.dumps(
            {
                "repository_ids": repository_ids,
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
            "user-agent": "HeyTim/1.0",
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
    elif binding["authType"] == "home_assistant_token":
        headers = {"Authorization": f"Bearer {_home_assistant_access_token(binding)}"}
    elif binding["authType"] == "bearer_token":
        headers = {"Authorization": f"Bearer {_mcp_access_token(binding)}"}
    options = {
        "connection_id": binding["id"],
        "startup_timeout": 15,
        "continue_on_error": False,
        "application_name": "HeyTim",
        "account_label": binding.get("accountLabel"),
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
    servers = list(binding["servers"])
    if (
        any(item.startswith("sheet:") for item in binding.get("resourceIds", []))
        and not any(
            urllib.parse.urlsplit(server["endpoint"]).hostname
            == "sheetsmcp.googleapis.com"
            for server in servers
        )
    ):
        endpoint = "https://sheetsmcp.googleapis.com/mcp/v1"
        servers.append({
            "endpoint": endpoint,
            "allowedTools": list(GOOGLE_WORKSPACE_MCP_SERVERS[endpoint]),
        })
    for server in servers:
        hostname = urllib.parse.urlsplit(server["endpoint"]).hostname or "mcp"
        resource_ids = None
        allowed_tools = server["allowedTools"]
        if "resourceIds" in binding:
            selected = {
                kind: {item.split(":", 1)[1] for item in binding["resourceIds"]
                       if item.startswith(f"{kind}:")}
                for kind in ("file", "sheet", "calendar")
            }
            resource_ids = (
                selected["file"] | selected["sheet"]
                if hostname == "drivemcp.googleapis.com"
                else selected["file"] if hostname == "docsmcp.googleapis.com"
                else selected["sheet"] if hostname == "sheetsmcp.googleapis.com"
                else selected["calendar"] if hostname == "calendarmcp.googleapis.com"
                else set()
            )
            allowed_tools = [
                name for name in allowed_tools
                if name in SCOPED_GOOGLE_TOOLS.get(hostname, {})
            ]
            if not resource_ids or not allowed_tools:
                continue
        clients.append(
            BoundedMCPClient(
                partial(_secure_streamable_http, server["endpoint"], headers),
                connection_id=f"{binding['id']}:{hostname}",
                resource_ids=resource_ids,
                resource_server=hostname,
                account_label=binding.get("accountLabel"),
                startup_timeout=15,
                continue_on_error=False,
                application_name="HeyTim",
                tool_filters={"allowed": allowed_tools},
            )
        )
    return clients
