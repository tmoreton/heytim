from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import boto3
from botocore.config import Config
from strands import tool

from .collaboration_provider_tools import (
    hubspot_tools as _hubspot_tools,
)
from .collaboration_provider_tools import (
    jira_tools as _jira_tools,
)
from .collaboration_provider_tools import (
    microsoft_tools as _microsoft_tools,
)
from .collaboration_provider_tools import (
    notion_tools as _notion_tools,
)
from .collaboration_provider_tools import (
    slack_tools as _slack_tools,
)
from .collaboration_provider_tools import (
    teams_tools as _teams_tools,
)
from .collaboration_provider_tools import (
    x_tools as _x_tools,
)
from .collaboration_provider_tools import (
    zoom_tools as _zoom_tools,
)
from .provider_binding import validated_provider_binding
from .youtube_provider_tools import _youtube_tools

CONNECTION_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/connections/[a-f0-9]{24}/"
    r"connection_[a-f0-9]{20}-[a-f0-9]{12}-[A-Za-z0-9]+$"
)
GOOGLE_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/google-[A-Za-z0-9-]+$"
)
X_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/x-[A-Za-z0-9-]+$"
)
SLACK_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/slack-[A-Za-z0-9-]+$"
)
MICROSOFT_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/microsoft-[A-Za-z0-9-]+$"
)
NOTION_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/notion-[A-Za-z0-9-]+$"
)
HUBSPOT_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/hubspot-[A-Za-z0-9-]+$"
)
JIRA_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/jira-[A-Za-z0-9-]+$"
)
ZOOM_CLIENT_SECRET_ARN_PATTERN = re.compile(
    r"^arn:aws:secretsmanager:[a-z0-9-]+:[0-9]{12}:"
    r"secret:frogbot/oauth/zoom-[A-Za-z0-9-]+$"
)
JIRA_SITE_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
)
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"
X_TOKEN_URL = "https://api.x.com/2/oauth2/token"
X_API_URL = "https://api.x.com/2"
SLACK_API_URL = "https://slack.com/api"
SLACK_TOKEN_URL = f"{SLACK_API_URL}/oauth.v2.access"
MICROSOFT_API_URL = "https://graph.microsoft.com/v1.0"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
NOTION_API_URL = "https://api.notion.com/v1"
NOTION_API_VERSION = "2026-03-11"
HUBSPOT_API_URL = "https://api.hubapi.com"
HUBSPOT_TOKEN_URL = f"{HUBSPOT_API_URL}/oauth/2026-03/token"
JIRA_API_URL = "https://api.atlassian.com"
JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"
ZOOM_API_URL = "https://api.zoom.us/v2"
PROVIDER_SCOPES = {
    "youtube": {"https://www.googleapis.com/auth/youtube.readonly"},
    "x": {"tweet.read", "users.read", "offline.access"},
    "slack": {
        "search:read.public",
        "search:read.private",
        "search:read.mpim",
        "search:read.im",
        "search:read.files",
        "search:read.users",
        "channels:history",
        "groups:history",
        "im:history",
        "mpim:history",
    },
    "microsoft": {
        "openid",
        "profile",
        "email",
        "offline_access",
        "User.Read",
        "Mail.Read",
        "Calendars.Read",
        "Files.Read.All",
        "Sites.Read.All",
    },
    "microsoft_teams": {
        "openid", "profile", "email", "offline_access", "User.Read",
        "Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Read.All",
    },
    "notion": {"read_content"},
    "hubspot": {
        "crm.objects.contacts.read",
        "crm.objects.companies.read",
        "crm.objects.deals.read",
    },
    "jira": {"offline_access", "read:jira-work"},
    "zoom": {"user:read:user", "meeting:read:list_meetings", "meeting:read:meeting"},
}
PROVIDER_CLIENT_SECRET_PATTERNS = {
    "youtube": GOOGLE_CLIENT_SECRET_ARN_PATTERN,
    "x": X_CLIENT_SECRET_ARN_PATTERN,
    "slack": SLACK_CLIENT_SECRET_ARN_PATTERN,
    "microsoft": MICROSOFT_CLIENT_SECRET_ARN_PATTERN,
    "microsoft_teams": MICROSOFT_CLIENT_SECRET_ARN_PATTERN,
    "notion": NOTION_CLIENT_SECRET_ARN_PATTERN,
    "hubspot": HUBSPOT_CLIENT_SECRET_ARN_PATTERN,
    "jira": JIRA_CLIENT_SECRET_ARN_PATTERN,
    "zoom": ZOOM_CLIENT_SECRET_ARN_PATTERN,
}
_secrets_manager = None


def _secret_client():
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = boto3.client(
            "secretsmanager",
            config=Config(
                retries={"total_max_attempts": 4, "mode": "adaptive"},
                connect_timeout=3,
                read_timeout=10,
            ),
        )
    return _secrets_manager


def _secret_value(secret_arn: str) -> str:
    response = _secret_client().get_secret_value(SecretId=secret_arn)
    value = response.get("SecretString")
    if not isinstance(value, str) or not value:
        raise ValueError("Provider connection credential is unavailable")
    return value


