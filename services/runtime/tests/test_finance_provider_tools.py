from __future__ import annotations

import json

import pytest

from heytim_runtime import finance_provider_tools, provider_connections
from heytim_runtime.mcp_connections import _bounded_tool_name

USER_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "heytim/connections/abcdef1234567890abcdef12/"
    "connection_1234567890abcdef1234-abcdef123456-ABC123"
)
QUICKBOOKS_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "heytim/oauth/quickbooks-production-ABC123"
)
PLAID_SECRET = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
    "heytim/oauth/plaid-production-ABC123"
)
TOOL_ID = "connection_1234567890abcdef1234"


def _quickbooks_binding() -> dict:
    return provider_connections.validated_provider_binding(
        TOOL_ID,
        {
            "kind": "provider_api",
            "provider": "quickbooks",
            "authType": "oauth",
            "oauthProvider": "quickbooks",
            "secretArn": USER_SECRET,
            "oauthClientSecretArn": QUICKBOOKS_SECRET,
            "scopes": ["com.intuit.quickbooks.accounting"],
            "realmId": "123456789",
            "environment": "production",
            "accountLabel": "Acme Books",
        },
    )


def _plaid_binding(account_ids: list[str] | None = None) -> dict:
    return provider_connections.validated_provider_binding(
        TOOL_ID,
        {
            "kind": "provider_api",
            "provider": "plaid",
            "authType": "plaid_link",
            "secretArn": USER_SECRET,
            "appSecretArn": PLAID_SECRET,
            "environment": "production",
            "accountLabel": "Plaid Bank",
            **({"accountIds": account_ids} if account_ids is not None else {}),
        },
    )


def test_finance_bindings_accept_only_scoped_provider_configuration() -> None:
    assert _quickbooks_binding()["realmId"] == "123456789"
    assert _plaid_binding()["appSecretArn"] == PLAID_SECRET

    with pytest.raises(ValueError, match="Plaid provider"):
        provider_connections.validated_provider_binding(
            TOOL_ID,
            {
                **_plaid_binding(),
                "appSecretArn": QUICKBOOKS_SECRET,
            },
        )


def test_quickbooks_exposes_reviewed_read_only_tools(monkeypatch) -> None:
    urls: list[str] = []
    monkeypatch.setattr(
        provider_connections, "_quickbooks_access_token", lambda _binding: "access"
    )

    def response(url: str, _access_token: str, **_kwargs) -> dict:
        urls.append(url)
        return {"QueryResponse": {"Account": [{"Name": "Checking"}]}}

    monkeypatch.setattr(provider_connections, "_provider_api_json", response)
    tools = provider_connections.provider_connection_tools(_quickbooks_binding())

    assert [item.tool_name for item in tools] == [
        _bounded_tool_name(TOOL_ID, name)
        for name in (
            "quickbooks_accounts",
            "quickbooks_profit_and_loss",
            "quickbooks_balance_sheet",
            "quickbooks_cash_flow",
            "quickbooks_trial_balance",
            "quickbooks_invoices",
            "quickbooks_bills",
            "quickbooks_vendors",
        )
    ]
    assert json.loads(tools[0](25))["Account"][0]["Name"] == "Checking"
    assert "/v3/company/123456789/query?" in urls[0]
    assert "MAXRESULTS+25" in urls[0]
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        tools[1]("not-a-date", "2026-09-25")


