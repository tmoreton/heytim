"""Bounded bot roster and management context for runtime calls."""
from __future__ import annotations

from shared.client_contract import MEMORY_MAX_LENGTH

from .support import _bot_key, catalog, table

MAX_TEAM_BOTS = 24


def _team_roster(user_id: str, current_bot_id: str) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": _bot_key(user_id, current_bot_id)["pk"],
            ":prefix": "BOT#",
        },
        ConsistentRead=True,
    ).get("Items", [])
    roster = []
    for item in items:
        name = item.get("name")
        tagline = item.get("tagline", "")
        roster_bot_id = item.get("id")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(tagline, str)
            or not isinstance(roster_bot_id, str)
        ):
            continue
        roster.append(
            {
                "name": name.strip()[:60],
                "tagline": tagline.strip()[:120],
                "isCurrent": roster_bot_id == current_bot_id,
            }
        )
    return sorted(
        roster,
        key=lambda item: (not item["isCurrent"], item["name"].casefold()),
    )[:MAX_TEAM_BOTS]


def _bot_management_context(user_id: str, current_bot: dict) -> dict:
    can_manage_bots = current_bot.get("systemRole") == "chief"
    bot_items = (
        table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#{user_id}",
                ":prefix": "BOT#",
            },
            ConsistentRead=True,
        ).get("Items", [])
        if can_manage_bots
        else []
    )
    bots = []
    for item in bot_items[:MAX_TEAM_BOTS]:
        if not isinstance(item.get("id"), str) or not isinstance(
            item.get("name"), str
        ):
            continue
        bots.append(
            {
                key: item[key]
                for key in (
                    "id",
                    "name",
                    "tagline",
                    "prompt",
                    "color",
                    "toolIds",
                    "skillIds",
                    "systemRole",
                )
                if key in item
            }
        )

    def concise(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
        return [
            {key: item[key] for key in keys if key in item}
            for item in items
            if isinstance(item, dict)
        ]

    tools = concise(
        catalog.list_tools(user_id),
        ("id", "name", "description", "category"),
    )
    self_tools = [
        item
        for item in catalog.available_tools(user_id, current_bot.get("toolIds", []))
        if item.get("id") != "bot_manager"
    ]
    self_tool_ids = [item["id"] for item in self_tools]
    if not can_manage_bots:
        tools = [item for item in tools if item.get("id") in self_tool_ids]

    return {
        "currentBot": {
            key: current_bot[key]
            for key in (
                "id",
                "name",
                "tagline",
                "prompt",
                "color",
                "toolIds",
                "skillIds",
                "systemRole",
            )
            if key in current_bot
        },
        "canManageBots": can_manage_bots,
        "bots": bots,
        "templates": (
            concise(
                catalog.list_bot_templates(user_id),
                (
                    "id",
                    "name",
                    "tagline",
                    "category",
                    "color",
                    "toolIds",
                    "skillIds",
                ),
            )
            if can_manage_bots
            else []
        ),
        "tools": tools,
        "skills": concise(
            catalog.list_skills(user_id),
            ("id", "name", "description", "category", "requiredToolIds"),
        ),
        "selfTools": concise(
            self_tools,
            ("id", "name", "description", "category"),
        ),
        "selfToolIds": self_tool_ids,
        "memoryMaxLength": MEMORY_MAX_LENGTH,
    }
