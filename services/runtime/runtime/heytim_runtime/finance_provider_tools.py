from __future__ import annotations

import base64
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from strands import tool

QUICKBOOKS_BASE_URLS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}
PLAID_BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}
QUICKBOOKS_TOKEN_URL = (  # nosec B105 - fixed OAuth endpoint, not a credential.
    "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
)


def _runtime():
    from . import provider_connections

    return provider_connections


def _date(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must use YYYY-MM-DD")
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc
    today = dt.datetime.now(dt.UTC).date()
    if parsed.year < 2000 or parsed > today + dt.timedelta(days=1):
        raise ValueError(f"{field} is outside the supported range")
    return parsed.isoformat()


def _date_range(start_date: str, end_date: str) -> tuple[str, str]:
    start = _date(start_date, "start_date")
    end = _date(end_date, "end_date")
    start_value = dt.date.fromisoformat(start)
    end_value = dt.date.fromisoformat(end)
    if start_value > end_value or (end_value - start_value).days > 730:
        raise ValueError("date range must be ordered and no longer than 730 days")
    return start, end


def _quickbooks_json(binding: dict, path: str, parameters: dict[str, str]) -> dict:
    query = urllib.parse.urlencode(parameters)
    url = f"{QUICKBOOKS_BASE_URLS[binding['environment']]}{path}?{query}"
    return _runtime()._provider_api_json(
        url,
        _runtime()._quickbooks_access_token(binding),
        headers={"accept": "application/json"},
    )


def quickbooks_access_token(binding: dict) -> str:
    runtime = _runtime()
    credential = runtime._json_secret(binding["secretArn"])
    cached = runtime._cached_access_token(credential)
    if cached:
        return cached
    refresh_token = credential.get("refreshToken")
    client_id, client_secret = runtime._oauth_client(binding)
    if not isinstance(refresh_token, str) or not refresh_token:
        raise ValueError("QuickBooks OAuth credential is invalid")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(
        QUICKBOOKS_TOKEN_URL,
        data=urllib.parse.urlencode(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        ).encode(),
        headers={
            "accept": "application/json",
            "authorization": f"Basic {basic}",
            "content-type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        value = runtime._token_json(request)
    except ValueError:
        latest = runtime._json_secret(binding["secretArn"])
        cached = runtime._cached_access_token(latest)
        if cached:
            return cached
        raise
    access_token = value.get("access_token")
    rotated_refresh_token = value.get("refresh_token")
    expires_in = value.get("expires_in")
    refresh_expires_in = value.get("x_refresh_token_expires_in")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(rotated_refresh_token, str)
        or not rotated_refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or int(expires_in) <= 0
    ):
        raise ValueError("QuickBooks OAuth access is unavailable")
    replacement = {
        "refreshToken": rotated_refresh_token,
        "accessToken": access_token,
        "expiresAt": int(runtime.time.time()) + int(expires_in),
    }
    if (
        not isinstance(refresh_expires_in, bool)
        and isinstance(refresh_expires_in, (int, float))
        and int(refresh_expires_in) > 0
    ):
        replacement["refreshExpiresAt"] = int(runtime.time.time()) + int(
            refresh_expires_in
        )
    elif isinstance(credential.get("refreshExpiresAt"), int):
        replacement["refreshExpiresAt"] = credential["refreshExpiresAt"]
    runtime._secret_client().put_secret_value(
        SecretId=binding["secretArn"],
        SecretString=json.dumps(replacement, separators=(",", ":")),
    )
    return access_token


def quickbooks_tools(binding: dict, usage: Any) -> list[Any]:
    company_path = f"/v3/company/{binding['realmId']}"

    def query_entities(statement: str) -> str:
        value = _quickbooks_json(
            binding,
            f"{company_path}/query",
            {"query": statement, "minorversion": "75"},
        )
        return json.dumps(value.get("QueryResponse", {}), separators=(",", ":"))

    def report(name: str, parameters: dict[str, str]) -> str:
        value = _quickbooks_json(
            binding,
            f"{company_path}/reports/{name}",
            {**parameters, "minorversion": "75"},
        )
        return json.dumps(value, separators=(",", ":"))

    @tool
    def quickbooks_accounts(max_results: int = 100) -> str:
        """List active accounts in the connected QuickBooks chart of accounts."""
        count = _runtime()._limit(max_results, minimum=1, maximum=250)
        _runtime()._record(usage, "quickbooks", "quickbooks_accounts")
        return query_entities(
            f"SELECT * FROM Account WHERE Active = true MAXRESULTS {count}"
        )

    @tool
    def quickbooks_profit_and_loss(start_date: str, end_date: str) -> str:
        """Read the QuickBooks profit and loss report for an inclusive date range."""
        start, end = _date_range(start_date, end_date)
        _runtime()._record(usage, "quickbooks", "quickbooks_profit_and_loss")
        return report("ProfitAndLoss", {"start_date": start, "end_date": end})

    @tool
    def quickbooks_balance_sheet(as_of_date: str) -> str:
        """Read the QuickBooks balance sheet as of a specified date."""
        end = _date(as_of_date, "as_of_date")
        _runtime()._record(usage, "quickbooks", "quickbooks_balance_sheet")
        return report("BalanceSheet", {"end_date": end})

    @tool
    def quickbooks_cash_flow(start_date: str, end_date: str) -> str:
        """Read the QuickBooks statement of cash flows for an inclusive date range."""
        start, end = _date_range(start_date, end_date)
        _runtime()._record(usage, "quickbooks", "quickbooks_cash_flow")
        return report("CashFlow", {"start_date": start, "end_date": end})

    @tool
    def quickbooks_trial_balance(as_of_date: str) -> str:
        """Read the QuickBooks trial balance as of a specified date."""
        end = _date(as_of_date, "as_of_date")
        _runtime()._record(usage, "quickbooks", "quickbooks_trial_balance")
        return report("TrialBalance", {"end_date": end})

    def dated_entities(entity: str, start_date: str, end_date: str, count: int) -> str:
        start, end = _date_range(start_date, end_date)
        return query_entities(
            f"SELECT * FROM {entity} WHERE TxnDate >= '{start}' "
            f"AND TxnDate <= '{end}' ORDERBY TxnDate DESC MAXRESULTS {count}"
        )

    @tool
    def quickbooks_invoices(
        start_date: str, end_date: str, max_results: int = 50
    ) -> str:
        """List QuickBooks invoices whose transaction dates fall in a date range."""
        count = _runtime()._limit(max_results, minimum=1, maximum=100)
        _runtime()._record(usage, "quickbooks", "quickbooks_invoices")
        return dated_entities("Invoice", start_date, end_date, count)

    @tool
    def quickbooks_bills(
        start_date: str, end_date: str, max_results: int = 50
    ) -> str:
        """List QuickBooks bills whose transaction dates fall in a date range."""
        count = _runtime()._limit(max_results, minimum=1, maximum=100)
        _runtime()._record(usage, "quickbooks", "quickbooks_bills")
        return dated_entities("Bill", start_date, end_date, count)

    @tool
    def quickbooks_vendors(max_results: int = 100) -> str:
        """List active vendors in the connected QuickBooks company."""
        count = _runtime()._limit(max_results, minimum=1, maximum=250)
        _runtime()._record(usage, "quickbooks", "quickbooks_vendors")
        return query_entities(
            f"SELECT * FROM Vendor WHERE Active = true MAXRESULTS {count}"
        )

    return [
        quickbooks_accounts,
        quickbooks_profit_and_loss,
        quickbooks_balance_sheet,
        quickbooks_cash_flow,
        quickbooks_trial_balance,
        quickbooks_invoices,
        quickbooks_bills,
        quickbooks_vendors,
    ]


def _plaid_configuration(binding: dict) -> tuple[str, str]:
    value = _runtime()._json_secret(binding["appSecretArn"])
    client_id = value.get("clientId")
    secret = value.get("secret")
    environment = value.get("environment")
    if (
        not isinstance(client_id, str)
        or not client_id
        or not isinstance(secret, str)
        or not secret
        or environment != binding["environment"]
    ):
        raise ValueError("Plaid configuration is invalid")
    return client_id, secret


def _plaid_json(binding: dict, path: str, payload: dict) -> dict:
    client_id, secret = _plaid_configuration(binding)
    credential = _runtime()._json_secret(binding["secretArn"])
    access_token = credential.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("Plaid connection credential is invalid")
    request = urllib.request.Request(
        f"{PLAID_BASE_URLS[binding['environment']]}{path}",
        data=json.dumps(
            {
                "client_id": client_id,
                "secret": secret,
                "access_token": access_token,
                **payload,
            },
            separators=(",", ":"),
        ).encode(),
        headers={"accept": "application/json", "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - URL uses a fixed Plaid host.
            request, timeout=15
        ) as response:
            value = json.loads(response.read(500_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Connected Plaid data is unavailable") from exc
    if not isinstance(value, dict):
        raise TypeError("Plaid returned an invalid response")
    return value


def _plaid_account_ids(binding: dict) -> list[str] | None:
    account_ids = binding.get("accountIds")
    return account_ids if isinstance(account_ids, list) else None


def _plaid_account_options(binding: dict) -> dict:
    account_ids = _plaid_account_ids(binding)
    return {"options": {"account_ids": account_ids}} if account_ids else {}


def _filter_plaid_records(values: Any, account_ids: list[str] | None) -> Any:
    if account_ids is None or not isinstance(values, list):
        return values
    allowed = set(account_ids)
    return [
        value for value in values
        if isinstance(value, dict) and value.get("account_id") in allowed
    ]


def _filter_plaid_liabilities(value: Any, account_ids: list[str] | None) -> Any:
    if account_ids is None or not isinstance(value, dict):
        return value
    return {
        kind: _filter_plaid_records(records, account_ids)
        for kind, records in value.items()
    }


def plaid_tools(binding: dict, usage: Any) -> list[Any]:
    @tool
    def plaid_accounts() -> str:
        """Read account names, types, masks, and cached balances from Plaid."""
        _runtime()._record(usage, "plaid", "plaid_accounts")
        account_ids = _plaid_account_ids(binding)
        value = _plaid_json(binding, "/accounts/get", _plaid_account_options(binding))
        return json.dumps(
            {
                "accounts": _filter_plaid_records(value.get("accounts", []), account_ids),
                "item": value.get("item", {}),
            },
            separators=(",", ":"),
        )

    @tool
    def plaid_transactions(
        start_date: str,
        end_date: str,
        max_results: int = 100,
        account_id: str = "",
    ) -> str:
        """Read posted and pending bank or card transactions in a date range."""
        start, end = _date_range(start_date, end_date)
        count = _runtime()._limit(max_results, minimum=1, maximum=100)
        options: dict[str, Any] = {
            "count": count,
            "offset": 0,
            "personal_finance_category_version": "v2",
        }
        allowed_account_ids = _plaid_account_ids(binding)
        if account_id:
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", account_id):
                raise ValueError("account_id is invalid")
            if allowed_account_ids is not None and account_id not in allowed_account_ids:
                raise ValueError("account_id is not assigned to this bot")
            options["account_ids"] = [account_id]
        elif allowed_account_ids is not None:
            options["account_ids"] = allowed_account_ids
        _runtime()._record(usage, "plaid", "plaid_transactions")
        value = _plaid_json(
            binding,
            "/transactions/get",
            {"start_date": start, "end_date": end, "options": options},
        )
        return json.dumps(
            {
                "accounts": _filter_plaid_records(
                    value.get("accounts", []), allowed_account_ids
                ),
                "transactions": _filter_plaid_records(
                    value.get("transactions", []), allowed_account_ids
                ),
                "totalTransactions": value.get("total_transactions", 0),
            },
            separators=(",", ":"),
        )

    @tool
    def plaid_liabilities() -> str:
        """Read supported credit-card and loan liabilities from Plaid."""
        _runtime()._record(usage, "plaid", "plaid_liabilities")
        account_ids = _plaid_account_ids(binding)
        value = _plaid_json(
            binding, "/liabilities/get", _plaid_account_options(binding)
        )
        return json.dumps(
            {
                "accounts": _filter_plaid_records(value.get("accounts", []), account_ids),
                "liabilities": _filter_plaid_liabilities(
                    value.get("liabilities", {}), account_ids
                ),
            },
            separators=(",", ":"),
        )

    return [plaid_accounts, plaid_transactions, plaid_liabilities]


__all__ = ["plaid_tools", "quickbooks_access_token", "quickbooks_tools"]