def test_plaid_exposes_accounts_transactions_and_liabilities(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def response(_binding: dict, path: str, payload: dict) -> dict:
        calls.append((path, payload))
        if path == "/accounts/get":
            return {"accounts": [{"name": "Card"}]}
        if path == "/transactions/get":
            return {
                "accounts": [],
                "transactions": [{"merchant_name": "Office Store", "amount": 18.25}],
                "total_transactions": 1,
            }
        return {"accounts": [], "liabilities": {"credit": []}}

    monkeypatch.setattr(finance_provider_tools, "_plaid_json", response)
    tools = provider_connections.provider_connection_tools(_plaid_binding())

    assert [item.tool_name for item in tools] == [
        _bounded_tool_name(TOOL_ID, name)
        for name in ("plaid_accounts", "plaid_transactions", "plaid_liabilities")
    ]
    assert json.loads(tools[0]())["accounts"][0]["name"] == "Card"
    result = json.loads(tools[1]("2026-09-01", "2026-09-25", 20))
    assert result["transactions"][0]["merchant_name"] == "Office Store"
    assert calls[1][0] == "/transactions/get"
    assert calls[1][1]["options"]["count"] == 20
    assert json.loads(tools[2]())["liabilities"] == {"credit": []}


def test_plaid_tools_enforce_bot_account_allowlist(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    allowed_id = "account_card_456"
    other_id = "account_checking_123"

    def response(_binding: dict, path: str, payload: dict) -> dict:
        calls.append((path, payload))
        accounts = [
            {"account_id": allowed_id, "name": "Business Card"},
            {"account_id": other_id, "name": "Personal Checking"},
        ]
        if path == "/transactions/get":
            return {
                "accounts": accounts,
                "transactions": [
                    {"account_id": allowed_id, "name": "Office Store"},
                    {"account_id": other_id, "name": "Groceries"},
                ],
                "total_transactions": 1,
            }
        if path == "/liabilities/get":
            return {
                "accounts": accounts,
                "liabilities": {
                    "credit": [
                        {"account_id": allowed_id, "minimum_payment_amount": 25},
                        {"account_id": other_id, "minimum_payment_amount": 10},
                    ]
                },
            }
        return {"accounts": accounts, "item": {"institution_id": "ins_123"}}

    monkeypatch.setattr(finance_provider_tools, "_plaid_json", response)
    tools = provider_connections.provider_connection_tools(_plaid_binding([allowed_id]))

    assert [item["account_id"] for item in json.loads(tools[0]())["accounts"]] == [
        allowed_id
    ]
    transactions = json.loads(tools[1]("2026-09-01", "2026-09-25"))
    assert [item["account_id"] for item in transactions["transactions"]] == [allowed_id]
    liabilities = json.loads(tools[2]())
    assert [item["account_id"] for item in liabilities["liabilities"]["credit"]] == [
        allowed_id
    ]
    assert all(call[1]["options"]["account_ids"] == [allowed_id] for call in calls)
    with pytest.raises(ValueError, match="not assigned to this bot"):
        tools[1]("2026-09-01", "2026-09-25", account_id=other_id)


def test_quickbooks_refresh_rotates_access_and_refresh_tokens(monkeypatch) -> None:
    class FakeSecrets:
        def __init__(self) -> None:
            self.saved = None

        def get_secret_value(self, *, SecretId: str) -> dict:
            if SecretId == USER_SECRET:
                return {"SecretString": json.dumps({"refreshToken": "old-refresh"})}
            assert SecretId == QUICKBOOKS_SECRET
            return {
                "SecretString": json.dumps(
                    {"clientId": "client-id", "clientSecret": "client-secret"}
                )
            }

        def put_secret_value(self, **kwargs) -> None:
            self.saved = kwargs

    secrets = FakeSecrets()
    monkeypatch.setattr(provider_connections, "_secrets_manager", secrets)
    monkeypatch.setattr(
        provider_connections,
        "_token_json",
        lambda _request: {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3_600,
            "x_refresh_token_expires_in": 8_640_000,
        },
    )

    assert provider_connections._quickbooks_access_token(_quickbooks_binding()) == "new-access"
    assert secrets.saved is not None
    saved = json.loads(secrets.saved["SecretString"])
    assert saved["accessToken"] == "new-access"
    assert saved["refreshToken"] == "new-refresh"
    assert saved["refreshExpiresAt"] > saved["expiresAt"]
