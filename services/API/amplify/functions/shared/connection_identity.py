from __future__ import annotations

import hashlib
import uuid


def _secret_name(user_id: str, connection_id: str) -> str:
    owner = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
    revision = uuid.uuid4().hex[:12]
    return f"heytim/connections/{owner}/{connection_id}-{revision}"


def _connection_id(provider: str, user_id: str, account_id: str) -> str:
    digest = hashlib.sha256(
        f"{provider}:{user_id}:{account_id.casefold()}".encode()
    ).hexdigest()[:20]
    return f"connection_{digest}"


def _matching_connection(
    connections: list[dict], provider: str, account_id: str, account: str
) -> dict | None:
    for item in connections:
        if item.get("provider") != provider:
            continue
        stored_id = item.get("providerAccountId")
        if isinstance(stored_id, str):
            if stored_id.casefold() == account_id.casefold():
                return item
        elif str(item.get("connectedAccount", "")).casefold() == account.casefold():
            # Connections saved before account-specific IDs existed retain their
            # IDs so bots already using them keep the same grant.
            return item
    return None


