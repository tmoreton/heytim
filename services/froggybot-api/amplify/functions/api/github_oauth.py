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
from shared.catalog import CatalogError
from shared.github_app import (
    GITHUB_API_URL,
    GITHUB_API_VERSION,
    GITHUB_MCP_ENDPOINT,
    GITHUB_OAUTH_URL,
    github_app_config,
    github_app_jwt,
    narrowed_permissions,
)

from .google_oauth import _redirect, _return_url, _state_key
from .support import ApiError, _ensure_account_active, catalog, table

OAUTH_STATE_SECONDS = 10 * 60
CALLBACK_BUDGET_SECONDS = 24.0
REQUEST_MAX_SECONDS = 5.0
DEFAULT_RETURN_URL = "https://app.froggybot.com/app?oauth=github"
REDIRECT_ENV = "GITHUB_OAUTH_REDIRECT_URI"

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


def _app_config() -> tuple[dict[str, str], str]:
    secret_arn = os.environ.get("GITHUB_APP_SECRET_ARN")
    if not secret_arn:
        raise ApiError(503, "GitHub connections are not configured")
    response = _secret_client().get_secret_value(SecretId=secret_arn)
    raw = response.get("SecretString")
    try:
        document = json.loads(raw) if isinstance(raw, str) else None
        return github_app_config(document), secret_arn
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ApiError(503, "GitHub connections are not configured") from exc


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining < 0.5:
        raise ApiError(400, "The GitHub connection took too long. Please try again.")
    return min(REQUEST_MAX_SECONDS, remaining)


def _oauth_redirect_uri() -> str:
    redirect_uri = os.environ.get(REDIRECT_ENV)
    if not isinstance(redirect_uri, str) or not redirect_uri:
        raise ApiError(503, "GitHub connections are not configured")
    parsed = urllib.parse.urlsplit(redirect_uri)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ApiError(503, "GitHub connections are not configured")
    return redirect_uri


def _github_json(
    url: str,
    deadline: float,
    *,
    token: str | None = None,
    method: str = "GET",
    body: dict | None = None,
    basic: tuple[str, str] | None = None,
) -> dict:
    headers = {
        "accept": "application/vnd.github+json",
        "user-agent": "FroggyBot/1.0",
        "x-github-api-version": GITHUB_API_VERSION,
    }
    if token:
        headers["authorization"] = f"Bearer {token}"
    if basic:
        encoded = base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
        headers["authorization"] = f"Basic {encoded}"
    data = None
    if body is not None:
        headers["content-type"] = "application/json"
        data = json.dumps(body, separators=(",", ":")).encode()
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(  # nosec B310 - URL is assembled from fixed hosts and numeric ids.
            request, timeout=_remaining_timeout(deadline)
        ) as response:
            raw = response.read(1_000_001)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(400, "GitHub could not complete the connection") from exc
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ApiError(400, "GitHub returned an invalid response") from exc
    if not isinstance(value, dict):
        raise ApiError(400, "GitHub returned an invalid response")
    return value


