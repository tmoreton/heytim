from __future__ import annotations

import base64
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
from shared.connection_providers import connection_specs

from .google_oauth import (
    _pkce_challenge,
    _redirect,
    _result_url,
    _return_url,
    _state_key,
)
from .support import ApiError, _ensure_account_active, catalog, table

EXTERNAL_PROVIDER_SPECS = {
    provider_id: spec
    for provider_id, spec in connection_specs().items()
    if provider_id in {"slack", "microsoft", "notion"}
}
OAUTH_STATE_SECONDS = 10 * 60
CALLBACK_BUDGET_SECONDS = 12.0
REQUEST_MAX_SECONDS = 4.0
DEFAULT_RETURN_URL = "https://app.froggybot.com/app?oauth=connection"
REDIRECT_ENV = "EXTERNAL_OAUTH_REDIRECT_URI"
SECRET_ENVS = {
    "slack": "SLACK_OAUTH_SECRET_ARN",
    "microsoft": "MICROSOFT_OAUTH_SECRET_ARN",
    "notion": "NOTION_OAUTH_SECRET_ARN",
}
SLACK_AUTH_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"  # nosec B105
MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = (  # nosec B105
    "https://login.microsoftonline.com/common/oauth2/v2.0/token"
)
MICROSOFT_PROFILE_URL = (
    "https://graph.microsoft.com/v1.0/me?"
    + urllib.parse.urlencode(
        {"$select": "id,displayName,mail,userPrincipalName"}
    )
)
NOTION_AUTH_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_TOKEN_URL = "https://api.notion.com/v1/oauth/token"  # nosec B105
NOTION_API_VERSION = "2026-03-11"

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


def _oauth_client(provider: str) -> tuple[str, str, str]:
    secret_env = SECRET_ENVS.get(provider)
    secret_arn = os.environ.get(secret_env, "") if secret_env else ""
    if not secret_arn:
        raise ApiError(503, f"{provider.title()} connections are not configured")
    response = _secret_client().get_secret_value(SecretId=secret_arn)
    raw = response.get("SecretString")
    try:
        document = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError as exc:
        raise ApiError(
            503, f"{provider.title()} connections are not configured"
        ) from exc
    client_id = document.get("clientId") if isinstance(document, dict) else None
    client_secret = (
        document.get("clientSecret") if isinstance(document, dict) else None
    )
    if (
        not isinstance(client_id, str)
        or not re.fullmatch(r"[A-Za-z0-9._~-]{8,300}", client_id)
        or not isinstance(client_secret, str)
        or not 16 <= len(client_secret) <= 1_000
    ):
        raise ApiError(503, f"{provider.title()} connections are not configured")
    return client_id, client_secret, secret_arn


