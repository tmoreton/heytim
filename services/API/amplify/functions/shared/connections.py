from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .account_state import (
    AccountInactiveError,
    UserItemConflictError,
    account_accepts_writes,
    put_user_item_while_account_active,
)
from .catalog_rules import (
    CatalogError,
    _normalize_home_assistant_endpoint,
    _public_tool,
)
from .connection_identity import _connection_id, _matching_connection, _secret_name
from .connection_lifecycle import ConnectionLifecycleMixin
from .connection_providers import (
    GMAIL_MCP_ENDPOINT,
    GMAIL_MCP_TOOLS,
    GOOGLE_WORKSPACE_MCP_SERVERS,
    SUPPORTED_CONNECTION_PROVIDER_IDS,
    connection_specs,
)
from .connection_revocation import (
    revoke_google_token,
)
from .github_app import (
    GITHUB_MCP_ENDPOINT,
    narrowed_permissions,
)
from .time import utc_now_iso as _now

MAX_CONNECTIONS = 50
MAX_CREDENTIAL_DOCUMENT_LENGTH = 64_000
CONNECTION_SAVE_ATTEMPTS = 4
CONNECTION_SPECS = connection_specs()
OAUTH_API_SCOPES = {
    provider_id: set(spec["scopes"])
    for provider_id, spec in CONNECTION_SPECS.items()
    if provider_id in {"youtube", "x"}
}
EXTERNAL_OAUTH_PROVIDER_IDS = frozenset({"slack", "microsoft", "microsoft_teams", "notion", "hubspot", "jira", "zoom"})

logger = logging.getLogger(__name__)


