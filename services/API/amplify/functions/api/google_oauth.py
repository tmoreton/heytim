from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import boto3
from botocore.config import Config
from shared.catalog import CatalogError

from .support import ApiError, _ensure_account_active, catalog, table

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_ENDPOINT = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
)
YOUTUBE_SCOPES = ("https://www.googleapis.com/auth/youtube.readonly",)
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
GOOGLE_WORKSPACE_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
    "https://www.googleapis.com/auth/calendar.events.readonly",
)
GOOGLE_DRIVE_ABOUT_URL = "https://www.googleapis.com/drive/v3/about"
GOOGLE_PROVIDER_SCOPES = {
    "gmail": GMAIL_SCOPES,
    "youtube": YOUTUBE_SCOPES,
    "google_workspace": GOOGLE_WORKSPACE_SCOPES,
}
OAUTH_STATE_SECONDS = 10 * 60
OAUTH_CALLBACK_BUDGET_SECONDS = 12.0
OAUTH_REQUEST_MAX_SECONDS = 4.0
DEFAULT_RETURN_URL = "https://heytim.ai/app?oauth=gmail"
ALLOWED_WEB_RETURN_HOSTS = {
    "heytim.ai",
    "heytim.expo.app",
    "localhost",
}

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


def _oauth_client() -> tuple[str, str]:
    secret_arn = os.environ.get("GOOGLE_OAUTH_SECRET_ARN")
    if not secret_arn:
        raise ApiError(503, "Gmail connections are not configured")
    response = _secret_client().get_secret_value(SecretId=secret_arn)
    raw = response.get("SecretString")
    if not isinstance(raw, str):
        raise ApiError(503, "Gmail connections are not configured")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(503, "Gmail connections are not configured") from exc
    client = value.get("web", value) if isinstance(value, dict) else {}
    client_id = client.get("client_id")
    client_secret = client.get("client_secret")
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        raise ApiError(503, "Gmail connections are not configured")
    return client_id, client_secret


def _return_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise ApiError(400, "The return link is invalid", code="invalid_return_url")
    parsed = urllib.parse.urlsplit(value)
    is_native = (
        parsed.scheme in {"heytim"}
        and parsed.hostname == "app"
        and parsed.path in {"", "/"}
        and parsed.fragment == ""
    )
    is_web = (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in ALLOWED_WEB_RETURN_HOSTS
        and (parsed.scheme == "https" or parsed.hostname == "localhost")
        and parsed.username is None
        and parsed.password is None
        and parsed.fragment == ""
    )
    if not is_native and not is_web:
        raise ApiError(400, "The return link is invalid", code="invalid_return_url")
    return value


def _state_key(state: str) -> dict:
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    return {"pk": f"OAUTH#{digest}", "sk": "STATE"}


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _begin_google_authorization(user_id: str, value: dict, provider_id: str) -> dict:
    scopes = GOOGLE_PROVIDER_SCOPES.get(provider_id)
    if not scopes:
        raise ApiError(404, "Google connection provider not found")
    return_url = _return_url(value.get("returnUrl"))
    client_id, _ = _oauth_client()
    redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    client_secret_arn = os.environ.get("GOOGLE_OAUTH_SECRET_ARN")
    if not redirect_uri or not client_secret_arn:
        raise ApiError(503, "Gmail connections are not configured")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    expires_at = int(time.time()) + OAUTH_STATE_SECONDS
    table.put_item(
        Item={
            **_state_key(state),
            "entity": "OAUTH_STATE",
            "userId": user_id,
            "provider": provider_id,
            "verifier": verifier,
            "returnUrl": return_url,
            "clientSecretArn": client_secret_arn,
            "expiresAt": expires_at,
        }
    )
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",
            "prompt": "consent select_account",
            "include_granted_scopes": "false",
            "state": state,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return {"authorizationUrl": f"{GOOGLE_AUTH_URL}?{query}"}


