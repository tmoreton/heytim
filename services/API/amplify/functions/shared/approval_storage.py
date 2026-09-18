"""Address the per-turn snapshot without listing user content."""
from __future__ import annotations

from .memory_identity import memory_actor_id


def approval_snapshot_key(scope: str, scope_id: str, turn_id: str,
                          bot_id: str | None = None) -> str:
    if scope == "direct" and bot_id:
        prefix = f"users/{memory_actor_id(scope_id)}/bots/{bot_id}"
    elif scope == "group":
        prefix = f"groups/{scope_id}"
    else:
        raise ValueError("Approval snapshot scope is invalid")
    return (f"{prefix}/approval-state/{turn_id}/session/{turn_id}/scopes/agent/"
            f"turn-{turn_id}/snapshots/snapshot_latest.json")
