from __future__ import annotations

import re
from typing import Any


def validate_plaid_binding(value: dict[str, Any]) -> dict[str, Any]:
    secret_arn = value.get("secretArn")
    app_secret_arn = value.get("appSecretArn")
    environment = value.get("environment")
    account_ids = value.get("accountIds")
    if (
        value.get("authType") != "plaid_link"
        or not isinstance(secret_arn, str)
        or not secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(app_secret_arn, str)
        or not app_secret_arn.startswith("arn:aws:secretsmanager:")
        or environment not in {"sandbox", "production"}
        or (account_ids is not None and (
            not isinstance(account_ids, list)
            or not 1 <= len(account_ids) <= 100
            or any(
                not isinstance(account_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", account_id)
                for account_id in account_ids
            )
            or len(account_ids) != len(set(account_ids))
        ))
    ):
        raise ValueError("Plaid provider connection is invalid")
    return {
        "kind": "provider_api",
        "provider": "plaid",
        "authType": "plaid_link",
        "secretArn": secret_arn,
        "appSecretArn": app_secret_arn,
        "environment": environment,
        **({"accountIds": account_ids} if account_ids is not None else {}),
    }
