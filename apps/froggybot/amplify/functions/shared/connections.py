from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from .catalog_rules import (
    CatalogError,
    _now,
    _public_tool,
    _validate_mcp_endpoint,
    _validate_text,
    _validate_tool_id,
)

AUTH_TYPES = {"none", "bearer", "api_key"}
HEADER_PATTERN = re.compile(r"^(Authorization|X-[A-Za-z0-9-]{1,60})$")
MAX_CONNECTIONS = 12
MAX_CREDENTIAL_LENGTH = 4_096


def _secret_name(user_id: str, connection_id: str) -> str:
    owner = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
    revision = uuid.uuid4().hex[:12]
    return f"frogbot/connections/{owner}/{connection_id}-{revision}"


def _auth_values(value: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    auth_type = value.get("authType", previous.get("authType", "none"))
    if auth_type not in AUTH_TYPES:
        raise CatalogError("Choose no authentication, bearer token, or API key")
    if auth_type == "none":
        return {"authType": "none"}
    if auth_type == "bearer":
        return {
            "authType": auth_type,
            "headerName": "Authorization",
            "headerPrefix": "Bearer ",
        }
    header = value.get("headerName", previous.get("headerName", "X-API-Key"))
    if not isinstance(header, str) or not HEADER_PATTERN.fullmatch(header.strip()):
        raise CatalogError("API key header must be Authorization or start with X-")
    return {
        "authType": auth_type,
        "headerName": header.strip(),
        "headerPrefix": "",
    }


class ConnectionMixin:
    table: Any
    secrets_manager: Any

    def _secret_client(self):
        if self.secrets_manager is None:
            import boto3
            from botocore.config import Config

            self.secrets_manager = boto3.client(
                "secretsmanager",
                config=Config(
                    retries={"total_max_attempts": 4, "mode": "adaptive"},
                    connect_timeout=3,
                    read_timeout=10,
                ),
            )
        return self.secrets_manager

    def _connection_items(self, user_id: str) -> list[dict]:
        return self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#{user_id}",
                ":prefix": "CONNECTION#",
            },
        ).get("Items", [])

    def list_connections(self, user_id: str) -> list[dict]:
        return sorted(
            (_public_tool(item) for item in self._connection_items(user_id)),
            key=lambda item: item["name"].lower(),
        )

    def _get_connection(self, user_id: str, connection_id: str) -> dict | None:
        connection_id = _validate_tool_id(connection_id)
        if not connection_id.startswith("connection_"):
            raise CatalogError("Connection id is invalid")
        return self.table.get_item(
            Key={
                "pk": f"USER#{user_id}",
                "sk": f"CONNECTION#{connection_id}",
            },
            ConsistentRead=True,
        ).get("Item")

    def _create_secret(self, user_id: str, connection_id: str, credential: str) -> str:
        response = self._secret_client().create_secret(
            Name=_secret_name(user_id, connection_id),
            Description="User-managed credential for a private FroggyBot MCP connection",
            SecretString=credential,
            Tags=[
                {"Key": "frogbot:resource", "Value": "connection"},
                {"Key": "frogbot:connection-id", "Value": connection_id},
            ],
        )
        arn = response.get("ARN")
        if not isinstance(arn, str) or not arn:
            raise RuntimeError("Secrets Manager did not return a secret ARN")
        return arn

    def _delete_secret(self, secret_arn: str) -> None:
        client = self._secret_client()
        try:
            client.delete_secret(SecretId=secret_arn, RecoveryWindowInDays=7)
        except client.exceptions.ResourceNotFoundException:
            return

    def save_connection(
        self, user_id: str, value: dict, connection_id: str | None = None
    ) -> dict:
        existing = None
        if connection_id:
            existing = self._get_connection(user_id, connection_id)
            if not existing:
                raise CatalogError("Connection not found")
        elif len(self._connection_items(user_id)) >= MAX_CONNECTIONS:
            raise CatalogError(
                f"You can add up to {MAX_CONNECTIONS} private connections"
            )

        name = _validate_text(
            value.get("name", existing and existing["name"]), "name", 80
        )
        description = _validate_text(
            value.get("description", existing and existing["description"]),
            "description",
            240,
        )
        endpoint = _validate_mcp_endpoint(
            value.get("endpoint", existing and existing["endpoint"])
        )
        risk = value.get("risk", existing and existing.get("risk", "interactive"))
        if risk not in {"read", "interactive"}:
            raise CatalogError(
                "Connection access must be read-only or able to make changes"
            )
        auth = _auth_values(value, existing)
        credential = value.get("credential")
        if credential is not None and (
            not isinstance(credential, str)
            or not credential.strip()
            or len(credential) > MAX_CREDENTIAL_LENGTH
        ):
            raise CatalogError("Credential must be between 1 and 4,096 characters")

        connection_id = connection_id or f"connection_{uuid.uuid4().hex[:20]}"
        previous_secret = existing.get("secretArn") if existing else None
        secret_arn = previous_secret
        created_secret = False
        if auth["authType"] == "none":
            secret_arn = None
        elif credential is not None:
            if previous_secret:
                self._secret_client().put_secret_value(
                    SecretId=previous_secret, SecretString=credential
                )
            else:
                secret_arn = self._create_secret(user_id, connection_id, credential)
                created_secret = True
        elif not previous_secret:
            raise CatalogError("Enter the credential for this connection")

        current = _now()
        runtime = {
            "kind": "mcp",
            "endpoint": endpoint,
            **auth,
        }
        if secret_arn:
            runtime["secretArn"] = secret_arn
        item = {
            "pk": f"USER#{user_id}",
            "sk": f"CONNECTION#{connection_id}",
            "entity": "CONNECTION",
            "id": connection_id,
            "name": name,
            "description": description,
            "endpoint": endpoint,
            "provider": "mcp",
            "risk": risk,
            "category": "Connections",
            "author": "You",
            "tags": ["private", "mcp"],
            "featured": False,
            "actions": ["Use server tools"],
            "source": "user",
            "editable": True,
            "relationship": "owner",
            "connectionStatus": "connected",
            "runtime": runtime,
            "createdAt": existing.get("createdAt", current) if existing else current,
            "updatedAt": current,
            **auth,
        }
        if secret_arn:
            item["secretArn"] = secret_arn
            item["hasCredential"] = True
        try:
            self.table.put_item(Item=item)
        except Exception:
            if created_secret and secret_arn:
                self._delete_secret(secret_arn)
            raise
        if previous_secret and auth["authType"] == "none":
            self._delete_secret(previous_secret)
        return _public_tool(item)

    def delete_connection(self, user_id: str, connection_id: str) -> dict:
        item = self._get_connection(user_id, connection_id)
        if not item:
            raise CatalogError("Connection not found")
        user_items = self.table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": f"USER#{user_id}"},
        ).get("Items", [])
        used_by = [
            value.get("name", "an item")
            for value in user_items
            if connection_id in value.get("toolIds", [])
            or connection_id in value.get("requiredToolIds", [])
        ]
        if used_by:
            raise CatalogError(
                f"Remove this connection from {used_by[0]} before deleting it"
            )
        secret_arn = item.get("secretArn")
        if isinstance(secret_arn, str):
            self._delete_secret(secret_arn)
        self.table.delete_item(
            Key={"pk": f"USER#{user_id}", "sk": f"CONNECTION#{connection_id}"}
        )
        return {"deleted": True, "recoverableForDays": 7}

    def delete_connection_secrets(self, items: list[dict]) -> int:
        connections = [item for item in items if item.get("entity") == "CONNECTION"]
        for item in connections:
            secret_arn = item.get("secretArn")
            if isinstance(secret_arn, str):
                self._delete_secret(secret_arn)
        return len(connections)