def _valid_secret_arn(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("arn:aws:secretsmanager:")


class ConnectionMixin(ConnectionLifecycleMixin):
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
        query = {
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
            "ExpressionAttributeValues": {
                ":pk": f"USER#{user_id}",
                ":prefix": "CONNECTION#",
            },
            "ConsistentRead": True,
        }
        items = []
        while True:
            page = self.table.query(**query)
            items.extend(page.get("Items", []))
            cursor = page.get("LastEvaluatedKey")
            if not cursor:
                return items
            query["ExclusiveStartKey"] = cursor

    def _active_connection_items(self, user_id: str) -> list[dict]:
        return [
            item
            for item in self._connection_items(user_id)
            if item.get("provider") in SUPPORTED_CONNECTION_PROVIDER_IDS
            and item.get("authType") == CONNECTION_SPECS[item["provider"]]["authType"]
        ]

    def list_connections(self, user_id: str) -> list[dict]:
        return sorted(
            (_public_tool(item) for item in self._active_connection_items(user_id)),
            key=lambda item: (
                item["name"].lower(),
                str(item.get("connectedAccount", "")).lower(),
            ),
        )

    def _get_connection(self, user_id: str, connection_id: str) -> dict | None:
        if not isinstance(connection_id, str) or not re.fullmatch(
            r"connection_[a-f0-9]{20}", connection_id
        ):
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
            Description="User OAuth or installation grant for a HeyTim connection",
            SecretString=credential,
            Tags=[
                {"Key": "heytim:resource", "Value": "connection"},
                {"Key": "heytim:connection-id", "Value": connection_id},
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
                "A provider cannot be connected while this account is being deleted"
            ) from exc

    def _secret_document(self, secret_arn: str) -> dict:
        response = self._secret_client().get_secret_value(SecretId=secret_arn)
        raw = response.get("SecretString")
        value = json.loads(raw) if isinstance(raw, str) else None
        if not isinstance(value, dict):
            raise TypeError("Connection credential is invalid")
        return value

    def _save_managed_connection(
        self,
        user_id: str,
        provider: str,
        account: str,
        credential: dict,
        runtime_factory: Callable[[str], dict],
        *,
        provider_account_id: str | None = None,
        repository_count: int | None = None,
        repositories: list[dict] | None = None,
    ) -> dict:
        spec = CONNECTION_SPECS.get(provider)
        if not spec:
            raise CatalogError("Connection provider is not supported")
        if not isinstance(account, str) or not account.strip() or len(account) > 254:
            raise CatalogError("The provider did not return a valid account")
        if provider_account_id is not None and (
            not isinstance(provider_account_id, str)
            or not provider_account_id
            or len(provider_account_id) > 200
        ):
            raise CatalogError("The provider account id is invalid")
        credential_json = json.dumps(credential, separators=(",", ":"))
        if len(credential_json) > MAX_CREDENTIAL_DOCUMENT_LENGTH:
            raise CatalogError("The provider grant is too large")
        if not self._account_accepts_connections(user_id):
            raise CatalogError(
                "A provider cannot be connected while this account is being deleted"
            )

        account_id = provider_account_id or account.strip()
        connections = self._active_connection_items(user_id)
        existing = _matching_connection(connections, provider, account_id, account.strip())
        if not existing and len(connections) >= MAX_CONNECTIONS:
            raise CatalogError(f"You can add up to {MAX_CONNECTIONS} connections")
        connection_id = (
            existing["id"] if existing else _connection_id(provider, user_id, account_id)
        )
        secret_arn = self._create_secret(user_id, connection_id, credential_json)
        previous_secret_arn = None
        item = None
        try:
            for attempt in range(CONNECTION_SAVE_ATTEMPTS):
                if attempt:
                    connections = self._active_connection_items(user_id)
                    existing = _matching_connection(
                        connections, provider, account_id, account.strip()
                    )
                    connection_id = (
                        existing["id"]
                        if existing
                        else _connection_id(provider, user_id, account_id)
                    )
                previous_secret_arn = existing.get("secretArn") if existing else None
                if existing and not _valid_secret_arn(previous_secret_arn):
                    raise CatalogError("The connection credential is invalid")

                current = _now()
                item = {
                    "pk": f"USER#{user_id}",
                    "sk": f"CONNECTION#{connection_id}",
                    "entity": "CONNECTION",
                    "id": connection_id,
                    "name": spec["name"],
                    "description": spec["description"],
                    "provider": provider,
                    "risk": spec["risk"],
                    "category": "Connections",
                    "author": "You",
                    "tags": spec["tags"],
                    "featured": False,
                    "actions": spec["actions"],
                    "source": "user",
                    "editable": True,
                    "relationship": "owner",
                    "connectionStatus": "connected",
                    "connectedAccount": account.strip(),
                    "authType": spec["authType"],
                    "hasCredential": True,
                    "secretArn": secret_arn,
                    "runtime": runtime_factory(secret_arn),
                    "createdAt": (
                        existing.get("createdAt", current) if existing else current
                    ),
                    "updatedAt": current,
                }
                if "endpoint" in spec:
                    item["endpoint"] = spec["endpoint"]
                if provider_account_id is not None:
                    item["providerAccountId"] = provider_account_id
                if repository_count is not None:
                    item["repositoryCount"] = repository_count
                if repositories is not None:
                    item["repositories"] = repositories
                try:
                    self._put_connection_while_account_active(
                        user_id,
                        item,
                        require_absent=existing is None,
                        expected_secret_arn=previous_secret_arn,
                    )
                except UserItemConflictError:
                    if attempt + 1 == CONNECTION_SAVE_ATTEMPTS:
                        raise CatalogError(
                            "The connection changed while reconnecting. Try again."
                        ) from None
                    continue
                break
        except Exception:
            self._delete_secret(secret_arn)
            raise
        if isinstance(previous_secret_arn, str):
            try:
                self._delete_secret(previous_secret_arn)
            except (BotoCoreError, ClientError):
                logger.warning(
                    "Could not schedule a superseded connection secret for deletion"
                )
        if item is None:
            raise RuntimeError("Connection was not saved")
        return _public_tool(item)

    def _revoke_google_token(self, refresh_token: str) -> None:
        revoke_google_token(
            refresh_token, urlopen=urllib.request.urlopen, logger=logger
        )

    def revoke_unused_google_token(self, refresh_token: str) -> None:
        if isinstance(refresh_token, str) and refresh_token:
            self._revoke_google_token(refresh_token)

    def revoke_unused_gmail_token(self, refresh_token: str) -> None:
        self.revoke_unused_google_token(refresh_token)

    def save_gmail_connection(
        self,
        user_id: str,
        account: str,
        refresh_token: str,
        client_secret_arn: str,
    ) -> dict:
        if not isinstance(refresh_token, str) or not refresh_token:
            raise CatalogError("Google did not return reusable Gmail access")
        if not _valid_secret_arn(client_secret_arn):
            raise CatalogError("Gmail OAuth configuration is invalid")
        try:
            return self._save_managed_connection(
                user_id,
                "gmail",
                account,
                {"refreshToken": refresh_token},
                lambda secret_arn: {
                    "kind": "mcp",
                    "endpoint": GMAIL_MCP_ENDPOINT,
                    "authType": "oauth",
                    "oauthProvider": "google",
                    "secretArn": secret_arn,
                    "oauthClientSecretArn": client_secret_arn,
                    "allowedTools": list(GMAIL_MCP_TOOLS),
                },
                provider_account_id=account.strip().casefold(),
            )
        except Exception:
            self._revoke_google_token(refresh_token)
            raise

    def save_home_assistant_connection(
        self, user_id: str, instance_url: str, access_token: str
    ) -> dict:
        endpoint = _normalize_home_assistant_endpoint(instance_url)
        if (
            not isinstance(access_token, str)
            or not 20 <= len(access_token) <= 4096
            or not re.fullmatch(r"[A-Za-z0-9._~=-]+", access_token)
        ):
            raise CatalogError("Home Assistant access token is invalid")
        hostname = urllib.parse.urlsplit(endpoint).hostname or "Home Assistant"
        account_id = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
        return self._save_managed_connection(
            user_id,
            "home_assistant",
            hostname,
            {"accessToken": access_token},
            lambda secret_arn: {
                "kind": "mcp",
                "endpoint": endpoint,
                "authType": "home_assistant_token",
                "secretArn": secret_arn,
            },
            provider_account_id=account_id,
        )

    def save_oauth_api_connection(
        self,
        user_id: str,
        provider: str,
        account: str,
        provider_account_id: str,
        refresh_token: str,
        client_secret_arn: str,
        scopes: list[str],
        *,
        access_token: str | None = None,
        expires_at: int | None = None,
    ) -> dict:
        expected_scopes = OAUTH_API_SCOPES.get(provider)
        if expected_scopes is None:
            raise CatalogError("OAuth API provider is not supported")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise CatalogError("The provider did not return reusable access")
        if not _valid_secret_arn(client_secret_arn):
            raise CatalogError("OAuth configuration is invalid")
        if (
            not isinstance(scopes, list)
            or not scopes
            or len(scopes) != len(set(scopes))
            or any(not isinstance(scope, str) or len(scope) > 200 for scope in scopes)
            or set(scopes) != expected_scopes
        ):
            raise CatalogError("OAuth scopes are invalid")
        credential: dict[str, Any] = {"refreshToken": refresh_token}
        if isinstance(access_token, str) and access_token:
            credential["accessToken"] = access_token
        if isinstance(expires_at, int):
            credential["expiresAt"] = expires_at
        oauth_provider = "google" if provider == "youtube" else "x"
        try:
            return self._save_managed_connection(
                user_id,
                provider,
                account,
                credential,
                lambda secret_arn: {
                    "kind": "provider_api",
                    "provider": provider,
                    "authType": "oauth",
                    "oauthProvider": oauth_provider,
                    "secretArn": secret_arn,
                    "oauthClientSecretArn": client_secret_arn,
                    "scopes": scopes,
                },
                provider_account_id=provider_account_id,
            )
        except Exception:
            try:
                if provider == "youtube":
                    self._revoke_google_token(refresh_token)
                else:
                    self._revoke_x_token(refresh_token, client_secret_arn)
            except (BotoCoreError, ClientError, KeyError, TypeError, ValueError):
                logger.warning("Could not revoke unused %s OAuth access", provider)
            raise

    def save_google_workspace_connection(
        self,
        user_id: str,
        account: str,
        provider_account_id: str,
        refresh_token: str,
        client_secret_arn: str,
        scopes: list[str],
    ) -> dict:
        spec = CONNECTION_SPECS["google_workspace"]
        expected_scopes = set(spec["scopes"])
        if not isinstance(refresh_token, str) or not refresh_token:
            raise CatalogError("Google did not return reusable Workspace access")
        if not _valid_secret_arn(client_secret_arn):
            raise CatalogError("Google Workspace OAuth configuration is invalid")
        if (
            not isinstance(scopes, list)
            or len(scopes) != len(set(scopes))
            or set(scopes) != expected_scopes
        ):
            raise CatalogError("Google Workspace OAuth scopes are invalid")
        servers = [
            {
                "endpoint": server["endpoint"],
                "allowedTools": list(server["allowedTools"]),
            }
            for server in GOOGLE_WORKSPACE_MCP_SERVERS
        ]
        try:
            return self._save_managed_connection(
                user_id,
                "google_workspace",
                account,
                {"refreshToken": refresh_token},
                lambda secret_arn: {
                    "kind": "mcp_bundle",
                    "authType": "oauth",
                    "oauthProvider": "google",
                    "secretArn": secret_arn,
                    "oauthClientSecretArn": client_secret_arn,
                    "servers": servers,
                    "scopes": scopes,
                },
                provider_account_id=provider_account_id,
            )
        except Exception:
            self._revoke_google_token(refresh_token)
            raise

    def save_external_oauth_connection(
        self,
        user_id: str,
        provider: str,
        account: str,
        provider_account_id: str,
        credential: dict,
        client_secret_arn: str,
        scopes: list[str],
    ) -> dict:
        if provider not in EXTERNAL_OAUTH_PROVIDER_IDS:
            raise CatalogError("OAuth provider is not supported")
        expected_scopes = set(CONNECTION_SPECS[provider]["scopes"])
        if not _valid_secret_arn(client_secret_arn):
            raise CatalogError("OAuth configuration is invalid")
        if (
            not isinstance(scopes, list)
            or len(scopes) != len(set(scopes))
            or set(scopes) != expected_scopes
        ):
            raise CatalogError("OAuth scopes are invalid")
        if not isinstance(credential, dict):
            raise CatalogError("OAuth credential is invalid")
        access_token = credential.get("accessToken")
        refresh_token = credential.get("refreshToken")
        expires_at = credential.get("expiresAt")
        if not isinstance(access_token, str) or not access_token:
            raise CatalogError("OAuth access token is invalid")
        if provider in {"slack", "microsoft", "microsoft_teams", "hubspot", "jira", "zoom"} and (
            not isinstance(refresh_token, str)
            or not refresh_token
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or expires_at <= 0
        ):
            raise CatalogError("OAuth refresh grant is invalid")
        if refresh_token is not None and (
            not isinstance(refresh_token, str) or not refresh_token
        ):
            raise CatalogError("OAuth refresh grant is invalid")
        return self._save_managed_connection(
            user_id,
            provider,
            account,
            credential,
            lambda secret_arn: {
                "kind": "provider_api",
                "provider": provider,
                "authType": "oauth",
                "oauthProvider": provider,
                "secretArn": secret_arn,
                "oauthClientSecretArn": client_secret_arn,
                "scopes": scopes,
                **({"siteId": provider_account_id} if provider == "jira" else {}),
            },
            provider_account_id=provider_account_id,
        )

    def save_github_connection(
        self,
        user_id: str,
        account: str,
        installation_id: str,
        repositories: list[dict],
        permissions: dict[str, str],
        app_secret_arn: str,
    ) -> dict:
        if not re.fullmatch(r"[0-9]{1,20}", installation_id):
            raise CatalogError("GitHub installation id is invalid")
        if (
            not isinstance(repositories, list)
            or not repositories
            or len(repositories) > 500
            or any(
                not isinstance(value, dict)
                or type(value.get("id")) is not int
                or value["id"] <= 0
                or not isinstance(value.get("name"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["name"])
                or len(value["name"]) > 200
                for value in repositories
            )
        ):
            raise CatalogError("GitHub repository selection is invalid")
        repository_ids = [value["id"] for value in repositories]
        if len(repository_ids) != len(set(repository_ids)):
            raise CatalogError("GitHub repository selection is invalid")
        if not _valid_secret_arn(app_secret_arn):
            raise CatalogError("GitHub App configuration is invalid")
        try:
            safe_permissions = narrowed_permissions(permissions)
        except (TypeError, ValueError) as exc:
            raise CatalogError("GitHub App permissions are invalid") from exc
        if safe_permissions != permissions:
            raise CatalogError("GitHub App permissions are invalid")
        return self._save_managed_connection(
            user_id,
            "github",
            account,
            {
                "installationId": installation_id,
                "repositoryIds": repository_ids,
                "permissions": safe_permissions,
            },
            lambda secret_arn: {
                "kind": "mcp",
                "endpoint": GITHUB_MCP_ENDPOINT,
                "authType": "github_app",
                "secretArn": secret_arn,
                "appSecretArn": app_secret_arn,
            },
            provider_account_id=installation_id,
            repository_count=len(repository_ids),
            repositories=[
                {"id": value["id"], "name": value["name"]}
                for value in repositories
            ],
        )