def _remaining_timeout(deadline: float, provider: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining < 0.5:
        raise ApiError(
            400, f"The {provider.title()} connection took too long. Please try again."
        )
    return min(REQUEST_MAX_SECONDS, remaining)


def _authorization_query(
    provider: str, client_id: str, redirect_uri: str, state: str, verifier: str
) -> tuple[str, dict[str, str]]:
    scopes = EXTERNAL_PROVIDER_SPECS[provider]["scopes"]
    common = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
    }
    if provider == "slack":
        return SLACK_AUTH_URL, {**common, "user_scope": ",".join(scopes)}
    if provider == "microsoft":
        return MICROSOFT_AUTH_URL, {
            **common,
            "response_mode": "query",
            "scope": " ".join(scopes),
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    return NOTION_AUTH_URL, {**common, "owner": "user"}


def _begin_external_authorization(
    user_id: str, value: dict, provider: str
) -> dict:
    if provider not in EXTERNAL_PROVIDER_SPECS:
        raise ApiError(404, "Connection provider not found")
    return_url = _return_url(value.get("returnUrl"))
    client_id, _, client_secret_arn = _oauth_client(provider)
    redirect_uri = os.environ.get(REDIRECT_ENV)
    if not redirect_uri:
        raise ApiError(503, f"{provider.title()} connections are not configured")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    table.put_item(
        Item={
            **_state_key(state),
            "entity": "OAUTH_STATE",
            "userId": user_id,
            "provider": provider,
            "verifier": verifier,
            "returnUrl": return_url,
            "clientSecretArn": client_secret_arn,
            "expiresAt": int(time.time()) + OAUTH_STATE_SECONDS,
        }
    )
    auth_url, query = _authorization_query(
        provider, client_id, redirect_uri, state, verifier
    )
    return {"authorizationUrl": f"{auth_url}?{urllib.parse.urlencode(query)}"}


def _begin_slack_authorization(user_id: str, value: dict) -> dict:
    return _begin_external_authorization(user_id, value, "slack")


def _begin_microsoft_authorization(user_id: str, value: dict) -> dict:
    return _begin_external_authorization(user_id, value, "microsoft")


def _begin_notion_authorization(user_id: str, value: dict) -> dict:
    return _begin_external_authorization(user_id, value, "notion")


def _consume_state(state: Any) -> dict:
    if not isinstance(state, str) or not 20 <= len(state) <= 200:
        raise ApiError(400, "The provider connection expired. Please try again.")
    result = table.delete_item(Key=_state_key(state), ReturnValues="ALL_OLD")
    item = result.get("Attributes")
    if (
        not item
        or item.get("provider") not in EXTERNAL_PROVIDER_SPECS
        or int(item.get("expiresAt", 0)) < int(time.time())
    ):
        raise ApiError(400, "The provider connection expired. Please try again.")
    return item


def _request_json(
    request: urllib.request.Request, deadline: float, provider: str
) -> dict:
    try:
        with urllib.request.urlopen(  # nosec B310 - fixed provider endpoints.
            request, timeout=_remaining_timeout(deadline, provider)
        ) as response:
            value = json.loads(response.read(200_001).decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(
            400, f"{provider.title()} could not complete the connection"
        ) from exc
    if not isinstance(value, dict):
        raise ApiError(400, f"{provider.title()} returned an invalid response")
    return value


def _exchange_code(provider: str, code: str, verifier: str, deadline: float) -> dict:
    client_id, client_secret, _ = _oauth_client(provider)
    redirect_uri = os.environ[REDIRECT_ENV]
    headers = {"content-type": "application/x-www-form-urlencoded"}
    if provider == "slack":
        fields = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        url = SLACK_TOKEN_URL
    elif provider == "microsoft":
        fields = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(EXTERNAL_PROVIDER_SPECS[provider]["scopes"]),
        }
        url = MICROSOFT_TOKEN_URL
    else:
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers = {
            "authorization": f"Basic {basic}",
            "content-type": "application/json",
            "notion-version": NOTION_API_VERSION,
        }
        request = urllib.request.Request(
            NOTION_TOKEN_URL,
            data=json.dumps(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                }
            ).encode(),
            headers=headers,
            method="POST",
        )
        return _request_json(request, deadline, provider)
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers=headers,
        method="POST",
    )
    return _request_json(request, deadline, provider)


def _bearer_json(url: str, access_token: str, deadline: float, provider: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/json",
            "authorization": f"Bearer {access_token}",
        },
    )
    return _request_json(request, deadline, provider)


def _slack_connection(token: dict) -> tuple[str, str, dict]:
    if token.get("ok") is not True:
        raise ApiError(400, "Slack could not complete the connection")
    user = token.get("authed_user")
    team = token.get("team")
    if not isinstance(user, dict) or not isinstance(team, dict):
        raise ApiError(400, "Slack returned an invalid connection")
    access_token = user.get("access_token")
    refresh_token = user.get("refresh_token")
    expires_in = user.get("expires_in")
    user_id = user.get("id")
    team_id = team.get("id")
    team_name = team.get("name")
    granted = {
        scope.strip()
        for scope in str(user.get("scope", "")).split(",")
        if scope.strip()
    }
    required = set(EXTERNAL_PROVIDER_SPECS["slack"]["scopes"])
    if (
        granted != required
        or not all(
            isinstance(value, str) and value
            for value in (
                access_token,
                refresh_token,
                user_id,
                team_id,
                team_name,
            )
        )
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or int(expires_in) <= 0
    ):
        raise ApiError(400, "Slack read-only access is required")
    return (
        f"{team_id}:{user_id}",
        team_name[:254],
        {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": int(time.time()) + int(expires_in),
        },
    )


