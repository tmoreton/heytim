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

from .google_oauth import _pkce_challenge, _redirect, _return_url, _state_key
from .support import ApiError, _ensure_account_active, catalog, table

X_AUTH_URL = "https://x.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.x.com/2/oauth2/token"  # nosec B105 - fixed OAuth URL.
X_PROFILE_URL = "https://api.x.com/2/users/me"
X_SCOPES = ("tweet.read", "users.read", "offline.access")
OAUTH_STATE_SECONDS = 10 * 60
CALLBACK_BUDGET_SECONDS = 12.0
REQUEST_MAX_SECONDS = 4.0
DEFAULT_RETURN_URL = "https://app.froggybot.com/app?oauth=x"

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


def _oauth_client() -> tuple[str, str, str]:
    secret_arn = os.environ.get("X_OAUTH_SECRET_ARN")
    if not secret_arn:
        raise ApiError(503, "X connections are not configured")
    response = _secret_client().get_secret_value(SecretId=secret_arn)
    raw = response.get("SecretString")
    try:
        document = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError as exc:
        raise ApiError(503, "X connections are not configured") from exc
    client_id = document.get("clientId") if isinstance(document, dict) else None
    client_secret = document.get("clientSecret") if isinstance(document, dict) else None
    if (
        not isinstance(client_id, str)
        or not re.fullmatch(r"[A-Za-z0-9._~-]{8,200}", client_id)
        or not isinstance(client_secret, str)
        or not 20 <= len(client_secret) <= 500
    ):
        raise ApiError(503, "X connections are not configured")
    return client_id, client_secret, secret_arn


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining < 0.5:
        raise ApiError(400, "The X connection took too long. Please try again.")
    return min(REQUEST_MAX_SECONDS, remaining)


def _begin_x_authorization(user_id: str, value: dict) -> dict:
    return_url = _return_url(value.get("returnUrl"))
    client_id, _, client_secret_arn = _oauth_client()
    redirect_uri = os.environ.get("X_OAUTH_REDIRECT_URI")
    if not redirect_uri:
        raise ApiError(503, "X connections are not configured")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    table.put_item(
        Item={
            **_state_key(state),
            "entity": "OAUTH_STATE",
            "userId": user_id,
            "provider": "x",
            "verifier": verifier,
            "returnUrl": return_url,
            "clientSecretArn": client_secret_arn,
            "expiresAt": int(time.time()) + OAUTH_STATE_SECONDS,
        }
    )
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(X_SCOPES),
            "state": state,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return {"authorizationUrl": f"{X_AUTH_URL}?{query}"}


def _consume_state(state: Any) -> dict:
    if not isinstance(state, str) or not 20 <= len(state) <= 200:
        raise ApiError(400, "The X connection expired. Please try again.")
    result = table.delete_item(Key=_state_key(state), ReturnValues="ALL_OLD")
    item = result.get("Attributes")
    if (
        not item
        or item.get("provider") != "x"
        or int(item.get("expiresAt", 0)) < int(time.time())
    ):
        raise ApiError(400, "The X connection expired. Please try again.")
    return item


def _exchange_code(code: str, verifier: str, deadline: float) -> dict:
    client_id, client_secret, _ = _oauth_client()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(
        X_TOKEN_URL,
        data=urllib.parse.urlencode(
            {
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": os.environ["X_OAUTH_REDIRECT_URI"],
            }
        ).encode(),
        headers={
            "authorization": f"Basic {basic}",
            "content-type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - fixed X OAuth endpoint.
            request, timeout=_remaining_timeout(deadline)
        ) as response:
            value = json.loads(response.read(100_001).decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(400, "X could not complete the connection") from exc
    if not isinstance(value, dict):
        raise ApiError(400, "X returned an invalid response")
    return value


def _profile(access_token: str, deadline: float) -> tuple[str, str]:
    request = urllib.request.Request(
        f"{X_PROFILE_URL}?user.fields=id,name,username,protected",
        headers={"authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - fixed X API endpoint.
            request, timeout=_remaining_timeout(deadline)
        ) as response:
            value = json.loads(response.read(100_001).decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(400, "X could not verify the account") from exc
    data = value.get("data") if isinstance(value, dict) else None
    user_id = data.get("id") if isinstance(data, dict) else None
    username = data.get("username") if isinstance(data, dict) else None
    if (
        not isinstance(user_id, str)
        or not re.fullmatch(r"[0-9]{1,30}", user_id)
        or not isinstance(username, str)
        or not re.fullmatch(r"[A-Za-z0-9_]{1,50}", username)
    ):
        raise ApiError(400, "X could not verify the account")
    return user_id, f"@{username}"


def _result_url(return_url: str, status: str) -> str:
    parsed = urllib.parse.urlsplit(return_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"connection": "x", "status": status})
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )


def _x_callback(query: dict) -> dict:
    return_url = DEFAULT_RETURN_URL
    deadline = time.monotonic() + CALLBACK_BUDGET_SECONDS
    refresh_token = None
    persistence_attempted = False
    try:
        state = _consume_state(query.get("state"))
        return_url = _return_url(state.get("returnUrl"))
        _ensure_account_active(state["userId"])
        if query.get("error"):
            raise ApiError(400, "X access was not approved")
        code = query.get("code")
        verifier = state.get("verifier")
        if not isinstance(code, str) or not isinstance(verifier, str):
            raise ApiError(400, "X did not return an authorization code")
        token = _exchange_code(code, verifier, deadline)
        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        granted = set(str(token.get("scope", "")).split())
        if granted != set(X_SCOPES):
            raise ApiError(400, "X read and offline access are required")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise ApiError(400, "X did not return reusable account access")
        expires_in = token.get("expires_in")
        expires_at = (
            int(time.time()) + int(expires_in)
            if isinstance(expires_in, (int, float)) and int(expires_in) > 0
            else None
        )
        account_id, account = _profile(access_token, deadline)
        persistence_attempted = True
        catalog.save_oauth_api_connection(
            state["userId"],
            "x",
            account,
            account_id,
            refresh_token,
            state["clientSecretArn"],
            list(X_SCOPES),
            access_token=access_token,
            expires_at=expires_at,
        )
        return _redirect(_result_url(return_url, "connected"))
    except (ApiError, CatalogError, KeyError, TypeError, ValueError):
        if not persistence_attempted and isinstance(refresh_token, str):
            try:
                catalog.revoke_unused_x_token(refresh_token, state["clientSecretArn"])
            except (BotoCoreError, ClientError, KeyError, TypeError, ValueError):
                logger.warning("Could not revoke unused X OAuth access")
        logger.exception("X OAuth callback failed")
        return _redirect(_result_url(return_url, "error"))


__all__ = ["X_SCOPES", "_begin_x_authorization", "_x_callback"]
