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
    microsoft_tools as _microsoft_tools,
)
from .collaboration_provider_tools import (
    notion_tools as _notion_tools,
)
from .collaboration_provider_tools import (
    slack_tools as _slack_tools,
)
from .collaboration_provider_tools import (
    x_tools as _x_tools,
)

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
    "notion": {"read_content"},
}
PROVIDER_CLIENT_SECRET_PATTERNS = {
    "youtube": GOOGLE_CLIENT_SECRET_ARN_PATTERN,
    "x": X_CLIENT_SECRET_ARN_PATTERN,
    "slack": SLACK_CLIENT_SECRET_ARN_PATTERN,
    "microsoft": MICROSOFT_CLIENT_SECRET_ARN_PATTERN,
    "notion": NOTION_CLIENT_SECRET_ARN_PATTERN,
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


def validated_provider_binding(tool_id: str, runtime: dict) -> dict:
    provider = runtime.get("provider")
    secret_arn = runtime.get("secretArn")
    client_secret_arn = runtime.get("oauthClientSecretArn")
    scopes = runtime.get("scopes")
    expected_scopes = PROVIDER_SCOPES.get(provider)
    expected_oauth_provider = "google" if provider == "youtube" else provider
    expected_client_pattern = PROVIDER_CLIENT_SECRET_PATTERNS.get(provider)
    if (
        expected_scopes is None
        or runtime.get("authType") != "oauth"
        or runtime.get("oauthProvider") != expected_oauth_provider
        or not isinstance(secret_arn, str)
        or not CONNECTION_SECRET_ARN_PATTERN.fullmatch(secret_arn)
        or not isinstance(client_secret_arn, str)
        or not expected_client_pattern.fullmatch(client_secret_arn)
        or not isinstance(scopes, list)
        or len(scopes) != len(set(scopes))
        or set(scopes) != expected_scopes
    ):
        raise ValueError(f"OAuth provider connection is invalid: {tool_id}")
    return {
        "id": tool_id,
        "kind": "provider_api",
        "provider": provider,
        "authType": "oauth",
        "oauthProvider": expected_oauth_provider,
        "secretArn": secret_arn,
        "oauthClientSecretArn": client_secret_arn,
        "scopes": scopes,
    }


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
    elif provider == "microsoft":
        url = MICROSOFT_TOKEN_URL
        fields = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(binding["scopes"]),
        }
    else:
        raise ValueError("Rotating OAuth provider is unsupported")
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
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
    if provider in {"slack", "microsoft"}:
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
            "user-agent": "FroggyBot/1.0",
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
        "user-agent": "FroggyBot/1.0",
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


def _youtube_tools(binding: dict, usage: Any) -> list[Any]:
    @tool
    def youtube_my_channel() -> str:
        """Read the connected user's YouTube channel profile and aggregate statistics."""
        _record(usage, "youtube", "youtube_my_channel")
        query = urllib.parse.urlencode(
            {
                "part": "id,snippet,contentDetails,statistics,status",
                "mine": "true",
                "maxResults": "1",
            }
        )
        value = _api_json(
            f"{YOUTUBE_API_URL}/channels?{query}", _google_access_token(binding)
        )
        items = value.get("items")
        channel = items[0] if isinstance(items, list) and items else None
        if not isinstance(channel, dict):
            raise TypeError("The connected Google account has no YouTube channel")
        return json.dumps(
            {
                "id": channel.get("id"),
                "snippet": channel.get("snippet"),
                "statistics": channel.get("statistics"),
                "status": channel.get("status"),
            },
            separators=(",", ":"),
        )

    @tool
    def youtube_my_videos(max_results: int = 10) -> str:
        """List recent uploads from the connected user's own YouTube channel."""
        count = _limit(max_results, minimum=1, maximum=50)
        _record(usage, "youtube", "youtube_my_videos")
        access_token = _google_access_token(binding)
        channel_query = urllib.parse.urlencode(
            {"part": "contentDetails", "mine": "true", "maxResults": "1"}
        )
        channel_value = _api_json(
            f"{YOUTUBE_API_URL}/channels?{channel_query}", access_token
        )
        channels = channel_value.get("items")
        channel = channels[0] if isinstance(channels, list) and channels else None
        content = channel.get("contentDetails") if isinstance(channel, dict) else None
        related = content.get("relatedPlaylists") if isinstance(content, dict) else None
        uploads = related.get("uploads") if isinstance(related, dict) else None
        if not isinstance(uploads, str) or not uploads:
            raise ValueError("The connected YouTube channel has no uploads playlist")
        videos_query = urllib.parse.urlencode(
            {
                "part": "id,snippet,contentDetails,status",
                "playlistId": uploads,
                "maxResults": str(count),
            }
        )
        value = _api_json(
            f"{YOUTUBE_API_URL}/playlistItems?{videos_query}", access_token
        )
        items = value.get("items")
        videos = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet")
            content_details = item.get("contentDetails")
            status = item.get("status")
            videos.append(
                {
                    "videoId": (
                        content_details.get("videoId")
                        if isinstance(content_details, dict)
                        else None
                    ),
                    "title": snippet.get("title")
                    if isinstance(snippet, dict)
                    else None,
                    "publishedAt": (
                        content_details.get("videoPublishedAt")
                        if isinstance(content_details, dict)
                        else None
                    ),
                    "privacyStatus": (
                        status.get("privacyStatus")
                        if isinstance(status, dict)
                        else None
                    ),
                }
            )
        return json.dumps({"videos": videos}, separators=(",", ":"))

    return [youtube_my_channel, youtube_my_videos]


def provider_connection_tools(binding: dict, usage: Any = None) -> list[Any]:
    if binding["provider"] == "youtube":
        return _youtube_tools(binding, usage)
    if binding["provider"] == "x":
        return _x_tools(binding, usage)
    if binding["provider"] == "slack":
        return _slack_tools(binding, usage)
    if binding["provider"] == "microsoft":
        return _microsoft_tools(binding, usage)
    if binding["provider"] == "notion":
        return _notion_tools(binding, usage)
    raise ValueError("OAuth provider connection is unsupported")


__all__ = ["provider_connection_tools", "validated_provider_binding"]
