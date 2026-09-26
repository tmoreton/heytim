from __future__ import annotations

import re
import time
from typing import Any

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import InvalidKeyError

GITHUB_API_URL = "https://api.github.com"
GITHUB_OAUTH_URL = "https://github.com/login/oauth/access_token"
GITHUB_MCP_ENDPOINT = "https://api.githubcopilot.com/mcp/"
GITHUB_API_VERSION = "2026-03-10"
GITHUB_APP_PERMISSIONS = {
    "contents": "write",
    "issues": "write",
    "metadata": "read",
    "pull_requests": "write",
}
def _rsa_private_key(private_key: str) -> rsa.RSAPrivateKey:
    if not isinstance(private_key, str) or len(private_key) > 32_000:
        raise ValueError("GitHub App private key is invalid")
    try:
        parsed = serialization.load_pem_private_key(
            private_key.encode("ascii"), password=None
        )
    except (TypeError, ValueError, UnsupportedAlgorithm, UnicodeEncodeError) as exc:
        raise ValueError("GitHub App private key is invalid") from exc
    if not isinstance(parsed, rsa.RSAPrivateKey):
        raise TypeError("GitHub App private key must be RSA")
    if parsed.key_size < 2_048:
        raise ValueError(
            "GitHub App private key must be a 2048-bit or stronger RSA key"
        )
    return parsed


def github_app_jwt(app_id: str, private_key: str, *, now: int | None = None) -> str:
    if not isinstance(app_id, str) or not re.fullmatch(r"[0-9]{1,20}", app_id):
        raise ValueError("GitHub App id is invalid")
    issued_at = int(time.time()) if now is None else int(now)
    try:
        return jwt.encode(
            {"iat": issued_at - 60, "exp": issued_at + 540, "iss": app_id},
            _rsa_private_key(private_key),
            algorithm="RS256",
            headers={"typ": "JWT"},
        )
    except (InvalidKeyError, TypeError) as exc:
        raise ValueError("GitHub App private key is invalid") from exc


def github_app_config(document: Any) -> dict[str, str]:
    if not isinstance(document, dict):
        raise TypeError("GitHub App configuration is invalid")
    values = {
        "appId": str(document.get("appId", "")),
        "clientId": document.get("clientId"),
        "clientSecret": document.get("clientSecret"),
        "privateKey": document.get("privateKey"),
        "slug": document.get("slug"),
    }
    if (
        not re.fullmatch(r"[0-9]{1,20}", values["appId"])
        or not isinstance(values["clientId"], str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{8,100}", values["clientId"])
        or not isinstance(values["clientSecret"], str)
        or not 20 <= len(values["clientSecret"]) <= 500
        or not isinstance(values["privateKey"], str)
        or not isinstance(values["slug"], str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,99}", values["slug"])
    ):
        raise ValueError("GitHub App configuration is invalid")
    _rsa_private_key(values["privateKey"])
    return values  # type: ignore[return-value]


def narrowed_permissions(granted: Any) -> dict[str, str]:
    if not isinstance(granted, dict):
        raise TypeError("GitHub App installation permissions are invalid")
    result = {}
    for name, requested in GITHUB_APP_PERMISSIONS.items():
        value = granted.get(name)
        if value == "read" or value == requested:
            result[name] = value
    if result.get("metadata") != "read" or result.get("contents") not in {
        "read",
        "write",
    }:
        raise ValueError("GitHub App needs metadata and repository contents access")
    return result