def _json_secret(secret_arn: str) -> dict:
    try:
        value = json.loads(_secret_value(secret_arn))
    except json.JSONDecodeError as exc:
        raise ValueError("Provider connection credential is invalid") from exc
    if not isinstance(value, dict):
        raise TypeError("Provider connection credential is invalid")
    return value


def _oauth_client(binding: dict) -> tuple[str, str]:
    document = _json_secret(binding["oauthClientSecretArn"])
    client = (
        document.get("web", document) if binding["provider"] == "youtube" else document
    )
    if not isinstance(client, dict):
        raise TypeError("Provider OAuth configuration is invalid")
    client_id_key = "client_id" if binding["provider"] == "youtube" else "clientId"
    client_secret_key = (
        "client_secret" if binding["provider"] == "youtube" else "clientSecret"
    )
    client_id = client.get(client_id_key)
    client_secret = client.get(client_secret_key)
    if not all(
        isinstance(value, str) and value for value in (client_id, client_secret)
    ):
        raise ValueError("Provider OAuth configuration is invalid")
    return client_id, client_secret


def _token_json(request: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(  # nosec B310 - callers use fixed OAuth hosts.
            request, timeout=10
        ) as response:
            value = json.loads(response.read(100_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Provider OAuth access is unavailable") from exc
    if not isinstance(value, dict):
        raise TypeError("Provider OAuth access is unavailable")
    return value


def _google_access_token(binding: dict) -> str:
    credential = _json_secret(binding["secretArn"])
    refresh_token = credential.get("refreshToken")
    client_id, client_secret = _oauth_client(binding)
    if not isinstance(refresh_token, str) or not refresh_token:
        raise ValueError("Google OAuth credential is invalid")
    request = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=urllib.parse.urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8"),
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    value = _token_json(request)
    access_token = value.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("Google OAuth access is unavailable")
    return access_token


def _cached_x_access_token(credential: dict) -> str | None:
    access_token = credential.get("accessToken")
    expires_at = credential.get("expiresAt")
    if (
        isinstance(access_token, str)
        and access_token
        and isinstance(expires_at, int)
        and not isinstance(expires_at, bool)
        and expires_at > int(time.time()) + 60
    ):
        return access_token
    return None


def _x_access_token(binding: dict) -> str:
    credential = _json_secret(binding["secretArn"])
    cached = _cached_x_access_token(credential)
    if cached:
        return cached
    refresh_token = credential.get("refreshToken")
    client_id, client_secret = _oauth_client(binding)
    if not isinstance(refresh_token, str) or not refresh_token:
        raise ValueError("X OAuth credential is invalid")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(
        X_TOKEN_URL,
        data=urllib.parse.urlencode(
            {"refresh_token": refresh_token, "grant_type": "refresh_token"}
        ).encode("utf-8"),
        headers={
            "authorization": f"Basic {basic}",
            "content-type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        value = _token_json(request)
    except ValueError:
        latest = _json_secret(binding["secretArn"])
        cached = _cached_x_access_token(latest)
        if cached:
            return cached
        raise
    access_token = value.get("access_token")
    rotated_refresh_token = value.get("refresh_token")
    expires_in = value.get("expires_in")
    if (
        not isinstance(access_token, str)
        or not access_token
        or not isinstance(rotated_refresh_token, str)
        or not rotated_refresh_token
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or int(expires_in) <= 0
    ):
        raise ValueError("X OAuth access is unavailable")
    replacement = {
        "refreshToken": rotated_refresh_token,
        "accessToken": access_token,
        "expiresAt": int(time.time()) + int(expires_in),
    }
    _secret_client().put_secret_value(
        SecretId=binding["secretArn"],
        SecretString=json.dumps(replacement, separators=(",", ":")),
    )
    return access_token


def _cached_access_token(credential: dict) -> str | None:
    access_token = credential.get("accessToken")
    expires_at = credential.get("expiresAt")
    if (
        isinstance(access_token, str)
        and access_token
        and isinstance(expires_at, int)
        and not isinstance(expires_at, bool)
        and expires_at > int(time.time()) + 60
    ):
        return access_token
    return None


def _rotating_provider_access_token(binding: dict) -> str:
    provider = binding["provider"]
    credential = _json_secret(binding["secretArn"])
    cached = _cached_access_token(credential)
    if cached:
        return cached
    refresh_token = credential.get("refreshToken")
    client_id, client_secret = _oauth_client(binding)
    if not isinstance(refresh_token, str) or not refresh_token:
        raise ValueError(f"{provider.title()} OAuth credential is invalid")
    if provider == "slack":
        url = SLACK_TOKEN_URL
        fields = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    elif provider in {"microsoft", "microsoft_teams"}:
        url = MICROSOFT_TOKEN_URL
        fields = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(binding["scopes"]),
        }
    elif provider == "hubspot":
        url = HUBSPOT_TOKEN_URL
        fields = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    elif provider == "jira":
        url = JIRA_TOKEN_URL
        fields = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
    elif provider == "zoom":
        url = ZOOM_TOKEN_URL
        fields = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    else:
        raise ValueError("Rotating OAuth provider is unsupported")
    request = urllib.request.Request(
        url,
        data=(
            json.dumps(fields, separators=(",", ":")).encode()
            if provider == "jira"
            else urllib.parse.urlencode(fields).encode()
        ),
        headers={
            "content-type": (
                "application/json" if provider == "jira" else "application/x-www-form-urlencoded"
            ),
            **(
                {"authorization": "Basic " + base64.b64encode(
                    f"{client_id}:{client_secret}".encode()
                ).decode()}
                if provider == "zoom" else {}
            ),
        },
        method="POST",
    )
    try:
        value = _token_json(request)
    except ValueError:
        latest = _json_secret(binding["secretArn"])
        cached = _cached_access_token(latest)
        if cached:
            return cached
        raise
    token = value.get("authed_user") if provider == "slack" else value
    if not isinstance(token, dict):
        token = value
    access_token = token.get("access_token")
    replacement_refresh_token = token.get("refresh_token") or refresh_token
    expires_in = token.get("expires_in")
    if (
        (provider == "slack" and value.get("ok") is not True)
        or not isinstance(access_token, str)
        or not access_token
        or not isinstance(replacement_refresh_token, str)
        or not replacement_refresh_token
        or (provider == "jira" and not isinstance(token.get("refresh_token"), str))
        or isinstance(expires_in, bool)
        or not isinstance(expires_in, (int, float))
        or int(expires_in) <= 0
    ):
        raise ValueError(f"{provider.title()} OAuth access is unavailable")
    replacement = {
        "refreshToken": replacement_refresh_token,
        "accessToken": access_token,
        "expiresAt": int(time.time()) + int(expires_in),
    }
    _secret_client().put_secret_value(
        SecretId=binding["secretArn"],
        SecretString=json.dumps(replacement, separators=(",", ":")),
    )
    return access_token


def _provider_access_token(binding: dict) -> str:
    provider = binding["provider"]
    if provider == "youtube":
        return _google_access_token(binding)
    if provider == "x":
        return _x_access_token(binding)
    if provider in {"slack", "microsoft", "microsoft_teams", "hubspot", "jira", "zoom"}:
        return _rotating_provider_access_token(binding)
    if provider == "notion":
        credential = _json_secret(binding["secretArn"])
        access_token = credential.get("accessToken")
        if isinstance(access_token, str) and access_token:
            return access_token
        raise ValueError("Notion OAuth credential is invalid")
    raise ValueError("OAuth provider connection is unsupported")


def _api_json(url: str, access_token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/json",
            "authorization": f"Bearer {access_token}",
            "user-agent": "HeyTim/1.0",
        },
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - callers assemble fixed API hosts.
            request, timeout=15
        ) as response:
            value = json.loads(response.read(500_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Connected provider data is unavailable") from exc
    if not isinstance(value, dict):
        raise TypeError("Connected provider returned an invalid response")
    return value


def _provider_api_json(
    url: str,
    access_token: str,
    *,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    request_headers = {
        "accept": "application/json",
        "authorization": f"Bearer {access_token}",
        "user-agent": "HeyTim/1.0",
        **(headers or {}),
    }
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        request_headers["content-type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(
        url, data=data, headers=request_headers, method=method
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - callers use fixed API hosts.
            request, timeout=15
        ) as response:
            value = json.loads(response.read(500_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Connected provider data is unavailable") from exc
    if not isinstance(value, dict):
        raise TypeError("Connected provider returned an invalid response")
    return value


def _record(usage: Any, provider: str, operation: str) -> None:
    if usage is not None:
        usage.observe_tool(provider, operation)


def _limit(value: int, *, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"max_results must be between {minimum} and {maximum}")
    return value


def _text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} is invalid")
    return value.strip()


def provider_connection_tools(binding: dict, usage: Any = None) -> list[Any]:
    from .mcp_connections import _bounded_tool_name

    if binding["provider"] == "youtube":
        provider_tools = _youtube_tools(binding, usage)
    elif binding["provider"] == "x":
        provider_tools = _x_tools(binding, usage)
    elif binding["provider"] == "slack":
        provider_tools = _slack_tools(binding, usage)
    elif binding["provider"] == "microsoft":
        provider_tools = _microsoft_tools(binding, usage)
    elif binding["provider"] == "microsoft_teams":
        provider_tools = _teams_tools(binding, usage)
    elif binding["provider"] == "notion":
        provider_tools = _notion_tools(binding, usage)
    elif binding["provider"] == "hubspot":
        provider_tools = _hubspot_tools(binding, usage)
    elif binding["provider"] == "jira":
        provider_tools = _jira_tools(binding, usage)
    elif binding["provider"] == "zoom":
        provider_tools = _zoom_tools(binding, usage)
    else:
        raise ValueError("OAuth provider connection is unsupported")

    label = binding.get("accountLabel") or binding["provider"]
    return [
        tool(
            name=_bounded_tool_name(binding["id"], item.tool_name),
            description=f"{item.tool_spec['description']} Connected account: {label}.",
        )(item.__wrapped__)
        for item in provider_tools
    ]


__all__ = ["provider_connection_tools", "validated_provider_binding"]
