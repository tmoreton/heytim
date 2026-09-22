from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from typing import Any

from shared.client_contract import BOT_PROMPT_MAX_LENGTH, SKILL_INSTRUCTIONS_MAX_LENGTH
from shared.connection_providers import (
    GMAIL_MCP_ENDPOINT,
    GMAIL_MCP_TOOLS,
    GOOGLE_WORKSPACE_MCP_SERVERS,
    connection_specs,
)
from shared.github_app import GITHUB_MCP_ENDPOINT

MAX_SKILLS_PER_BOT = 12
MAX_TOOLS_PER_BOT = 12
MAX_SKILL_INSTRUCTIONS = SKILL_INSTRUCTIONS_MAX_LENGTH
RETIRED_TOOL_IDS = frozenset({"meme_composer", "x_search", "youtube_search"})
MAX_CATALOG_TAGS = 6
MAX_BOT_PROMPT = BOT_PROMPT_MAX_LENGTH
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TOOL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
RUNTIME_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,127}$")
RUNTIME_NAMES = {
    "agentcore": {"browser", "code_interpreter"},
    "local": {
        "bot_manager",
        "calculator",
        "current_time",
        "image_generator",
        "meme_lord",
    },
    "stan_builtin": {"web_fetch"},
    "stan_plugin": {"todos"},
    "stan_subagent": {"generalist"},
}
TOOL_RISKS = {"read", "sandbox", "interactive"}
BOT_COLORS = {
    "#FFBC3B",
    "#007A3D",
    "#58BEAA",
    "#FFAA34",
    "#6C5CE7",
    "#3984F6",
    "#F46A27",
    "#E95383",
}
BOT_CATALOG_FIELDS = {
    "id",
    "version",
    "name",
    "tagline",
    "prompt",
    "color",
    "category",
    "author",
    "tags",
    "featured",
    "skillIds",
    "toolIds",
}
PROVIDER_API_SCOPES = {
    provider_id: frozenset(spec["scopes"])
    for provider_id, spec in connection_specs().items()
    if provider_id in {"youtube", "x", "slack", "microsoft", "microsoft_teams", "notion", "hubspot", "jira", "zoom"}
}
GOOGLE_WORKSPACE_SCOPES = frozenset(
    connection_specs()["google_workspace"]["scopes"]
)
GOOGLE_WORKSPACE_SERVERS = {
    server["endpoint"]: frozenset(server["allowedTools"])
    for server in GOOGLE_WORKSPACE_MCP_SERVERS
}


class CatalogError(Exception):
    pass


def _version_key(version: int) -> str:
    return f"VERSION#{version:09d}"


def _validate_id(value: Any, field: str = "id") -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise CatalogError(f"{field} is invalid")
    return value


def _validate_tool_id(value: Any) -> str:
    if not isinstance(value, str) or not TOOL_ID_PATTERN.fullmatch(value):
        raise CatalogError("tool id is invalid")
    return value


def _validate_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{field} is required")
    clean = value.strip()
    if len(clean) > maximum:
        raise CatalogError(f"{field} must be at most {maximum} characters")
    return clean


def _validate_mcp_endpoint(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise CatalogError("MCP server URL is required")
    clean = value.strip()
    parsed = urllib.parse.urlsplit(clean)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise CatalogError("MCP server must use a plain HTTPS URL on port 443")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".local", ".internal")):
        raise CatalogError("MCP server must use a public hostname")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise CatalogError("MCP server must use a public hostname")
    if not _hostname_resolves_publicly(hostname):
        raise CatalogError("MCP server must resolve only to public addresses")
    return urllib.parse.urlunsplit(("https", hostname, parsed.path or "/", "", ""))


def _normalize_home_assistant_endpoint(value: Any) -> str:
    endpoint = _validate_mcp_endpoint(value)
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.path.rstrip("/") not in {"", "/api/mcp", "/api/mcp/assist"}:
        raise CatalogError("Home Assistant URL must point to the instance or Assist MCP endpoint")
    return urllib.parse.urlunsplit(
        ("https", parsed.hostname or "", "/api/mcp/assist", "", "")
    )


