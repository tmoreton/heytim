from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from .catalog_rules import CatalogError
from .connection_providers import SUPPORTED_CONNECTION_PROVIDER_IDS
from .connection_revocation import (
    revoke_external_access,
    revoke_github_access,
    revoke_plaid_access,
    revoke_quickbooks_access,
    revoke_x_token,
)

EXTERNAL_OAUTH_PROVIDER_IDS = frozenset({
    "slack", "microsoft", "microsoft_teams", "notion", "hubspot", "jira", "zoom"
})
logger = logging.getLogger("shared.connections")


def _valid_secret_arn(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("arn:aws:secretsmanager:")


class ConnectionLifecycleMixin:
    table: Any

    def _secret_client(self): ...

    def _secret_document(self, secret_arn: str) -> dict: ...

    def _get_connection(self, user_id: str, connection_id: str) -> dict | None: ...

    def _delete_secret(self, secret_arn: str) -> None: ...

    def _revoke_google_token(self, refresh_token: str) -> None: ...

    def _revoke_x_token(self, refresh_token: str, config_arn: str) -> None:
        revoke_x_token(
            refresh_token,
            config_arn,
            valid_secret_arn=_valid_secret_arn,
            secret_document=self._secret_document,
            urlopen=urllib.request.urlopen,
            logger=logger,
        )

    def revoke_unused_x_token(self, refresh_token: str, config_arn: str) -> None:
        if isinstance(refresh_token, str) and refresh_token:
            self._revoke_x_token(refresh_token, config_arn)

    def revoke_unused_external_token(
        self, provider: str, credential: dict, config_arn: str
    ) -> None:
        revoke_external_access(
            provider,
            credential,
            config_arn,
            valid_secret_arn=_valid_secret_arn,
            secret_document=self._secret_document,
            urlopen=urllib.request.urlopen,
            logger=logger,
        )

    def revoke_unused_quickbooks_token(
        self, credential: dict, config_arn: str
    ) -> None:
        revoke_quickbooks_access(
            credential,
            config_arn,
            valid_secret_arn=_valid_secret_arn,
            secret_document=self._secret_document,
            urlopen=urllib.request.urlopen,
            logger=logger,
        )

    def _revoke_x_access(self, credential: dict, item: dict) -> None:
        refresh_token = credential.get("refreshToken")
        config_arn = item.get("runtime", {}).get("oauthClientSecretArn")
        if isinstance(refresh_token, str) and isinstance(config_arn, str):
            self._revoke_x_token(refresh_token, config_arn)

    def _revoke_github_access(self, credential: dict, item: dict) -> None:
        revoke_github_access(
            credential,
            item,
            valid_secret_arn=_valid_secret_arn,
            secret_document=self._secret_document,
            urlopen=urllib.request.urlopen,
            logger=logger,
        )

    def _revoke_provider_access(self, item: dict) -> None:
        provider = item.get("provider")
        secret_arn = item.get("secretArn")
        if provider not in SUPPORTED_CONNECTION_PROVIDER_IDS or not _valid_secret_arn(
            secret_arn
        ):
            return
        try:
            credential = self._secret_document(secret_arn)
            if provider in {"gmail", "youtube", "google_workspace"}:
                refresh_token = credential.get("refreshToken")
                if isinstance(refresh_token, str) and refresh_token:
                    self._revoke_google_token(refresh_token)
            elif provider == "x":
                self._revoke_x_access(credential, item)
            elif provider == "github":
                self._revoke_github_access(credential, item)
            elif provider in EXTERNAL_OAUTH_PROVIDER_IDS:
                config_arn = item.get("runtime", {}).get("oauthClientSecretArn")
                if isinstance(config_arn, str):
                    self.revoke_unused_external_token(provider, credential, config_arn)
            elif provider == "quickbooks":
                config_arn = item.get("runtime", {}).get("oauthClientSecretArn")
                if isinstance(config_arn, str):
                    self.revoke_unused_quickbooks_token(credential, config_arn)
            elif provider == "plaid":
                runtime = item.get("runtime", {})
                config_arn = runtime.get("appSecretArn")
                environment = runtime.get("environment")
                if isinstance(config_arn, str) and isinstance(environment, str):
                    revoke_plaid_access(
                        credential,
                        config_arn,
                        environment,
                        valid_secret_arn=_valid_secret_arn,
                        secret_document=self._secret_document,
                        urlopen=urllib.request.urlopen,
                        logger=logger,
                    )
        except (
            BotoCoreError,
            ClientError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            logger.warning(
                "Could not revoke %s access; removing local access", provider
            )
        except self._secret_client().exceptions.ResourceNotFoundException:
            logger.warning(
                "Could not revoke %s access; removing local access", provider
            )

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
        self._revoke_provider_access(item)
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
            self._revoke_provider_access(item)
            secret_arn = item.get("secretArn")
            if isinstance(secret_arn, str):
                self._delete_secret(secret_arn)
        return len(connections)
