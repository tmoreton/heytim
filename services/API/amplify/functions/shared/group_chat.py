from __future__ import annotations

from typing import Any

from shared.client_contract import GROUP_MEMORY_MAX_LENGTH

ALL_BOTS_REPLY_TARGET = "all"
MAX_GROUP_CONTEXT_PEOPLE = 50
MAX_GROUP_BOTS = 12
MAX_GROUP_ROUND_REPLIES = MAX_GROUP_BOTS + 1
MAX_GROUP_MEMORY_CHARS = GROUP_MEMORY_MAX_LENGTH
MAX_GROUP_DECISIONS = 10
MAX_GROUP_DECISION_CHARS = 1_000
ROUND_ROLES = {"solo", "lead", "contributor", "synthesizer"}
CHIEF_SYSTEM_ROLE = "chief"
MAX_HISTORY_BLOCK_CHARS = 12_000


def is_chief_bot(bot: dict) -> bool:
    role = bot.get("systemRole")
    return role == CHIEF_SYSTEM_ROLE or (
        role is None and str(bot.get("name", "")).strip().casefold() == "chief"
    )


def group_bots(items: list[dict]) -> list[dict]:
    """Return the group's bots in a stable, human-friendly turn order."""
    return sorted(
        (item for item in items if item.get("entity") == "GROUP_BOT"),
        key=lambda item: (
            not is_chief_bot(item),
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


def plan_group_reply_round(bots: list[dict], coordinated: bool) -> list[dict]:
    """Create a bounded team round with one final coordinator synthesis."""
    if not bots:
        return []
    if not coordinated or len(bots) == 1:
        return [{**bots[0], "roundRole": "solo"}]

    coordinator = next((bot for bot in bots if is_chief_bot(bot)), None)
    if not coordinator:
        raise ValueError("A coordinated bot round requires Chief")
    contributors = [
        bot for bot in bots if bot.get("botId") != coordinator.get("botId")
    ]
    return [
        {**coordinator, "roundRole": "lead"},
        *({**bot, "roundRole": "contributor"} for bot in contributors),
        {**coordinator, "roundRole": "synthesizer"},
    ]


def group_round_step(replies: Any, index: Any) -> tuple[dict, bool]:
    if (
        not isinstance(replies, list)
        or not replies
        or len(replies) > MAX_GROUP_ROUND_REPLIES
    ):
        raise ValueError(
            f"Group agent round must contain between 1 and {MAX_GROUP_ROUND_REPLIES} replies"
        )
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
    round_role: str = "solo",
    coordinator_bot_id: str | None = None,
) -> dict:
    if round_role not in ROUND_ROLES:
        raise ValueError("Group round role is invalid")
    people = sorted(
        (
            {
                "name": str(item.get("name", "HeyTim user"))[:40],
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
            "name": str(item.get("name", "HeyTim"))[:60],
            "tagline": str(item.get("tagline", ""))[:120],
            "isCurrent": item.get("botId") == current_bot_id,
        }
        for item in group_bots(items)
    ]
    decisions = [
        {
            "text": str(item.get("text", ""))[:MAX_GROUP_DECISION_CHARS],
            "sourceAuthorName": str(item.get("sourceAuthorName", "HeyTim"))[:60],
            "createdByName": str(item.get("createdByName", "Room member"))[:40],
            "createdAt": str(item.get("createdAt", ""))[:32],
        }
        for item in sorted(
            (item for item in items if item.get("entity") == "GROUP_DECISION"),
            key=lambda item: str(item.get("createdAt", "")),
            reverse=True,
        )[:MAX_GROUP_DECISIONS]
        if str(item.get("text", "")).strip()
    ]
    coordinator = next(
        (bot for bot in bots if bot["id"] == coordinator_bot_id),
        next((bot for bot in bots if bot["isCurrent"]), bots[0]),
    )
    return {
        "name": str(meta.get("name", "Group"))[:64],
        "memory": str(meta.get("memory", ""))[:MAX_GROUP_MEMORY_CHARS],
        "people": people,
        "bots": bots,
        "decisions": decisions,
        "round": {
            "position": round_position,
            "size": round_size,
            "role": round_role,
            "coordinatorName": coordinator["name"],
        },
    }


def _append_history(messages: list[dict], role: str, text: str) -> None:
    if messages and messages[-1]["role"] == role:
        previous = messages[-1]["content"].pop()["text"]
        text = f"{previous}\n{text}"
    else:
        messages.append({"role": role, "content": []})
    messages[-1]["content"].extend(
        {"text": text[index:index + MAX_HISTORY_BLOCK_CHARS]}
        for index in range(0, len(text), MAX_HISTORY_BLOCK_CHARS)
        if text[index:index + MAX_HISTORY_BLOCK_CHARS].strip()
    )


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
        clean_text = text.strip()[:60_000]
        author_name = str(item.get("authorName", "Participant"))[:60]
        if item.get("authorType") == "bot" and item.get("authorId") == current_bot_id:
            _append_history(messages, "assistant", clean_text)
        else:
            _append_history(messages, "user", f"[{author_name}]: {clean_text}")
    return messages
