from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

INVITE_KINDS = {"bot", "chat", "group", "skill"}


def invite_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invite_access_key(token: str) -> dict[str, str]:
    return {"tokenHash": invite_token_hash(token)}


def active_invite_access(
    table: Any,
    kind: str,
    token: str,
    *,
    now_epoch: int | None = None,
) -> dict | None:
    """Read the authoritative invite grant without retaining the bearer token."""
    if kind not in INVITE_KINDS or not isinstance(token, str) or not token:
        return None
    item = table.get_item(Key=invite_access_key(token), ConsistentRead=True).get("Item")
    current = (
        int(datetime.now(UTC).timestamp()) if now_epoch is None else int(now_epoch)
    )
    if (
        not item
        or item.get("kind") != kind
        or int(item.get("expiresAt", 0)) < current
    ):
        return None
    return item


def revoke_invite_access(table: Any, token: str) -> None:
    """Revoke the authoritative grant before best-effort cleanup of invite metadata."""
    table.delete_item(Key=invite_access_key(token))


def invite_url(base_url: str, kind: str, token: str) -> str:
    if kind not in INVITE_KINDS:
        raise ValueError("Unsupported invite kind")
    return f"{base_url.rstrip('/')}/invite?{urlencode({'kind': kind, 'token': token})}"