def _begin_gmail_authorization(user_id: str, value: dict) -> dict:
    return _begin_google_authorization(user_id, value, "gmail")


def _begin_youtube_authorization(user_id: str, value: dict) -> dict:
    return _begin_google_authorization(user_id, value, "youtube")


def _begin_google_workspace_authorization(user_id: str, value: dict) -> dict:
    return _begin_google_authorization(user_id, value, "google_workspace")


def _consume_state(state: Any) -> dict:
    if not isinstance(state, str) or not 20 <= len(state) <= 200:
        raise ApiError(400, "The Gmail connection expired. Please try again.")
    result = table.delete_item(Key=_state_key(state), ReturnValues="ALL_OLD")
    item = result.get("Attributes")
    if (
        not item
        or item.get("provider") not in GOOGLE_PROVIDER_SCOPES
        or int(item.get("expiresAt", 0)) < int(time.time())
    ):
        raise ApiError(400, "The Gmail connection expired. Please try again.")
    return item


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining < 0.5:
        raise ApiError(400, "The Gmail connection took too long. Please try again.")
    return min(OAUTH_REQUEST_MAX_SECONDS, remaining)


def _post_json(url: str, fields: dict[str, str], deadline: float) -> dict:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=_remaining_timeout(deadline)
        ) as response:  # nosec B310
            value = json.loads(response.read(100_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(400, "Google could not complete the Gmail connection") from exc
    if not isinstance(value, dict):
        raise ApiError(400, "Google could not complete the Gmail connection")
    return value


def _exchange_code(code: str, verifier: str, deadline: float) -> dict:
    client_id, client_secret = _oauth_client()
    return _post_json(
        GOOGLE_OAUTH_ENDPOINT,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": os.environ["GOOGLE_OAUTH_REDIRECT_URI"],
        },
        deadline,
    )


def _gmail_profile(access_token: str, deadline: float) -> str:
    request = urllib.request.Request(
        GMAIL_PROFILE_URL,
        headers={"authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=_remaining_timeout(deadline)
        ) as response:  # nosec B310
            value = json.loads(response.read(100_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(400, "Google could not verify the Gmail account") from exc
    email = value.get("emailAddress") if isinstance(value, dict) else None
    if not isinstance(email, str) or "@" not in email:
        raise ApiError(400, "Google could not verify the Gmail account")
    return email


def _youtube_channel(access_token: str, deadline: float) -> tuple[str, str]:
    query = urllib.parse.urlencode(
        {"part": "id,snippet", "mine": "true", "maxResults": "1"}
    )
    request = urllib.request.Request(
        f"{YOUTUBE_CHANNELS_URL}?{query}",
        headers={"authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - fixed Google API endpoint.
            request, timeout=_remaining_timeout(deadline)
        ) as response:
            value = json.loads(response.read(100_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(400, "Google could not verify the YouTube channel") from exc
    items = value.get("items") if isinstance(value, dict) else None
    channel = items[0] if isinstance(items, list) and items else None
    snippet = channel.get("snippet") if isinstance(channel, dict) else None
    channel_id = channel.get("id") if isinstance(channel, dict) else None
    title = snippet.get("title") if isinstance(snippet, dict) else None
    if (
        not isinstance(channel_id, str)
        or not channel_id
        or not isinstance(title, str)
        or not title.strip()
    ):
        raise ApiError(400, "The Google account does not have a YouTube channel")
    return channel_id, title.strip()[:100]


def _google_workspace_account(access_token: str, deadline: float) -> tuple[str, str]:
    query = urllib.parse.urlencode(
        {"fields": "user(displayName,emailAddress,permissionId)"}
    )
    request = urllib.request.Request(
        f"{GOOGLE_DRIVE_ABOUT_URL}?{query}",
        headers={"authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - fixed Google API endpoint.
            request, timeout=_remaining_timeout(deadline)
        ) as response:
            value = json.loads(response.read(100_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(400, "Google could not verify the Workspace account") from exc
    user = value.get("user") if isinstance(value, dict) else None
    account_id = user.get("permissionId") if isinstance(user, dict) else None
    email = user.get("emailAddress") if isinstance(user, dict) else None
    display_name = user.get("displayName") if isinstance(user, dict) else None
    account = email if isinstance(email, str) and "@" in email else display_name
    if (
        not isinstance(account_id, str)
        or not account_id
        or not isinstance(account, str)
        or not account.strip()
    ):
        raise ApiError(400, "Google could not verify the Workspace account")
    return account_id, account.strip()[:254]


def _result_url(return_url: str, status: str, provider: str = "gmail") -> str:
    parsed = urllib.parse.urlsplit(return_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"connection": provider, "status": status})
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )


def _redirect(location: str) -> dict:
    return {
        "statusCode": 302,
        "headers": {
            "location": location,
            "cache-control": "no-store",
            "content-type": "text/plain",
        },
        "body": "Returning to HeyTim",
    }


def _google_callback(query: dict) -> dict:
    return_url = DEFAULT_RETURN_URL
    provider = "gmail"
    deadline = time.monotonic() + OAUTH_CALLBACK_BUDGET_SECONDS
    refresh_token = None
    persistence_attempted = False
    try:
        state = _consume_state(query.get("state"))
        provider = state["provider"]
        return_url = _return_url(state.get("returnUrl"))
        _ensure_account_active(state["userId"])
        if query.get("error"):
            raise ApiError(400, "Google access was not approved")
        code = query.get("code")
        verifier = state.get("verifier")
        if not isinstance(code, str) or not isinstance(verifier, str):
            raise ApiError(400, "Google did not return an authorization code")
        token = _exchange_code(code, verifier, deadline)
        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        granted = set(str(token.get("scope", "")).split())
        required_scopes = set(GOOGLE_PROVIDER_SCOPES[provider])
        if granted != required_scopes:
            raise ApiError(400, f"{provider.title()} requested access is required")
        if not isinstance(access_token, str) or not isinstance(refresh_token, str):
            raise ApiError(400, "Google did not return reusable Gmail access")
        client_secret_arn = state["clientSecretArn"]
        if provider == "gmail":
            account = _gmail_profile(access_token, deadline)
            persistence_attempted = True
            catalog.save_gmail_connection(
                state["userId"],
                account,
                refresh_token,
                client_secret_arn,
            )
        elif provider == "youtube":
            channel_id, account = _youtube_channel(access_token, deadline)
            persistence_attempted = True
            catalog.save_oauth_api_connection(
                state["userId"],
                "youtube",
                account,
                channel_id,
                refresh_token,
                client_secret_arn,
                list(YOUTUBE_SCOPES),
            )
        else:
            account_id, account = _google_workspace_account(access_token, deadline)
            persistence_attempted = True
            catalog.save_google_workspace_connection(
                state["userId"],
                account,
                account_id,
                refresh_token,
                client_secret_arn,
                list(GOOGLE_WORKSPACE_SCOPES),
            )
        return _redirect(_result_url(return_url, "connected", provider))
    except (ApiError, CatalogError, KeyError, TypeError, ValueError):
        if not persistence_attempted and isinstance(refresh_token, str):
            catalog.revoke_unused_google_token(refresh_token)
        logger.exception("Google OAuth callback failed for %s", provider)
        return _redirect(_result_url(return_url, "error", provider))


def _gmail_callback(query: dict) -> dict:
    """Compatibility alias for existing callback tests and deployed route callers."""
    return _google_callback(query)


__all__ = [
    "GMAIL_SCOPES",
    "GOOGLE_WORKSPACE_SCOPES",
    "YOUTUBE_SCOPES",
    "_begin_gmail_authorization",
    "_begin_google_workspace_authorization",
    "_begin_youtube_authorization",
    "_gmail_callback",
    "_google_callback",
]