def _exchange_user_code(
    code: str,
    verifier: str,
    config: dict[str, str],
    redirect_uri: str,
    deadline: float,
) -> dict:
    request = urllib.request.Request(
        GITHUB_OAUTH_URL,
        data=urllib.parse.urlencode(
            {
                "client_id": config["clientId"],
                "client_secret": config["clientSecret"],
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            }
        ).encode(),
        headers={
            "accept": "application/json",
            "content-type": "application/x-www-form-urlencoded",
            "user-agent": "FroggyBot/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # nosec B310 - fixed GitHub OAuth endpoint.
            request, timeout=_remaining_timeout(deadline)
        ) as response:
            value = json.loads(response.read(100_001).decode())
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ApiError(400, "GitHub could not complete the connection") from exc
    if not isinstance(value, dict) or not isinstance(value.get("access_token"), str):
        raise ApiError(400, "GitHub did not return user authorization")
    return value


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _installation_token(
    config: dict[str, str],
    installation_id: str,
    permissions: dict[str, str],
    deadline: float,
    repository_ids: list[int] | None = None,
) -> str:
    body: dict[str, Any] = {"permissions": permissions}
    if repository_ids is not None:
        body["repository_ids"] = repository_ids
    response = _github_json(
        f"{GITHUB_API_URL}/app/installations/{installation_id}/access_tokens",
        deadline,
        token=github_app_jwt(config["appId"], config["privateKey"]),
        method="POST",
        body=body,
    )
    token = response.get("token")
    if not isinstance(token, str) or not token:
        raise ApiError(400, "GitHub did not grant repository access")
    return token


def _installation_repositories(token: str, deadline: float) -> list[dict]:
    repositories = []
    for page in range(1, 6):
        result = _github_json(
            f"{GITHUB_API_URL}/installation/repositories?per_page=100&page={page}",
            deadline,
            token=token,
        )
        total_count = result.get("total_count")
        if isinstance(total_count, int) and total_count > 500:
            raise ApiError(400, "Select 500 or fewer repositories for FroggyBot")
        values = result.get("repositories")
        if not isinstance(values, list):
            raise ApiError(400, "GitHub did not return repository access")
        for value in values:
            if (
                isinstance(value, dict)
                and isinstance(value.get("id"), int)
                and isinstance(value.get("full_name"), str)
            ):
                repositories.append({"id": value["id"], "name": value["full_name"]})
        if len(values) < 100:
            break
    if not repositories:
        raise ApiError(400, "Select at least one repository for FroggyBot")
    return repositories


def _revoke_user_token(token: str, config: dict[str, str], deadline: float) -> None:
    try:
        _github_json(
            f"{GITHUB_API_URL}/applications/{config['clientId']}/token",
            deadline,
            method="DELETE",
            body={"access_token": token},
            basic=(config["clientId"], config["clientSecret"]),
        )
    except ApiError:
        logger.warning(
            "GitHub user token revocation failed after installation validation"
        )


def _begin_github_authorization(user_id: str, value: dict) -> dict:
    return_url = _return_url(value.get("returnUrl"))
    config, app_secret_arn = _app_config()
    redirect_uri = _oauth_redirect_uri()
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    table.put_item(
        Item={
            **_state_key(state),
            "entity": "OAUTH_STATE",
            "userId": user_id,
            "provider": "github",
            "returnUrl": return_url,
            "appSecretArn": app_secret_arn,
            "redirectUri": redirect_uri,
            "verifier": verifier,
            "expiresAt": int(time.time()) + OAUTH_STATE_SECONDS,
        }
    )
    return {
        "authorizationUrl": "https://github.com/login/oauth/authorize?"
        + urllib.parse.urlencode(
            {
                "client_id": config["clientId"],
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    }


def _consume_state(state: Any) -> dict:
    if not isinstance(state, str) or not 20 <= len(state) <= 200:
        raise ApiError(400, "The GitHub connection expired. Please try again.")
    result = table.delete_item(Key=_state_key(state), ReturnValues="ALL_OLD")
    item = result.get("Attributes")
    if (
        not item
        or item.get("provider") != "github"
        or int(item.get("expiresAt", 0)) < int(time.time())
    ):
        raise ApiError(400, "The GitHub connection expired. Please try again.")
    return item


def _result_url(return_url: str, status: str) -> str:
    parsed = urllib.parse.urlsplit(return_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"connection": "github", "status": status})
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )


def _begin_github_user_authorization(query: dict) -> dict:
    return_url = DEFAULT_RETURN_URL
    try:
        installation_id = query.get("installation_id")
        if not isinstance(installation_id, str) or not re.fullmatch(
            r"[0-9]{1,20}", installation_id
        ):
            raise ApiError(400, "GitHub did not return an installation")
        state = _consume_state(query.get("state"))
        return_url = _return_url(state.get("returnUrl"))
        _ensure_account_active(state["userId"])
        config, app_secret_arn = _app_config()
        if app_secret_arn != state.get("appSecretArn"):
            raise ApiError(
                400, "The GitHub App configuration changed. Please try again."
            )
        redirect_uri = _oauth_redirect_uri()

        oauth_state = secrets.token_urlsafe(32)
        verifier, challenge = _pkce_pair()
        table.put_item(
            Item={
                **_state_key(oauth_state),
                "entity": "OAUTH_STATE",
                "userId": state["userId"],
                "provider": "github",
                "returnUrl": return_url,
                "appSecretArn": app_secret_arn,
                "installationId": installation_id,
                "redirectUri": redirect_uri,
                "verifier": verifier,
                "expiresAt": int(time.time()) + OAUTH_STATE_SECONDS,
            }
        )
        authorization_url = "https://github.com/login/oauth/authorize?" + (
            urllib.parse.urlencode(
                {
                    "client_id": config["clientId"],
                    "redirect_uri": redirect_uri,
                    "state": oauth_state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        return _redirect(authorization_url)
    except (ApiError, KeyError, TypeError, ValueError):
        logger.exception("GitHub App setup callback failed")
        return _redirect(_result_url(return_url, "error"))


def _github_callback(query: dict) -> dict:
    if query.get("installation_id") is not None and query.get("code") is None:
        return _begin_github_user_authorization(query)

    return_url = DEFAULT_RETURN_URL
    deadline = time.monotonic() + CALLBACK_BUDGET_SECONDS
    user_token = None
    try:
        state = _consume_state(query.get("state"))
        return_url = _return_url(state.get("returnUrl"))
        _ensure_account_active(state["userId"])
        if query.get("error"):
            raise ApiError(400, "GitHub access was not approved")
        code = query.get("code")
        installation_id = state.get("installationId")
        verifier = state.get("verifier")
        if not isinstance(code, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{10,500}", code
        ):
            raise ApiError(400, "GitHub did not return an authorization code")
        if installation_id is not None and (
            not isinstance(installation_id, str)
            or not re.fullmatch(r"[0-9]{1,20}", installation_id)
        ):
            raise ApiError(400, "GitHub did not return an installation")
        if not isinstance(verifier, str) or not 43 <= len(verifier) <= 200:
            raise ApiError(400, "The GitHub connection expired. Please try again.")
        redirect_uri = state.get("redirectUri")
        if not isinstance(redirect_uri, str) or not redirect_uri:
            redirect_uri = _oauth_redirect_uri()

        config, app_secret_arn = _app_config()
        if app_secret_arn != state.get("appSecretArn"):
            raise ApiError(
                400, "The GitHub App configuration changed. Please try again."
            )
        exchanged = _exchange_user_code(
            code, verifier, config, redirect_uri, deadline
        )
        user_token = exchanged["access_token"]
        user_installations = _github_json(
            f"{GITHUB_API_URL}/user/installations?per_page=100",
            deadline,
            token=user_token,
        )
        installations = user_installations.get("installations")
        if not isinstance(installations, list):
            raise ApiError(400, "GitHub installation ownership could not be verified")
        matching_installations = [
            candidate
            for candidate in installations
            if isinstance(candidate, dict)
            and str(candidate.get("app_id", "")) == config["appId"]
            and not candidate.get("suspended_at")
        ]
        if installation_id is None:
            if len(matching_installations) != 1:
                install_state = secrets.token_urlsafe(32)
                table.put_item(
                    Item={
                        **_state_key(install_state),
                        "entity": "OAUTH_STATE",
                        "userId": state["userId"],
                        "provider": "github",
                        "returnUrl": return_url,
                        "appSecretArn": app_secret_arn,
                        "expiresAt": int(time.time()) + OAUTH_STATE_SECONDS,
                    }
                )
                return _redirect(
                    f"https://github.com/apps/{config['slug']}/installations/new?"
                    f"{urllib.parse.urlencode({'state': install_state})}"
                )
            installation_id = str(matching_installations[0]["id"])
        elif not any(
            str(candidate.get("id", "")) == installation_id
            for candidate in matching_installations
        ):
            raise ApiError(400, "GitHub installation ownership could not be verified")

        app_jwt = github_app_jwt(config["appId"], config["privateKey"])
        installation = _github_json(
            f"{GITHUB_API_URL}/app/installations/{installation_id}",
            deadline,
            token=app_jwt,
        )
        if str(installation.get("app_id", "")) != config["appId"] or installation.get(
            "suspended_at"
        ):
            raise ApiError(400, "GitHub installation is not available")
        account = installation.get("account")
        account_name = account.get("login") if isinstance(account, dict) else None
        if not isinstance(account_name, str) or not account_name:
            raise ApiError(400, "GitHub installation account is invalid")
        permissions = narrowed_permissions(installation.get("permissions"))
        installation_token = _installation_token(
            config, installation_id, permissions, deadline
        )
        repositories = _installation_repositories(installation_token, deadline)
        catalog.save_github_connection(
            state["userId"],
            account_name,
            installation_id,
            repositories,
            permissions,
            app_secret_arn,
        )
        return _redirect(_result_url(return_url, "connected"))
    except (ApiError, CatalogError, KeyError, TypeError, ValueError):
        logger.exception("GitHub App callback failed")
        return _redirect(_result_url(return_url, "error"))
    finally:
        if isinstance(user_token, str):
            try:
                config, _ = _app_config()
                _revoke_user_token(user_token, config, deadline)
            except (ApiError, ValueError):
                logger.warning("GitHub user token could not be revoked")


__all__ = [
    "GITHUB_MCP_ENDPOINT",
    "_begin_github_authorization",
    "_begin_github_user_authorization",
    "_github_callback",
]