def _hostname_resolves_publicly(hostname: str) -> bool:
    try:
        results = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # A connection may be provisioned before DNS. Runtime resolution must
        # repeat this check immediately before connecting to prevent rebinding.
        return True
    addresses = {
        result[4][0]
        for result in results
        if len(result) > 4 and result[4] and isinstance(result[4][0], str)
    }
    return bool(addresses) and all(
        ipaddress.ip_address(value).is_global for value in addresses
    )


def _validate_catalog_metadata(value: dict, *, actions: bool = False) -> dict:
    tags = value.get("tags", [])
    if (
        not isinstance(tags, list)
        or len(tags) > MAX_CATALOG_TAGS
        or any(
            not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 32
            for tag in tags
        )
    ):
        raise CatalogError(f"tags must contain at most {MAX_CATALOG_TAGS} short labels")
    metadata = {
        "category": _validate_text(value.get("category", "General"), "category", 48),
        "author": _validate_text(value.get("author", "HeyTim"), "author", 80),
        "tags": list(dict.fromkeys(tag.strip() for tag in tags)),
        "featured": value.get("featured") is True,
    }
    if actions:
        tool_actions = value.get("actions", [])
        if (
            not isinstance(tool_actions, list)
            or not 1 <= len(tool_actions) <= 8
            or any(
                not isinstance(action, str)
                or not action.strip()
                or len(action.strip()) > 80
                for action in tool_actions
            )
        ):
            raise CatalogError("tool actions must contain 1 to 8 short labels")
        metadata["actions"] = list(
            dict.fromkeys(action.strip() for action in tool_actions)
        )
    return metadata


