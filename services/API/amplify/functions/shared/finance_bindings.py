from __future__ import annotations

from typing import Any


def validate_plaid_binding(value: dict[str, Any]) -> dict[str, Any]:
    secret_arn = value.get("secretArn")
    app_secret_arn = value.get("appSecretArn")
    environment = value.get("environment")
    if (
        value.get("authType") != "plaid_link"
        or not isinstance(secret_arn, str)
        or not secret_arn.startswith("arn:aws:secretsmanager:")
        or not isinstance(app_secret_arn, str)
        or not app_secret_arn.startswith("arn:aws:secretsmanager:")
        or environment not in {"sandbox", "production"}
    ):
        raise ValueError("Plaid provider connection is invalid")
    return {
        "kind": "provider_api",
        "provider": "plaid",
        "authType": "plaid_link",
        "secretArn": secret_arn,
        "appSecretArn": app_secret_arn,
        "environment": environment,
    }
