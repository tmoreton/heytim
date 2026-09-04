from __future__ import annotations

from typing import Any

ALL_BOTS_REPLY_TARGET = "all"
MAX_GROUP_CONTEXT_PEOPLE = 50


def group_bots(items: list[dict]) -> list[dict]:
    """Return the group's bots in a stable, human-friendly turn order."""
    return sorted(
        (item for item in items if item.get("entity") == "GROUP_BOT"),
        key=lambda item: (
            str(item.get("name", "")).lower(),
            str(item.get("botId", "")),
        ),
    )


def select_group_reply_targets(items: list[dict], target: str | None) -> list[dict]:
    bots = group_bots(items)
    if target is None:
        return []
    if target == ALL_BOTS_REPLY_TARGET:
        return bots
    return [bot for bot in bots if bot.get("botId") == target]


def group_round_step(replies: Any, index: Any) -> tuple[dict, bool]:
    if not isinstance(replies, list) or not replies or len(replies) > 12:
        raise ValueError("Group agent round must contain between 1 and 12 replies")
    if (
        isinstance(index, bool)
        or not isinstance(index, int)
        or not 0 <= index < len(replies)
    ):
        raise ValueError("Group agent round position is invalid")
    reply = replies[index]
    if not isinstance(reply, dict):
        raise TypeError("Each group agent round reply must be an object")
    return reply, index == len(replies) - 1


def group_runtime_context(
    meta: dict,
    items: list[dict],
    current_bot_id: str,
    round_position: int,
    round_size: int,
) -> dict:
    people = sorted(
        (
            {
                "name": str(item.get("name", "FrogBot user"))[:40],
                "role": "owner" if item.get("role") == "owner" else "member",
            }
            for item in items
            if item.get("entity") == "GROUP_USER"
        ),
        key=lambda person: (person["role"] != "owner", person["name"].lower()),
    )[:MAX_GROUP_CONTEXT_PEOPLE]
    bots = [
        {
            "id": str(item.get("botId", ""))[:64],
            "name": str(item.get("name", "FrogBot"))[:60],
            "tagline": str(item.get("tagline", ""))[:120],
            "isCurrent": item.get("botId") == current_bot_id,
        }
        for item in group_bots(items)
    ]
    return {
        "name": str(meta.get("name", "Group"))[:64],
        "people": people,
        "bots": bots,
        "round": {"position": round_position, "size": round_size},
    }


def _append_history(messages: list[dict], role: str, text: str) -> None:
    if messages and messages[-1]["role"] == role:
        previous = messages[-1]["content"][0]["text"]
        messages[-1]["content"] = [{"text": f"{previous}\n{text}"}]
        return
    messages.append({"role": role, "content": [{"text": text}]})


def group_history_from_items(items: list[dict], current_bot_id: str) -> list[dict]:
    """Translate the shared transcript into one bot's model conversation."""
    messages: list[dict] = []
    for item in sorted(items, key=lambda value: str(value.get("sk", ""))):
        text = item.get("text")
        if (
            item.get("status") != "COMPLETE"
            or not isinstance(text, str)
            or not text.strip()
        ):
            continue
        clean_text = text.strip()[:12_000]
        author_name = str(item.get("authorName", "Participant"))[:60]
        if item.get("authorType") == "bot" and item.get("authorId") == current_bot_id:
            _append_history(messages, "assistant", clean_text)
        else:
            _append_history(messages, "user", f"[{author_name}]: {clean_text}")
    return messages
