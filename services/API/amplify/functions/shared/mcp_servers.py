from __future__ import annotations

import hashlib
import re

from .catalog_rules import CatalogError, _validate_mcp_endpoint


class MCPServerConnectionMixin:
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
