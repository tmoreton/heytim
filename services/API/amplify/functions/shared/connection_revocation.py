from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .github_app import (
    GITHUB_API_URL,
    GITHUB_API_VERSION,
    github_app_config,
    github_app_jwt,
)

GOOGLE_TOKEN_REVOKE_URL = "https://oauth2.googleapis.com/revoke"  # nosec B105
X_TOKEN_REVOKE_URL = "https://api.x.com/2/oauth2/revoke"  # nosec B105
SLACK_TOKEN_REVOKE_URL = "https://slack.com/api/auth.revoke"  # nosec B105
NOTION_TOKEN_REVOKE_URL = "https://api.notion.com/v1/oauth/revoke"  # nosec B105
NOTION_API_VERSION = "2026-03-11"
PROVIDER_REVOKE_TIMEOUT_SECONDS = 4


def revoke_google_token(
    refresh_token: str, *, urlopen: Callable, logger: Any
) -> None:
    request = urllib.request.Request(
        GOOGLE_TOKEN_REVOKE_URL,
        data=urllib.parse.urlencode({"token": refresh_token}).encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=PROVIDER_REVOKE_TIMEOUT_SECONDS):
            pass
    except urllib.error.HTTPError as error:
        if error.code != 400:
            logger.warning("Google token revocation failed; removing local access")
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.warning("Google token revocation was unavailable; removing local access")


def revoke_x_token(
    refresh_token: str,
    config_arn: str,
    *,
    valid_secret_arn: Callable[[Any], bool],
    secret_document: Callable[[str], dict],
    urlopen: Callable,
    logger: Any,
) -> None:
    if not valid_secret_arn(config_arn):
        return
    config = secret_document(config_arn)
    client_id = config.get("clientId")
    client_secret = config.get("clientSecret")
    if not all(
        isinstance(value, str) and value
        for value in (client_id, client_secret, refresh_token)
    ):
        return
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(
        X_TOKEN_REVOKE_URL,
        data=urllib.parse.urlencode(
            {  # nosec B105 - OAuth token type name, not a credential.
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            }
        ).encode(),
        headers={
            "authorization": f"Basic {basic}",
            "content-type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=PROVIDER_REVOKE_TIMEOUT_SECONDS):
            pass
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        logger.warning("X token revocation failed; removing local access")


def revoke_github_access(
    credential: dict,
    item: dict,
    *,
    valid_secret_arn: Callable[[Any], bool],
    secret_document: Callable[[str], dict],
    urlopen: Callable,
    logger: Any,
) -> None:
    config_arn = item.get("runtime", {}).get("appSecretArn")
    installation_id = credential.get("installationId")
    if not valid_secret_arn(config_arn) or not isinstance(installation_id, str):
        return
    config = github_app_config(secret_document(config_arn))
    token = github_app_jwt(config["appId"], config["privateKey"])
    request = urllib.request.Request(
        f"{GITHUB_API_URL}/app/installations/{installation_id}",
        headers={
            "accept": "application/vnd.github+json",
            "authorization": f"Bearer {token}",
            "user-agent": "FroggyBot/1.0",
            "x-github-api-version": GITHUB_API_VERSION,
        },
        method="DELETE",
    )
    try:
        with urlopen(request, timeout=PROVIDER_REVOKE_TIMEOUT_SECONDS):
            pass
    except urllib.error.HTTPError as error:
        if error.code != 404:
            logger.warning("GitHub App uninstall failed; removing local access")
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.warning("GitHub App uninstall was unavailable; removing local access")


def revoke_external_access(
    provider: str,
    credential: dict,
    config_arn: str,
    *,
    valid_secret_arn: Callable[[Any], bool],
    secret_document: Callable[[str], dict],
    urlopen: Callable,
    logger: Any,
) -> None:
    access_token = credential.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        return
    if provider == "slack":
        request = urllib.request.Request(
            SLACK_TOKEN_REVOKE_URL,
            data=b"",
            headers={
                "authorization": f"Bearer {access_token}",
                "content-type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
    elif provider == "notion":
        if not valid_secret_arn(config_arn):
            return
        config = secret_document(config_arn)
        client_id = config.get("clientId")
        client_secret = config.get("clientSecret")
        if not all(
            isinstance(value, str) and value
            for value in (client_id, client_secret)
        ):
            return
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        request = urllib.request.Request(
            NOTION_TOKEN_REVOKE_URL,
            data=json.dumps({"token": access_token}).encode(),
            headers={
                "authorization": f"Basic {basic}",
                "content-type": "application/json",
                "notion-version": NOTION_API_VERSION,
            },
            method="POST",
        )
    else:
        # Microsoft does not expose an app-specific refresh-token revocation
        # endpoint. Removing the local secret immediately ends FroggyBot access.
        return
    try:
        with urlopen(request, timeout=PROVIDER_REVOKE_TIMEOUT_SECONDS):
            pass
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        logger.warning("%s token revocation failed; removing local access", provider)
