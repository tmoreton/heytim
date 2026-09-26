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
GITHUB_API_VERSION = "2026-03-10"
GITHUB_MCP_ENDPOINT = "https://api.githubcopilot.com/mcp/"
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
    app_id = str(document.get("appId", ""))
    private_key = document.get("privateKey")
    if not re.fullmatch(r"[0-9]{1,20}", app_id) or not isinstance(private_key, str):
        raise ValueError("GitHub App configuration is invalid")
    _rsa_private_key(private_key)
    return {"appId": app_id, "privateKey": private_key}


def validate_installation_grant(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise TypeError("GitHub installation grant is invalid")
    installation_id = document.get("installationId")
    repository_ids = document.get("repositoryIds")
    permissions = document.get("permissions")
    if (
        not isinstance(installation_id, str)
        or not re.fullmatch(r"[0-9]{1,20}", installation_id)
        or not isinstance(repository_ids, list)
        or not 1 <= len(repository_ids) <= 500
        or len(repository_ids) != len(set(repository_ids))
        or any(not isinstance(value, int) or value <= 0 for value in repository_ids)
        or not isinstance(permissions, dict)
        or not permissions
        or any(
            name not in GITHUB_APP_PERMISSIONS or value not in {"read", "write"}
            for name, value in permissions.items()
        )
        or permissions.get("metadata") != "read"
        or permissions.get("contents") not in {"read", "write"}
    ):
        raise ValueError("GitHub installation grant is invalid")
    return {
        "installationId": installation_id,
        "repositoryIds": repository_ids,
        "permissions": permissions,
    }
