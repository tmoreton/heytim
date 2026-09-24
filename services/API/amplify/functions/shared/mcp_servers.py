from __future__ import annotations

import hashlib
import re

from .catalog_rules import CatalogError, _public_tool, _validate_mcp_endpoint
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
        self, user_id: str, name: str, endpoint_url: str, access_token: str
    ) -> dict:
        endpoint = _validate_mcp_endpoint(endpoint_url)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise CatalogError("MCP server name is required (80 characters maximum)")
        if (
            not isinstance(access_token, str)
            or not 20 <= len(access_token) <= 4096
            or not re.fullmatch(r"[A-Za-z0-9._~+/-]+={0,3}", access_token)
        ):
            raise CatalogError("MCP access token is invalid")
        account_id = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
        return self._save_managed_connection(
            user_id,
            "mcp_server",
            name.strip(),
            {"accessToken": access_token},
            lambda secret_arn: {
                "kind": "mcp",
                "endpoint": endpoint,
                "authType": "bearer_token",
                "secretArn": secret_arn,
            },
            provider_account_id=account_id,
        )
