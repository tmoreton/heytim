"""Stable identities and deterministic transaction merges for Plaid Items."""
from __future__ import annotations

import re
from typing import Any

from .memory_identity import memory_actor_id

CONNECTION_ID = re.compile(r"connection_[a-f0-9]{20}\Z")
ITEM_ID = re.compile(r"[A-Za-z0-9_-]{8,200}\Z")
TRANSACTION_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
MAX_TRANSACTIONS = 100_000


def sync_key(user_id: str, connection_id: str) -> dict[str, str]:
    if not CONNECTION_ID.fullmatch(connection_id):
        raise ValueError("Plaid connection identity is invalid")
    return {"pk": f"USER#{user_id}", "sk": f"PLAID_SYNC#{connection_id}"}


def item_mapping_key(environment: str, item_id: str) -> dict[str, str]:
    if environment not in {"sandbox", "production"} or not ITEM_ID.fullmatch(item_id):
        raise ValueError("Plaid Item identity is invalid")
    return {"pk": f"PLAID_ITEM#{environment}#{item_id}", "sk": "CONNECTION"}


def ledger_prefix(user_id: str, connection_id: str) -> str:
    if not CONNECTION_ID.fullmatch(connection_id):
        raise ValueError("Plaid connection identity is invalid")
    return f"users/{memory_actor_id(user_id)}/finance/plaid/{connection_id}/"


def merge_transactions(
    previous: list[dict[str, Any]],
    added: list[dict[str, Any]],
    modified: list[dict[str, Any]],
    removed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply a complete sync window by transaction ID, including removals."""
    result: dict[str, dict[str, Any]] = {}
    for transaction in previous:
        transaction_id = transaction.get("transaction_id") if isinstance(transaction, dict) else None
        if not isinstance(transaction_id, str) or not TRANSACTION_ID.fullmatch(transaction_id):
            raise ValueError("Saved Plaid ledger is invalid")
        result[transaction_id] = transaction
    for removed_transaction in removed:
        transaction_id = (
            removed_transaction.get("transaction_id")
            if isinstance(removed_transaction, dict) else None
        )
        if not isinstance(transaction_id, str) or not TRANSACTION_ID.fullmatch(transaction_id):
            raise ValueError("Plaid removed transaction is invalid")
        result.pop(transaction_id, None)
    for transaction in [*added, *modified]:
        transaction_id = transaction.get("transaction_id") if isinstance(transaction, dict) else None
        account_id = transaction.get("account_id") if isinstance(transaction, dict) else None
        if (
            not isinstance(transaction_id, str)
            or not TRANSACTION_ID.fullmatch(transaction_id)
            or not isinstance(account_id, str)
            or not ITEM_ID.fullmatch(account_id)
        ):
            raise ValueError("Plaid transaction is invalid")
        result[transaction_id] = transaction
    if len(result) > MAX_TRANSACTIONS:
        raise ValueError("Plaid ledger exceeds the supported transaction limit")
    return [result[key] for key in sorted(result)]


def public_sync_status(item: dict | None) -> dict[str, Any]:
    if not item:
        return {"status": "not_started", "transactionCount": 0}
    allowed = {
        "status", "transactionCount", "lastSyncedAt", "lastCheckedAt",
        "requestedAt", "errorCode", "historicalComplete",
    }
    return {key: value for key, value in item.items() if key in allowed}
