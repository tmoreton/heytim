from __future__ import annotations

import ipaddress
import re
import urllib.parse
from datetime import UTC, datetime
from typing import Any

MAX_SKILLS_PER_BOT = 12
MAX_TOOLS_PER_BOT = 12
MAX_SKILL_INSTRUCTIONS = 20_000
MAX_CATALOG_TAGS = 6
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TOOL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
RUNTIME_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,127}$")
RUNTIME_NAMES = {
    "agentcore": {"browser", "code_interpreter"},
    "local": {"calculator", "current_time"},
    "stan_builtin": {"web_fetch"},
    "stan_plugin": {"todos"},
    "stan_subagent": {"generalist"},
}
TOOL_RISKS = {"read", "sandbox", "interactive"}
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


class CatalogError(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


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
    return urllib.parse.urlunsplit(("https", hostname, parsed.path or "/", "", ""))


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
        "author": _validate_text(value.get("author", "FroggyBot"), "author", 80),
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


def _validate_header_binding(
    value: dict, endpoint: str, auth_type: Any, secret_arn: Any
) -> dict:
    header_name = value.get("headerName")
    header_prefix = value.get("headerPrefix", "")
    if (
        auth_type not in {"bearer", "api_key"}
        or not isinstance(secret_arn, str)
        or not secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(header_name, str)
        or not re.fullmatch(r"^(Authorization|X-[A-Za-z0-9-]{1,60})$", header_name)
        or header_prefix not in {"", "Bearer "}
    ):
        raise CatalogError("MCP connection authentication is invalid")
    return {
        "kind": "mcp",
        "endpoint": endpoint,
        "authType": auth_type,
        "secretArn": secret_arn,
        "headerName": header_name,
        "headerPrefix": header_prefix,
    }


def _validate_mcp_binding(value: dict) -> dict:
    endpoint = _validate_mcp_endpoint(value.get("endpoint"))
    auth_type = value.get("authType", "none")
    if auth_type == "none":
        return {"kind": "mcp", "endpoint": endpoint, "authType": "none"}
    secret_arn = value.get("secretArn")
    if auth_type == "oauth":
        return _validate_oauth_binding(value, endpoint, secret_arn)
    return _validate_header_binding(value, endpoint, auth_type, secret_arn)


def _validate_runtime_binding(value: Any) -> dict:
    if not isinstance(value, dict):
        raise CatalogError("tool runtime binding is required")
    kind = value.get("kind")
    if kind == "gateway":
        return _validate_gateway_binding(value)
    if kind == "mcp":
        return _validate_mcp_binding(value)
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
        "endpoint",
        "authType",
        "headerName",
        "hasCredential",
        "connectionStatus",
        "connectedAccount",
        "updatedAt",
    )
    return {key: item[key] for key in keys if key in item}
