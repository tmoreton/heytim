from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
from typing import Any

import boto3
from botocore.config import Config
from strands.tools.mcp.mcp_client import MCPClient

SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/connections/[a-f0-9]{24}/"
    r"connection_[a-f0-9]{20}-[a-f0-9]{12}-[A-Za-z0-9]+$"
)
HEADER_PATTERN = re.compile(r"^(Authorization|X-[A-Za-z0-9-]{1,60})$")
_secrets_manager = None


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


def connection_client(binding: dict) -> MCPClient:
    headers = None
    if binding["authType"] != "none":
        credential = _secret_value(binding["secretArn"])
        headers = {binding["headerName"]: f"{binding['headerPrefix']}{credential}"}
    return MCPClient(
        url=binding["endpoint"],
        headers=headers,
        prefix=binding["id"],
        startup_timeout=15,
        continue_on_error=False,
        application_name="FroggyBot",
    )
