from __future__ import annotations

import hashlib
import re

from .catalog_rules import CatalogError, _public_tool, _validate_mcp_endpoint
from .mcp_discovery import discover_mcp_server
from .time import utc_now_iso


class MCPServerConnectionMixin:
    def rename_mcp_server_connection(
        self, user_id: str, connection_id: str, name: str
    ) -> dict:
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise CatalogError("MCP server name is required (80 characters maximum)")
        item = self._get_connection(user_id, connection_id)
        if not item or item.get("provider") not in {"mcp_server", "home_assistant"}:
            raise CatalogError("MCP server not found")
        updated = {**item, "connectedAccount": name.strip(), "updatedAt": utc_now_iso()}
        if item["provider"] == "home_assistant":
            updated["displayName"] = name.strip()
        self._put_connection_while_account_active(
            user_id, updated, require_absent=False,
            expected_secret_arn=item.get("secretArn"),
        )
        return _public_tool(updated)

    def save_mcp_server_connection(
        self, user_id: str, name: str, endpoint_url: str, access_token: str,
        *, approved_tools: dict | None = None, auth_type: str = "bearer_token",
    ) -> dict:
        endpoint = _validate_mcp_endpoint(endpoint_url)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise CatalogError("MCP server name is required (80 characters maximum)")
        if auth_type not in {"bearer_token", "none"}:
            raise CatalogError("Choose access token or no authentication")
        if auth_type == "none" and access_token not in (None, ""):
            raise CatalogError("An anonymous connection cannot contain a token")
        if auth_type == "bearer_token" and (
            not isinstance(access_token, str)
            or not 1 <= len(access_token) <= 4096
            or not re.fullmatch(r"[A-Za-z0-9._~+/-]+={0,3}", access_token)
        ):
            raise CatalogError("MCP access token is invalid")
        metadata = {"hasCredential": auth_type != "none"}
        if approved_tools is not None:
            if (not isinstance(approved_tools, dict) or not 1 <= len(approved_tools) <= 100
                    or any(not isinstance(k, str) or not isinstance(v, str)
                           or not re.fullmatch(r"[a-f0-9]{64}", v) for k, v in approved_tools.items())):
                raise CatalogError("Select at least one discovered MCP tool")
            discovery = discover_mcp_server(endpoint, access_token or None)
            discovered = {tool["name"]: tool["digest"] for tool in discovery["tools"]}
            if any(discovered.get(k) != v for k, v in approved_tools.items()):
                raise CatalogError("MCP tools changed. Test the connection and review the tools again.")
            metadata.update({"mcpServerName": discovery["serverName"],
                        "mcpVerifiedAt": utc_now_iso(), "mcpToolCount": len(approved_tools)})
        account_id = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
        return self._save_managed_connection(
            user_id,
            "mcp_server",
            name.strip(),
            {"accessToken": access_token} if access_token else {},
            lambda secret_arn: {
                "kind": "mcp",
                "endpoint": endpoint,
                "authType": auth_type,
                **({"secretArn": secret_arn} if auth_type != "none" else {}),
                **({"approvedTools": approved_tools, "requireActionApproval": True}
                   if approved_tools is not None else {}),
            },
            provider_account_id=account_id,
            metadata=metadata,
        )
