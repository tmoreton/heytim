from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
from typing import Any

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
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _read_tlv(document: bytes, offset: int = 0) -> tuple[int, bytes, int]:
    if offset >= len(document):
        raise ValueError("GitHub App private key is invalid")
    tag = document[offset]
    offset += 1
    if offset >= len(document):
        raise ValueError("GitHub App private key is invalid")
    length = document[offset]
    offset += 1
    if length & 0x80:
        width = length & 0x7F
        if width == 0 or width > 4 or offset + width > len(document):
            raise ValueError("GitHub App private key is invalid")
        length = int.from_bytes(document[offset : offset + width], "big")
        offset += width
    end = offset + length
    if end > len(document):
        raise ValueError("GitHub App private key is invalid")
    return tag, document[offset:end], end


def _sequence_children(document: bytes) -> list[tuple[int, bytes]]:
    tag, content, end = _read_tlv(document)
    if tag != 0x30 or end != len(document):
        raise ValueError("GitHub App private key is invalid")
    children = []
    offset = 0
    while offset < len(content):
        child_tag, child, offset = _read_tlv(content, offset)
        children.append((child_tag, child))
    return children


def _rsa_private_numbers(private_key: str) -> tuple[int, int]:
    if not isinstance(private_key, str) or len(private_key) > 32_000:
        raise ValueError("GitHub App private key is invalid")
    match = re.fullmatch(
        r"-----BEGIN (?P<label>RSA PRIVATE KEY|PRIVATE KEY)-----\s+"
        r"(?P<body>[A-Za-z0-9+/=\s]+)"
        r"-----END (?P=label)-----\s*",
        private_key.strip(),
    )
    if not match:
        raise ValueError("GitHub App private key is invalid")
    try:
        der = base64.b64decode("".join(match.group("body").split()), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("GitHub App private key is invalid") from exc
    children = _sequence_children(der)
    if match.group("label") == "PRIVATE KEY":
        octets = next((value for tag, value in children if tag == 0x04), None)
        if octets is None:
            raise ValueError("GitHub App private key is invalid")
        children = _sequence_children(octets)
    integers = [int.from_bytes(value, "big") for tag, value in children if tag == 0x02]
    if len(integers) < 4 or integers[0] not in {0, 1}:
        raise ValueError("GitHub App private key is invalid")
    modulus, private_exponent = integers[1], integers[3]
    if modulus.bit_length() < 2048 or private_exponent <= 1:
        raise ValueError(
            "GitHub App private key must be a 2048-bit or stronger RSA key"
        )
    return modulus, private_exponent


def _rsa_sign_sha256(message: bytes, private_key: str) -> bytes:
    modulus, private_exponent = _rsa_private_numbers(private_key)
    width = (modulus.bit_length() + 7) // 8
    digest_info = _SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(message).digest()
    padding_length = width - len(digest_info) - 3
    if padding_length < 8:
        raise ValueError("GitHub App private key is too short")
    encoded = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), private_exponent, modulus)
    return signature.to_bytes(width, "big")


def github_app_jwt(app_id: str, private_key: str, *, now: int | None = None) -> str:
    if not isinstance(app_id, str) or not re.fullmatch(r"[0-9]{1,20}", app_id):
        raise ValueError("GitHub App id is invalid")
    issued_at = int(time.time()) if now is None else int(now)
    header = _base64url(
        json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload = _base64url(
        json.dumps(
            {"iat": issued_at - 60, "exp": issued_at + 540, "iss": app_id},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    return (
        f"{header}.{payload}.{_base64url(_rsa_sign_sha256(signing_input, private_key))}"
    )


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
    _rsa_private_numbers(values["privateKey"])
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
