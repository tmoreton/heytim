from __future__ import annotations

import re
from typing import Any

from .catalog_rules import CatalogError

PLAID_ACCOUNT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{8,200}")


def _valid_secret_arn(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("arn:aws:secretsmanager:")


def _plaid_accounts(values: Any) -> list[dict]:
    if not isinstance(values, list) or len(values) > 100:
        raise CatalogError("Plaid account metadata is invalid")
    accounts = []
    seen = set()
    for value in values:
        account_id = value.get("id") if isinstance(value, dict) else None
        name = value.get("name") if isinstance(value, dict) else None
        account_type = value.get("type") if isinstance(value, dict) else None
        subtype = value.get("subtype") if isinstance(value, dict) else None
        mask = value.get("mask") if isinstance(value, dict) else None
        if (
            not isinstance(account_id, str)
            or not PLAID_ACCOUNT_ID_PATTERN.fullmatch(account_id)
            or account_id in seen
            or not isinstance(name, str)
            or not name.strip()
            or len(name.strip()) > 160
            or not isinstance(account_type, str)
            or not re.fullmatch(r"[a-z_]{2,40}", account_type)
            or (subtype is not None and (
                not isinstance(subtype, str)
                or not re.fullmatch(r"[a-z0-9_ -]{1,80}", subtype)
            ))
            or (mask is not None and (
                not isinstance(mask, str) or not re.fullmatch(r"[A-Za-z0-9* -]{1,16}", mask)
            ))
        ):
            raise CatalogError("Plaid account metadata is invalid")
        seen.add(account_id)
        accounts.append({
            "id": account_id,
            "name": name.strip(),
            "type": account_type,
            **({"subtype": subtype} if subtype is not None else {}),
            **({"mask": mask} if mask is not None else {}),
        })
    return accounts


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
        accounts: list[dict] | None = None,
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
            metadata=(
                {"plaidAccounts": _plaid_accounts(accounts)}
                if accounts is not None else None
            ),
        )
