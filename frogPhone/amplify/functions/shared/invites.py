from __future__ import annotations

import hashlib
from urllib.parse import urlencode

INVITE_KINDS = {"bot", "chat", "group", "skill"}


def invite_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def invite_url(base_url: str, kind: str, token: str) -> str:
    if kind not in INVITE_KINDS:
        raise ValueError("Unsupported invite kind")
    return f"{base_url.rstrip('/')}/invite?{urlencode({'kind': kind, 'token': token})}"