def _validate_tool_ids(value: Any, allowed: set[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CatalogError("requiredToolIds must be a list")
    unique = list(dict.fromkeys(value))
    unknown = set(unique) - allowed
    if unknown:
        raise CatalogError(f"Unknown required tools: {', '.join(sorted(unknown))}")
    if len(unique) > MAX_TOOLS_PER_BOT:
        raise CatalogError(f"A skill can require at most {MAX_TOOLS_PER_BOT} tools")
    return unique


def _validate_gateway_binding(value: dict) -> dict:
    operations = value.get("operations")
    if (
        not isinstance(operations, list)
        or not 1 <= len(operations) <= 8
        or len(set(operations)) != len(operations)
        or any(
            not isinstance(operation, str)
            or not RUNTIME_NAME_PATTERN.fullmatch(operation)
            for operation in operations
        )
    ):
        raise CatalogError("gateway tool operations are invalid")
    return {"kind": "gateway", "operations": operations}


def _validate_oauth_binding(value: dict, endpoint: str, secret_arn: Any) -> dict:
    client_secret_arn = value.get("oauthClientSecretArn")
    allowed_tools = value.get("allowedTools")
    if (
        endpoint != GMAIL_MCP_ENDPOINT
        or value.get("oauthProvider") != "google"
        or not isinstance(secret_arn, str)
        or not secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(client_secret_arn, str)
        or not client_secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(allowed_tools, list)
        or not allowed_tools
        or len(allowed_tools) != len(set(allowed_tools))
        or not set(allowed_tools).issubset(GMAIL_MCP_TOOLS)
    ):
        raise CatalogError("OAuth MCP connection is invalid")
    return {
        "kind": "mcp",
        "endpoint": endpoint,
        "authType": "oauth",
        "oauthProvider": "google",
        "secretArn": secret_arn,
        "oauthClientSecretArn": client_secret_arn,
        "allowedTools": allowed_tools,
    }


def _validate_github_app_binding(value: dict, endpoint: str, secret_arn: Any) -> dict:
    app_secret_arn = value.get("appSecretArn")
    if (
        endpoint.rstrip("/") != GITHUB_MCP_ENDPOINT.rstrip("/")
        or not isinstance(secret_arn, str)
        or not secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(app_secret_arn, str)
        or not app_secret_arn.startswith("arn:aws:secretsmanager:")
    ):
        raise CatalogError("GitHub App connection is invalid")
    return {
        "kind": "mcp",
        "endpoint": endpoint,
        "authType": "github_app",
        "secretArn": secret_arn,
        "appSecretArn": app_secret_arn,
    }


def _validate_mcp_binding(value: dict) -> dict:
    endpoint = _validate_mcp_endpoint(value.get("endpoint"))
    auth_type = value.get("authType", "none")
    if auth_type == "none":
        return {"kind": "mcp", "endpoint": endpoint, "authType": "none"}
    secret_arn = value.get("secretArn")
    if auth_type == "oauth":
        return _validate_oauth_binding(value, endpoint, secret_arn)
    if auth_type == "github_app":
        return _validate_github_app_binding(value, endpoint, secret_arn)
    if auth_type == "home_assistant_token":
        if (
            endpoint != _normalize_home_assistant_endpoint(endpoint)
            or not isinstance(secret_arn, str)
            or not secret_arn.startswith("arn:aws:secretsmanager:")
        ):
            raise CatalogError("Home Assistant MCP connection is invalid")
        return {
            "kind": "mcp", "endpoint": endpoint,
            "authType": "home_assistant_token", "secretArn": secret_arn,
        }
    raise CatalogError("Legacy MCP credentials are no longer supported")


def _validate_mcp_bundle_binding(value: dict) -> dict:
    secret_arn = value.get("secretArn")
    client_secret_arn = value.get("oauthClientSecretArn")
    scopes = value.get("scopes")
    servers = value.get("servers")
    resource_ids = value.get("resourceIds")
    if (
        value.get("authType") != "oauth"
        or value.get("oauthProvider") != "google"
        or not isinstance(secret_arn, str)
        or not secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(client_secret_arn, str)
        or not client_secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(scopes, list)
        or set(scopes) != GOOGLE_WORKSPACE_SCOPES
        or len(scopes) != len(set(scopes))
        or not isinstance(servers, list)
        or len(servers) not in {len(GOOGLE_WORKSPACE_SERVERS), len(GOOGLE_WORKSPACE_SERVERS) - 1}
    ):
        raise CatalogError("Google Workspace MCP connection is invalid")

    normalized_servers = []
    seen = set()
    for server in servers:
        if not isinstance(server, dict):
            raise CatalogError("Google Workspace MCP connection is invalid")
        endpoint = _validate_mcp_endpoint(server.get("endpoint"))
        allowed_tools = server.get("allowedTools")
        expected_tools = GOOGLE_WORKSPACE_SERVERS.get(endpoint)
        if (
            endpoint in seen
            or expected_tools is None
            or not isinstance(allowed_tools, list)
            or set(allowed_tools) != expected_tools
            or len(allowed_tools) != len(set(allowed_tools))
        ):
            raise CatalogError("Google Workspace MCP connection is invalid")
        seen.add(endpoint)
        normalized_servers.append(
            {"endpoint": endpoint, "allowedTools": allowed_tools}
        )
    legacy_servers = set(GOOGLE_WORKSPACE_SERVERS) - {
        "https://sheetsmcp.googleapis.com/mcp/v1"
    }
    if frozenset(seen) not in {frozenset(GOOGLE_WORKSPACE_SERVERS), frozenset(legacy_servers)}:
        raise CatalogError("Google Workspace MCP connection is invalid")
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
        raise CatalogError("Workspace resource access is invalid")
    return {
        "kind": "mcp_bundle",
        "authType": "oauth",
        "oauthProvider": "google",
        "secretArn": secret_arn,
        "oauthClientSecretArn": client_secret_arn,
        "scopes": scopes,
        "servers": normalized_servers,
        **({"resourceIds": resource_ids} if resource_ids is not None else {}),
    }


def _validate_provider_api_binding(value: dict) -> dict:
    provider = value.get("provider")
    scopes = value.get("scopes")
    secret_arn = value.get("secretArn")
    client_secret_arn = value.get("oauthClientSecretArn")
    expected = PROVIDER_API_SCOPES.get(provider)
    oauth_provider = "google" if provider == "youtube" else provider
    if (
        expected is None
        or value.get("authType") != "oauth"
        or value.get("oauthProvider") != oauth_provider
        or not isinstance(secret_arn, str)
        or not secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(client_secret_arn, str)
        or not client_secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(scopes, list)
        or set(scopes) != expected
        or len(scopes) != len(set(scopes))
    ):
        raise CatalogError("OAuth provider connection is invalid")
    site_id = value.get("siteId")
    project_keys = value.get("projectKeys")
    channel_access = value.get("channelAccess")
    resource_ids = value.get("resourceIds")
    if provider == "jira" and (
        not isinstance(site_id, str)
        or not re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", site_id
        )
    ):
        raise CatalogError("Jira site identity is invalid")
    if provider == "jira" and project_keys is not None and (
        not isinstance(project_keys, list)
        or not 1 <= len(project_keys) <= 100
        or any(
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", key)
            for key in project_keys
        )
        or len(project_keys) != len(set(project_keys))
    ):
        raise CatalogError("Jira project access is invalid")
    if provider == "microsoft_teams" and channel_access is not None and (
        not isinstance(channel_access, list)
        or not 1 <= len(channel_access) <= 100
        or any(
            not isinstance(value, str)
            or not re.fullmatch(
                r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/[A-Za-z0-9:_@.\-]{5,200}",
                value,
            )
            for value in channel_access
        )
        or len(channel_access) != len(set(channel_access))
    ):
        raise CatalogError("Teams channel access is invalid")
    patterns = {
        "slack": r"[A-Z0-9]{2,32}",
        "notion": r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
        "google_workspace": r"(?:file|sheet):[A-Za-z0-9_-]{8,256}|calendar:[A-Za-z0-9_.@%+\-]{1,256}",
    }
    if resource_ids is not None and (
        provider not in patterns
        or not isinstance(resource_ids, list)
        or not 1 <= len(resource_ids) <= 100
        or any(
            not isinstance(value, str)
            or not re.fullmatch(patterns[provider], value)
            for value in resource_ids
        )
        or len(resource_ids) != len(set(resource_ids))
    ):
        raise CatalogError("Provider resource access is invalid")
    return {
        "kind": "provider_api",
        "provider": provider,
        "authType": "oauth",
        "oauthProvider": oauth_provider,
        "secretArn": secret_arn,
        "oauthClientSecretArn": client_secret_arn,
        "scopes": scopes,
        **({"siteId": site_id.lower()} if provider == "jira" else {}),
        **(
            {"projectKeys": project_keys}
            if provider == "jira" and project_keys is not None else {}
        ),
        **(
            {"channelAccess": channel_access}
            if provider == "microsoft_teams" and channel_access is not None else {}
        ),
        **({"resourceIds": resource_ids} if resource_ids is not None else {}),
    }


def _validate_runtime_binding(value: Any) -> dict:
    if not isinstance(value, dict):
        raise CatalogError("tool runtime binding is required")
    kind = value.get("kind")
    if kind == "gateway":
        return _validate_gateway_binding(value)
    if kind == "mcp":
        return _validate_mcp_binding(value)
    if kind == "mcp_bundle":
        return _validate_mcp_bundle_binding(value)
    if kind == "provider_api":
        return _validate_provider_api_binding(value)
    allowed_names = RUNTIME_NAMES.get(kind)
    name = value.get("name")
    if not allowed_names or name not in allowed_names:
        raise CatalogError("tool runtime binding is unsupported")
    return {"kind": kind, "name": name}


def _public_skill(item: dict) -> dict:
    keys = (
        "id",
        "version",
        "name",
        "description",
        "requiredToolIds",
        "source",
        "visibility",
        "editable",
        "relationship",
        "updatedAt",
        "sourceUrl",
        "category",
        "author",
        "tags",
        "featured",
    )
    return {key: item[key] for key in keys if key in item}


def _public_tool(item: dict) -> dict:
    keys = (
        "id",
        "name",
        "description",
        "provider",
        "risk",
        "category",
        "author",
        "tags",
        "featured",
        "actions",
        "source",
        "editable",
        "relationship",
        "connectionStatus",
        "connectedAccount",
        "repositoryCount",
        "repositories",
        "updatedAt",
    )
    return {key: item[key] for key in keys if key in item}


def _public_bot_template(item: dict) -> dict:
    keys = (
        "id",
        "version",
        "name",
        "tagline",
        "prompt",
        "color",
        "skillIds",
        "toolIds",
        "category",
        "author",
        "tags",
        "featured",
        "updatedAt",
    )
    return {key: item[key] for key in keys if key in item}
