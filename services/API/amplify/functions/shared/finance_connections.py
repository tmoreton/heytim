from __future__ import annotations

import re
from typing import Any

from .catalog_rules import CatalogError


def _valid_secret_arn(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("arn:aws:secretsmanager:")


class FinanceConnectionMixin:
    def _save_managed_connection(self, *args: Any, **kwargs: Any) -> dict: ...

    def save_quickbooks_connection(
        self,
        user_id: str,
        account: str,
        realm_id: str,
        credential: dict,
        client_secret_arn: str,
        environment: str,
    ) -> dict:
        if not re.fullmatch(r"[0-9]{1,32}", realm_id):
            raise CatalogError("QuickBooks company identity is invalid")
        if not _valid_secret_arn(client_secret_arn):
            raise CatalogError("QuickBooks OAuth configuration is invalid")
        if environment not in {"sandbox", "production"}:
            raise CatalogError("QuickBooks environment is invalid")
        if not isinstance(credential, dict):
            raise CatalogError("QuickBooks credential is invalid")
        if any(
            not isinstance(credential.get(field), str) or not credential[field]
            for field in ("accessToken", "refreshToken")
        ):
            raise CatalogError("QuickBooks credential is invalid")
        expires_at = credential.get("expiresAt")
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
            or expires_at <= 0
        ):
            raise CatalogError("QuickBooks credential is invalid")
        return self._save_managed_connection(
            user_id,
            "quickbooks",
            account,
            credential,
            lambda secret_arn: {
                "kind": "provider_api",
                "provider": "quickbooks",
                "authType": "oauth",
                "oauthProvider": "quickbooks",
                "secretArn": secret_arn,
                "oauthClientSecretArn": client_secret_arn,
                "scopes": ["com.intuit.quickbooks.accounting"],
                "realmId": realm_id,
                "environment": environment,
            },
            provider_account_id=realm_id,
        )

    def save_plaid_connection(
        self,
        user_id: str,
        account: str,
        item_id: str,
        access_token: str,
        app_secret_arn: str,
        environment: str,
    ) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", item_id):
            raise CatalogError("Plaid Item identity is invalid")
        if not isinstance(access_token, str) or not access_token:
            raise CatalogError("Plaid access is invalid")
        if not _valid_secret_arn(app_secret_arn):
            raise CatalogError("Plaid configuration is invalid")
        if environment not in {"sandbox", "production"}:
            raise CatalogError("Plaid environment is invalid")
        return self._save_managed_connection(
            user_id,
            "plaid",
            account,
            {"accessToken": access_token, "itemId": item_id},
            lambda secret_arn: {
                "kind": "provider_api",
                "provider": "plaid",
                "authType": "plaid_link",
                "secretArn": secret_arn,
                "appSecretArn": app_secret_arn,
                "environment": environment,
            },
            provider_account_id=item_id,
        )