def _microsoft_connection(
    token: dict, deadline: float
) -> tuple[str, str, dict]:
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    expires_in = token.get("expires_in")
    granted = {scope.casefold() for scope in str(token.get("scope", "")).split()}
    required = {
        "user.read",
        "mail.read",
        "calendars.read",
        "files.read.all",
        "sites.read.all",
    }
    if (
        not required.issubset(granted)
        or not isinstance(access_token, str)
        or not access_token
        or not isinstance(refresh_token, str)
        or not refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or int(expires_in) <= 0
    ):
        raise ApiError(400, "Microsoft 365 read-only access is required")
    profile = _bearer_json(
        MICROSOFT_PROFILE_URL, access_token, deadline, "microsoft"
    )
    account_id = profile.get("id")
    account = profile.get("mail") or profile.get("userPrincipalName")
    if not isinstance(account, str) or not account:
        account = profile.get("displayName")
    if (
        not isinstance(account_id, str)
        or not account_id
        or not isinstance(account, str)
        or not account.strip()
    ):
        raise ApiError(400, "Microsoft could not verify the account")
    return (
        account_id[:200],
        account.strip()[:254],
        {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": int(time.time()) + int(expires_in),
        },
    )


def _notion_connection(token: dict) -> tuple[str, str, dict]:
    access_token = token.get("access_token")
    workspace_id = token.get("workspace_id")
    workspace_name = token.get("workspace_name") or "Notion workspace"
    if (
        token.get("token_type") != "bearer"
        or not isinstance(access_token, str)
        or not access_token
        or not isinstance(workspace_id, str)
        or not workspace_id
        or not isinstance(workspace_name, str)
        or not workspace_name.strip()
    ):
        raise ApiError(400, "Notion returned an invalid connection")
    credential = {"accessToken": access_token}
    refresh_token = token.get("refresh_token")
    if isinstance(refresh_token, str) and refresh_token:
        credential["refreshToken"] = refresh_token
    return workspace_id[:200], workspace_name.strip()[:254], credential


def _external_callback(query: dict) -> dict:
    return_url = DEFAULT_RETURN_URL
    provider = "connection"
    state: dict = {}
    credential: dict = {}
    persistence_attempted = False
    deadline = time.monotonic() + CALLBACK_BUDGET_SECONDS
    try:
        state = _consume_state(query.get("state"))
        provider = state["provider"]
        return_url = _return_url(state.get("returnUrl"))
        _ensure_account_active(state["userId"])
        if query.get("error"):
            raise ApiError(400, f"{provider.title()} access was not approved")
        code = query.get("code")
        verifier = state.get("verifier")
        if not isinstance(code, str) or not isinstance(verifier, str):
            raise ApiError(400, f"{provider.title()} did not return an authorization code")
        token = _exchange_code(provider, code, verifier, deadline)
        if provider == "slack":
            account_id, account, credential = _slack_connection(token)
        elif provider == "microsoft":
            account_id, account, credential = _microsoft_connection(token, deadline)
        else:
            account_id, account, credential = _notion_connection(token)
        persistence_attempted = True
        catalog.save_external_oauth_connection(
            state["userId"],
            provider,
            account,
            account_id,
            credential,
            state["clientSecretArn"],
            list(EXTERNAL_PROVIDER_SPECS[provider]["scopes"]),
        )
        return _redirect(_result_url(return_url, "connected", provider))
    except (ApiError, CatalogError, KeyError, TypeError, ValueError):
        if not persistence_attempted and credential and state:
            try:
                catalog.revoke_unused_external_token(
                    provider, credential, state["clientSecretArn"]
                )
            except (BotoCoreError, ClientError, KeyError, TypeError, ValueError):
                logger.warning("Could not revoke unused %s OAuth access", provider)
        logger.exception("External OAuth callback failed for %s", provider)
        return _redirect(_result_url(return_url, "error", provider))


__all__ = [
    "EXTERNAL_PROVIDER_SPECS",
    "_begin_microsoft_authorization",
    "_begin_notion_authorization",
    "_begin_slack_authorization",
    "_external_callback",
]
