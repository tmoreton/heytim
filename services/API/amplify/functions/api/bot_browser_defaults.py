"""One-time browser defaults for existing bots."""
from __future__ import annotations

from .support import _bot_sk, _user_pk, table


def _apply_browser_default(user_id: str, bot: dict) -> dict:
    """Apply the new default once; later bot edits may remove it deliberately."""
    if bot.get("browserDefaultApplied") is True:
        return bot
    old_tools = bot.get("toolIds", [])
    old_extra = bot.get("extraToolIds")
    if not isinstance(old_tools, list) or not all(isinstance(tool, str) for tool in old_tools):
        return bot
    if old_extra is not None and (
        not isinstance(old_extra, list)
        or not all(isinstance(tool, str) for tool in old_extra)
    ):
        return bot
    tools = list(dict.fromkeys([*old_tools, "browser"]))
    extra = list(dict.fromkeys([*(old_extra if old_extra is not None else old_tools), "browser"]))
    allowed = bot.get("alwaysAllowedToolIds", [])
    if not isinstance(allowed, list):
        allowed = []
    if bot.get("actionApprovalMode", "automatic") == "automatic":
        allowed = list(dict.fromkeys([*allowed, "browser"]))
    values = {
        ":tools": tools,
        ":extra": extra,
        ":allowed": allowed,
        ":applied": True,
        ":oldTools": old_tools,
    }
    condition = "attribute_not_exists(browserDefaultApplied) AND toolIds = :oldTools"
    if old_extra is not None:
        condition += " AND extraToolIds = :oldExtra"
        values[":oldExtra"] = old_extra
    else:
        condition += " AND attribute_not_exists(extraToolIds)"
    try:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot["id"])},
            UpdateExpression=(
                "SET toolIds = :tools, extraToolIds = :extra, "
                "alwaysAllowedToolIds = :allowed, browserDefaultApplied = :applied"
            ),
            ConditionExpression=condition,
            ExpressionAttributeValues=values,
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        # Another device changed the bot. A fresh bootstrap can retry safely.
        return bot
    return {
        **bot, "toolIds": tools, "extraToolIds": extra,
        "alwaysAllowedToolIds": allowed, "browserDefaultApplied": True,
    }
