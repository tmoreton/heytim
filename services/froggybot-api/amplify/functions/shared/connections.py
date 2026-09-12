from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .account_state import (
    AccountInactiveError,
    UserItemConflictError,
    account_accepts_writes,
    put_user_item_while_account_active,
)
from .catalog_rules import (
    GMAIL_MCP_ENDPOINT,
    GMAIL_MCP_TOOLS,
    CatalogError,
    _public_tool,
    _validate_mcp_endpoint,
    _validate_text,
    _validate_tool_id,
)
from .time import utc_now_iso as _now

AUTH_TYPES = {"none", "bearer", "api_key"}
HEADER_PATTERN = re.compile(r"^(Authorization|X-[A-Za-z0-9-]{1,60})$")
MAX_CONNECTIONS = 12
MAX_CREDENTIAL_LENGTH = 4_096
# Public OAuth endpoint, not a password or token value.
GOOGLE_TOKEN_REVOKE_URL = "https://oauth2.googleapis.com/revoke"  # nosec B105
GOOGLE_TOKEN_REVOKE_TIMEOUT_SECONDS = 4
GMAIL_SAVE_ATTEMPTS = 4

logger = logging.getLogger(__name__)


def _secret_name(user_id: str, connection_id: str) -> str:
    owner = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
    revision = uuid.uuid4().hex[:12]
    return f"frogbot/connections/{owner}/{connection_id}-{revision}"


