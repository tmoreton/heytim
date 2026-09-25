from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from shared.catalog import CatalogError

from .google_oauth import _redirect, _result_url, _return_url, _state_key
from .support import ApiError, _ensure_account_active, catalog, table

QUICKBOOKS_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QUICKBOOKS_TOKEN_URL = (  # nosec B105 - fixed OAuth endpoint, not a credential.
    "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
)
QUICKBOOKS_SCOPE = "com.intuit.quickbooks.accounting"
QUICKBOOKS_BASE_URLS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}
PLAID_BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}
OAUTH_STATE_SECONDS = 10 * 60
CALLBACK_BUDGET_SECONDS = 14.0
REQUEST_MAX_SECONDS = 5.0
DEFAULT_RETURN_URL = "https://heytim.ai/app?oauth=finance"

_secrets_manager = None
logger = logging.getLogger(__name__)


def _secret_client():
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = boto3.client(
            "secretsmanager",
            config=Config(
                retries={"total_max_attempts": 4, "mode": "adaptive"},
                connect_timeout=2,
                read_timeout=3,
            ),
        )
    return _secrets_manager


def _configuration(provider: str, secret_arn: str | None = None) -> tuple[dict, str]:
    environment_name = {
        "quickbooks": "QUICKBOOKS_OAUTH_SECRET_ARN",
        "plaid": "PLAID_SECRET_ARN",
    }[provider]
    arn = secret_arn or os.environ.get(environment_name, "")
    if not arn.startswith("arn:aws:secretsmanager:"):
        raise ApiError(503, f"{provider.title()} connections are not configured")
    response = _secret_client().get_secret_value(SecretId=arn)
    raw = response.get("SecretString")
    try:
        document = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError as exc:
        raise ApiError(503, f"{provider.title()} connections are not configured") from exc
    if not isinstance(document, dict):
        raise ApiError(503, f"{provider.title()} connections are not configured")
    client_id = document.get("clientId")
    secret_key = "clientSecret" if provider == "quickbooks" else "secret"
    client_secret = document.get(secret_key)
    environment = document.get("environment")
    if (
        not isinstance(client_id, str)
        or not re.fullmatch(r"[A-Za-z0-9._~-]{8,300}", client_id)
        or not isinstance(client_secret, str)
        or not 8 <= len(client_secret) <= 1_000
        or environment not in {"sandbox", "production"}
    ):
        raise ApiError(503, f"{provider.title()} connections are not configured")
    return {
        "clientId": client_id,
        "clientSecret": client_secret,
        "environment": environment,
    }, arn


