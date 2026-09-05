from __future__ import annotations

IN_FLIGHT_STATUSES = frozenset(
    {"PENDING", "RUNNING", "WAITING", "NEEDS_INPUT", "AWAITING_APPROVAL"}
)
CLAIMABLE_STATUSES = frozenset({"PENDING", "RUNNING"})
TERMINAL_STATUSES = frozenset({"COMPLETE", "ERROR", "CANCELLED"})


def is_in_flight(status: object) -> bool:
    return isinstance(status, str) and status in IN_FLIGHT_STATUSES


def is_claimable(status: object) -> bool:
    return isinstance(status, str) and status in CLAIMABLE_STATUSES
