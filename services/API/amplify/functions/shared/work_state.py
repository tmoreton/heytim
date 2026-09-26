from __future__ import annotations

IN_FLIGHT_STATUSES = frozenset(
    {
        "PENDING", "RUNNING", "WAITING", "NEEDS_INPUT",
        "AWAITING_APPROVAL", "AWAITING_DEVICE",
    }
)
CLAIMABLE_STATUSES = frozenset({"PENDING", "RUNNING"})


def is_in_flight(status: object) -> bool:
    return isinstance(status, str) and status in IN_FLIGHT_STATUSES


def is_claimable(status: object) -> bool:
    return isinstance(status, str) and status in CLAIMABLE_STATUSES


def processing_summary(items: list[dict]) -> dict:
    """Describe the newest visibly active response in a conversation."""
    current = next(
        (item for item in items if item.get("status") in CLAIMABLE_STATUSES),
        None,
    )
    if not current:
        return {"processing": False}
    name = current.get("authorName")
    return {
        "processing": True,
        **({"processingBotName": name} if isinstance(name, str) and name else {}),
    }