def _remaining_timeout(deadline: float, provider: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining < 0.5:
        raise ApiError(400, f"The {provider} connection took too long. Please try again.")
    return min(REQUEST_MAX_SECONDS, remaining)


def _request_json(
    request: urllib.request.Request, deadline: float, provider: str
) -> dict:
    try:
        with urllib.request.urlopen(  # nosec B310 - all callers use fixed provider hosts.
            request, timeout=_remaining_timeout(deadline, provider)
        ) as response:
            value = json.loads(response.read(500_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(400, f"{provider} could not complete the connection") from exc
    if not isinstance(value, dict):
        raise ApiError(400, f"{provider} returned an invalid response")
    return value


def _consume_state(value: Any, provider: str) -> dict:
    if not isinstance(value, str) or not 20 <= len(value) <= 200:
        raise ApiError(400, f"The {provider} connection expired. Please try again.")
    result = table.delete_item(Key=_state_key(value), ReturnValues="ALL_OLD")
    item = result.get("Attributes")
    if (
        not item
        or item.get("provider") != provider
        or int(item.get("expiresAt", 0)) < int(time.time())
    ):
        raise ApiError(400, f"The {provider} connection expired. Please try again.")
    return item


def _begin_quickbooks_authorization(user_id: str, value: dict) -> dict:
    return_url = _return_url(value.get("returnUrl"))
    config, secret_arn = _configuration("quickbooks")
    redirect_uri = os.environ.get("QUICKBOOKS_OAUTH_REDIRECT_URI")
    if not redirect_uri:
        raise ApiError(503, "QuickBooks connections are not configured")
    state = secrets.token_urlsafe(32)
    table.put_item(
        Item={
            **_state_key(state),
            "entity": "OAUTH_STATE",
            "userId": user_id,
            "provider": "quickbooks",
            "returnUrl": return_url,
            "clientSecretArn": secret_arn,
            "environment": config["environment"],
            "expiresAt": int(time.time()) + OAUTH_STATE_SECONDS,
        }
    )
    query = urllib.parse.urlencode(
        {
            "client_id": config["clientId"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": QUICKBOOKS_SCOPE,
            "state": state,
        }
    )
    return {"authorizationUrl": f"{QUICKBOOKS_AUTH_URL}?{query}"}


def _quickbooks_token(code: str, config: dict, deadline: float) -> dict:
    credentials = base64.b64encode(
        f"{config['clientId']}:{config['clientSecret']}".encode()
    ).decode()
    request = urllib.request.Request(
        QUICKBOOKS_TOKEN_URL,
        data=urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": os.environ["QUICKBOOKS_OAUTH_REDIRECT_URI"],
            }
        ).encode(),
        headers={
            "accept": "application/json",
            "authorization": f"Basic {credentials}",
            "content-type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    return _request_json(request, deadline, "QuickBooks")


def _quickbooks_company(
    realm_id: str, access_token: str, environment: str, deadline: float
) -> str:
    url = (
        f"{QUICKBOOKS_BASE_URLS[environment]}/v3/company/{realm_id}/"
        f"companyinfo/{realm_id}?minorversion=75"
    )
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/json",
            "authorization": f"Bearer {access_token}",
        },
    )
    value = _request_json(request, deadline, "QuickBooks")
    company = value.get("CompanyInfo")
    name = None
    if isinstance(company, dict):
        name = company.get("CompanyName") or company.get("LegalName")
    if not isinstance(name, str) or not name.strip():
        raise ApiError(400, "QuickBooks could not identify the connected company")
    return name.strip()[:254]


def _quickbooks_callback(query: dict) -> dict:
    return_url = DEFAULT_RETURN_URL
    deadline = time.monotonic() + CALLBACK_BUDGET_SECONDS
    credential: dict = {}
    config_arn = None
    try:
        state = _consume_state(query.get("state"), "quickbooks")
        return_url = _return_url(state.get("returnUrl"))
        _ensure_account_active(state["userId"])
        if query.get("error"):
            raise ApiError(400, "QuickBooks access was not approved")
        code = query.get("code")
        realm_id = query.get("realmId")
        if not isinstance(code, str) or not code or not isinstance(realm_id, str):
            raise ApiError(400, "QuickBooks did not return an authorization code")
        if not re.fullmatch(r"[0-9]{1,32}", realm_id):
            raise ApiError(400, "QuickBooks returned an invalid company identity")
        config, config_arn = _configuration(
            "quickbooks", state.get("clientSecretArn")
        )
        if config["environment"] != state.get("environment"):
            raise ApiError(400, "QuickBooks connection configuration changed")
        token = _quickbooks_token(code, config, deadline)
        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        expires_in = token.get("expires_in")
        refresh_expires_in = token.get("x_refresh_token_expires_in")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(refresh_token, str)
            or not refresh_token
            or isinstance(expires_in, bool)
            or not isinstance(expires_in, (int, float))
            or int(expires_in) <= 0
        ):
            raise ApiError(400, "QuickBooks did not return reusable access")
        account = _quickbooks_company(
            realm_id, access_token, config["environment"], deadline
        )
        credential = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": int(time.time()) + int(expires_in),
        }
        if (
            not isinstance(refresh_expires_in, bool)
            and isinstance(refresh_expires_in, (int, float))
            and int(refresh_expires_in) > 0
        ):
            credential["refreshExpiresAt"] = int(time.time()) + int(
                refresh_expires_in
            )
        catalog.save_quickbooks_connection(
            state["userId"],
            account,
            realm_id,
            credential,
            state["clientSecretArn"],
            config["environment"],
        )
        return _redirect(_result_url(return_url, "connected", "quickbooks"))
    except (ApiError, CatalogError, KeyError, TypeError, ValueError):
        if credential and isinstance(config_arn, str):
            try:
                catalog.revoke_unused_quickbooks_token(credential, config_arn)
            except (BotoCoreError, ClientError, KeyError, TypeError, ValueError):
                logger.warning("Could not revoke unused QuickBooks OAuth access")
        logger.exception("QuickBooks OAuth callback failed")
        return _redirect(_result_url(return_url, "error", "quickbooks"))


def _plaid_json(
    config: dict, path: str, payload: dict, deadline: float
) -> dict:
    body = {
        "client_id": config["clientId"],
        "secret": config["clientSecret"],
        **payload,
    }
    request = urllib.request.Request(
        f"{PLAID_BASE_URLS[config['environment']]}{path}",
        data=json.dumps(body, separators=(",", ":")).encode(),
        headers={"accept": "application/json", "content-type": "application/json"},
        method="POST",
    )
    return _request_json(request, deadline, "Plaid")


def _plaid_completion_url(state: str) -> str:
    base = os.environ.get("PLAID_COMPLETION_REDIRECT_URI")
    if not base:
        raise ApiError(503, "Plaid connections are not configured")
    parsed = urllib.parse.urlsplit(base)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["state"] = state
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )


