"""Push delivery terminology: no provider result proves display on a device."""

from __future__ import annotations

import hashlib


def receipt_key(receipt_id: str) -> str:
    return hashlib.sha256(receipt_id.encode()).hexdigest()


def ticket_status(total: int, accepted: int, rejected: int) -> str:
    if total <= 0 or accepted + rejected != total:
        return "UNKNOWN"
    if accepted == total:
        return "ACCEPTED"
    if accepted:
        return "PARTIALLY_ACCEPTED"
    return "REJECTED"


def receipt_status(states: dict, rejected_tickets: int, unknown_tickets: int) -> str:
    values = [item.get("status") for item in states.values()]
    if "PENDING" in values:
        return "PENDING_RECEIPTS"
    if unknown_tickets or "UNKNOWN" in values:
        return "UNKNOWN"
    accepted = values.count("PROVIDER_ACCEPTED")
    failed = values.count("FAILED") + rejected_tickets
    if accepted and failed:
        return "PARTIAL"
    if accepted:
        return "PROVIDER_ACCEPTED"
    return "FAILED" if failed else "UNKNOWN"