def _gmail_connection_id(user_id: str) -> str:
    digest = hashlib.sha256(f"gmail:{user_id}".encode()).hexdigest()[:20]
    return f"connection_{digest}"


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
            ConsistentRead=True,
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

    def _account_accepts_connections(self, user_id: str) -> bool:
        return account_accepts_writes(self.table, user_id)

    def _put_connection_while_account_active(
        self,
        user_id: str,
        item: dict,
        *,
        require_absent: bool,
        expected_secret_arn: str | None,
    ) -> None:
        try:
            put_user_item_while_account_active(
                self.table,
                user_id,
                item,
                require_absent=require_absent,
                expected_secret_arn=expected_secret_arn,
            )
        except AccountInactiveError as exc:
            raise CatalogError(
                "Gmail cannot be connected while this account is being deleted"
            ) from exc

    def _revoke_google_token(self, refresh_token: str) -> None:
        request = urllib.request.Request(
            GOOGLE_TOKEN_REVOKE_URL,
            data=urllib.parse.urlencode({"token": refresh_token}).encode("utf-8"),
            headers={"content-type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # nosec B310
                request, timeout=GOOGLE_TOKEN_REVOKE_TIMEOUT_SECONDS
            ):
                pass
        except urllib.error.HTTPError as error:
            if error.code == 400:
                logger.info(
                    "Google reported that the Gmail credential was already invalid; "
                    "continuing local connection removal"
                )
            else:
                logger.warning(
                    "Google Gmail revocation failed; continuing local connection removal"
                )
        except (urllib.error.URLError, TimeoutError, OSError):
            logger.warning(
                "Google Gmail revocation was unavailable; "
                "continuing local connection removal"
            )

    def revoke_unused_gmail_token(self, refresh_token: str) -> None:
        if isinstance(refresh_token, str) and refresh_token:
            self._revoke_google_token(refresh_token)

    def _revoke_gmail_access(self, item: dict) -> None:
        if item.get("provider") != "gmail":
            return
        secret_arn = item.get("secretArn")
        if not isinstance(secret_arn, str):
            return

        client = self._secret_client()
        try:
            response = client.get_secret_value(SecretId=secret_arn)
            if not isinstance(response, dict):
                raise TypeError("Gmail credential response is invalid")
            raw = response.get("SecretString")
            value = json.loads(raw) if isinstance(raw, str) else None
            refresh_token = (
                value.get("refreshToken") if isinstance(value, dict) else None
            )
            if not isinstance(refresh_token, str):
                raise TypeError("Gmail refresh token is unavailable")
            if not refresh_token:
                raise ValueError("Gmail refresh token is unavailable")
        except (
            client.exceptions.ResourceNotFoundException,
            BotoCoreError,
            ClientError,
            TypeError,
            ValueError,
        ):
            logger.warning(
                "Could not read the Gmail credential for revocation; "
                "continuing local connection removal"
            )
            return

        self._revoke_google_token(refresh_token)

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

    def save_gmail_connection(
        self,
        user_id: str,
        account: str,
        refresh_token: str,
        client_secret_arn: str,
    ) -> dict:
        if not isinstance(refresh_token, str) or not refresh_token:
            raise CatalogError("Google did not return reusable Gmail access")
        credential = json.dumps(
            {"refreshToken": refresh_token}, separators=(",", ":")
        )
        secret_arn = None
        try:
            if not self._account_accepts_connections(user_id):
                raise CatalogError(
                    "Gmail cannot be connected while this account is being deleted"
                )
            if (
                not isinstance(account, str)
                or "@" not in account
                or len(account) > 254
            ):
                raise CatalogError("Google did not return a valid Gmail account")
            if (
                not isinstance(client_secret_arn, str)
                or not client_secret_arn.startswith("arn:aws:secretsmanager:")
            ):
                raise CatalogError("Gmail OAuth configuration is invalid")

            connections = self._connection_items(user_id)
            existing = next(
                (item for item in connections if item.get("provider") == "gmail"),
                None,
            )
            if not existing and len(connections) >= MAX_CONNECTIONS:
                raise CatalogError(
                    f"You can add up to {MAX_CONNECTIONS} private connections"
                )
            connection_id = (
                existing["id"] if existing else _gmail_connection_id(user_id)
            )
            secret_arn = self._create_secret(user_id, connection_id, credential)
            for attempt in range(GMAIL_SAVE_ATTEMPTS):
                if attempt:
                    connections = self._connection_items(user_id)
                    existing = next(
                        (
                            value
                            for value in connections
                            if value.get("provider") == "gmail"
                        ),
                        None,
                    )
                    connection_id = (
                        existing["id"]
                        if existing
                        else _gmail_connection_id(user_id)
                    )
                previous_secret_arn = (
                    existing.get("secretArn") if existing else None
                )
                if existing and not isinstance(previous_secret_arn, str):
                    raise CatalogError("The Gmail connection credential is invalid")

                current = _now()
                runtime = {
                    "kind": "mcp",
                    "endpoint": GMAIL_MCP_ENDPOINT,
                    "authType": "oauth",
                    "oauthProvider": "google",
                    "secretArn": secret_arn,
                    "oauthClientSecretArn": client_secret_arn,
                    "allowedTools": list(GMAIL_MCP_TOOLS),
                }
                item = {
                    "pk": f"USER#{user_id}",
                    "sk": f"CONNECTION#{connection_id}",
                    "entity": "CONNECTION",
                    "id": connection_id,
                    "name": "Gmail",
                    "description": (
                        "Search and summarize email, and create drafts for review."
                    ),
                    "endpoint": GMAIL_MCP_ENDPOINT,
                    "provider": "gmail",
                    "risk": "interactive",
                    "category": "Connections",
                    "author": "You",
                    "tags": ["private", "gmail", "mcp"],
                    "featured": False,
                    "actions": ["Search email", "Read threads", "Create drafts"],
                    "source": "user",
                    "editable": True,
                    "relationship": "owner",
                    "connectionStatus": "connected",
                    "connectedAccount": account,
                    "authType": "oauth",
                    "hasCredential": True,
                    "secretArn": secret_arn,
                    "runtime": runtime,
                    "createdAt": (
                        existing.get("createdAt", current) if existing else current
                    ),
                    "updatedAt": current,
                }
                try:
                    self._put_connection_while_account_active(
                        user_id,
                        item,
                        require_absent=existing is None,
                        expected_secret_arn=previous_secret_arn,
                    )
                except UserItemConflictError:
                    if attempt + 1 == GMAIL_SAVE_ATTEMPTS:
                        raise CatalogError(
                            "The Gmail connection changed while reconnecting. Try again."
                        ) from None
                    continue
                break
        except Exception:
            self._revoke_google_token(refresh_token)
            if isinstance(secret_arn, str):
                self._delete_secret(secret_arn)
            raise
        if isinstance(previous_secret_arn, str):
            try:
                self._delete_secret(previous_secret_arn)
            except (BotoCoreError, ClientError):
                logger.warning(
                    "Could not schedule the superseded Gmail credential for deletion"
                )
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
        self._revoke_gmail_access(item)
        secret_arn = item.get("secretArn")
        if isinstance(secret_arn, str):
            self._delete_secret(secret_arn)
        self.table.delete_item(
            Key={"pk": f"USER#{user_id}", "sk": f"CONNECTION#{connection_id}"}
        )
        result = {"deleted": True}
        if isinstance(secret_arn, str):
            result["credentialDeletionWindowDays"] = 7
        return result

    def delete_connection_secrets(self, items: list[dict]) -> int:
        connections = [item for item in items if item.get("entity") == "CONNECTION"]
        for item in connections:
            self._revoke_gmail_access(item)
            secret_arn = item.get("secretArn")
            if isinstance(secret_arn, str):
                self._delete_secret(secret_arn)
        return len(connections)