def _begin_plaid_authorization(user_id: str, value: dict) -> dict:
    return_url = _return_url(value.get("returnUrl"))
    config, secret_arn = _configuration("plaid")
    redirect_uri = os.environ.get("PLAID_OAUTH_REDIRECT_URI")
    if not redirect_uri:
        raise ApiError(503, "Plaid connections are not configured")
    state = secrets.token_urlsafe(32)
    deadline = time.monotonic() + CALLBACK_BUDGET_SECONDS
    native = urllib.parse.urlsplit(return_url).scheme == "heytim"
    result = _plaid_json(
        config,
        "/link/token/create",
        {
            "client_name": "HeyTim",
            "country_codes": ["US"],
            "language": "en",
            "products": ["transactions"],
            "optional_products": ["liabilities"],
            "transactions": {"days_requested": 180},
            "redirect_uri": redirect_uri,
            "user": {
                "client_user_id": hashlib.sha256(
                    f"heytim:{user_id}".encode()
                ).hexdigest()
            },
            "hosted_link": {
                "completion_redirect_uri": _plaid_completion_url(state),
                "is_mobile_app": native,
                "url_lifetime_seconds": OAUTH_STATE_SECONDS,
            },
        },
        deadline,
    )
    link_token = result.get("link_token")
    hosted_url = result.get("hosted_link_url")
    if (
        not isinstance(link_token, str)
        or not link_token
        or not isinstance(hosted_url, str)
        or not hosted_url.startswith("https://secure.plaid.com/")
    ):
        raise ApiError(400, "Plaid could not start a secure connection")
    table.put_item(
        Item={
            **_state_key(state),
            "entity": "OAUTH_STATE",
            "userId": user_id,
            "provider": "plaid",
            "returnUrl": return_url,
            "appSecretArn": secret_arn,
            "environment": config["environment"],
            "linkToken": link_token,
            "expiresAt": int(time.time()) + OAUTH_STATE_SECONDS,
        }
    )
    return {"authorizationUrl": hosted_url}


def _plaid_link_result(value: dict) -> dict:
    sessions = value.get("link_sessions")
    for session in reversed(sessions if isinstance(sessions, list) else []):
        if not isinstance(session, dict):
            continue
        results = session.get("results")
        additions = results.get("item_add_results") if isinstance(results, dict) else None
        if isinstance(additions, list):
            for addition in additions:
                if isinstance(addition, dict) and isinstance(
                    addition.get("public_token"), str
                ):
                    return addition
        legacy = session.get("on_success")
        if isinstance(legacy, dict) and isinstance(legacy.get("public_token"), str):
            return legacy
    raise ApiError(400, "Plaid Link was closed before an institution was connected")


def _plaid_account_label(result: dict) -> str:
    institution = result.get("institution")
    name = institution.get("name") if isinstance(institution, dict) else None
    if not isinstance(name, str) or not name.strip():
        metadata = result.get("metadata")
        institution = metadata.get("institution") if isinstance(metadata, dict) else None
        name = institution.get("name") if isinstance(institution, dict) else None
    accounts = result.get("accounts")
    account_count = len(accounts) if isinstance(accounts, list) else 0
    if isinstance(name, str) and name.strip():
        suffix = f" · {account_count} accounts" if account_count > 1 else ""
        return f"{name.strip()[:220]}{suffix}"
    if isinstance(accounts, list) and accounts and isinstance(accounts[0], dict):
        account_name = accounts[0].get("name")
        if isinstance(account_name, str) and account_name.strip():
            return account_name.strip()[:254]
    return "Connected institution"


def _plaid_account_metadata(result: dict) -> list[dict]:
    values = result.get("accounts")
    if not isinstance(values, list):
        return []
    return [
        {
            "id": account.get("id", account.get("account_id")),
            "name": account.get("name"),
            "type": account.get("type"),
            "subtype": account.get("subtype"),
            "mask": account.get("mask"),
        }
        for account in values
        if isinstance(account, dict)
    ]


def _plaid_callback(query: dict) -> dict:
    return_url = DEFAULT_RETURN_URL
    deadline = time.monotonic() + CALLBACK_BUDGET_SECONDS
    access_token = None
    config = None
    try:
        state = _consume_state(query.get("state"), "plaid")
        return_url = _return_url(state.get("returnUrl"))
        _ensure_account_active(state["userId"])
        config, _ = _configuration("plaid", state.get("appSecretArn"))
        if config["environment"] != state.get("environment"):
            raise ApiError(400, "Plaid connection configuration changed")
        session = _plaid_json(
            config,
            "/link/token/get",
            {"link_token": state["linkToken"]},
            deadline,
        )
        result = _plaid_link_result(session)
        exchange = _plaid_json(
            config,
            "/item/public_token/exchange",
            {"public_token": result["public_token"]},
            deadline,
        )
        access_token = exchange.get("access_token")
        item_id = exchange.get("item_id")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(item_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", item_id)
        ):
            raise ApiError(400, "Plaid did not return reusable institution access")
        catalog.save_plaid_connection(
            state["userId"],
            _plaid_account_label(result),
            item_id,
            access_token,
            state["appSecretArn"],
            config["environment"],
            _plaid_account_metadata(result),
        )
        return _redirect(_result_url(return_url, "connected", "plaid"))
    except (ApiError, CatalogError, KeyError, TypeError, ValueError):
        if access_token and config:
            try:
                _plaid_json(
                    config,
                    "/item/remove",
                    {"access_token": access_token},
                    deadline,
                )
            except (ApiError, KeyError, TypeError, ValueError):
                logger.warning("Could not remove unused Plaid Item")
        logger.exception("Plaid Hosted Link callback failed")
        return _redirect(_result_url(return_url, "error", "plaid"))


__all__ = [
    "_begin_plaid_authorization",
    "_begin_quickbooks_authorization",
    "_plaid_callback",
    "_quickbooks_callback",
]
