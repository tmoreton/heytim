from __future__ import annotations

from shared.work_state import is_in_flight


def has_pending_work(items: list[dict], *, bot_id: str | None = None) -> bool:
    return any(
        is_in_flight(item.get("status"))
        and (bot_id is None or item.get("authorId") == bot_id)
        for item in items
    )


def group_member_ids(items: list[dict]) -> list[str]:
    return [
        user_id
        for item in items
        if item.get("entity") == "GROUP_USER"
        and isinstance((user_id := item.get("userId")), str)
    ]


def group_invite_records(items: list[dict]) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for item in items:
        if item.get("entity") != "GROUP_INVITE_POINTER":
            continue
        token = item.get("token")
        token_hash = item.get("tokenHash")
        if isinstance(token, str) and isinstance(token_hash, str):
            records.append((token, token_hash))
    return records
