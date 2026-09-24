"""Version the effective owner grants across approval and execution."""
from __future__ import annotations

import hashlib
import json
import re

AUTOMATIC_APPROVAL_MODE = "automatic"
ASK_APPROVAL_MODE = "ask"


def action_approval_mode(bot: dict) -> str:
    """Return the stored policy, treating legacy bots as automatic."""
    return (
        ASK_APPROVAL_MODE
        if bot.get("actionApprovalMode") == ASK_APPROVAL_MODE
        else AUTOMATIC_APPROVAL_MODE
    )


def effective_allowed_interactive_tool_ids(bot: dict) -> list[str]:
    """Resolve the tool grants sent to runtimes and unattended jobs."""
    tool_ids = bot.get("toolIds", [])
    if action_approval_mode(bot) == AUTOMATIC_APPROVAL_MODE:
        return (
            tool_ids
            if isinstance(tool_ids, list)
            and all(isinstance(tool_id, str) for tool_id in tool_ids)
            else []
        )
    allowed = bot.get("alwaysAllowedToolIds", [])
    return (
        allowed
        if isinstance(allowed, list)
        and all(isinstance(tool_id, str) for tool_id in allowed)
        else []
    )


def approval_grant_digest(catalog, owner_id: str, bot: dict) -> str:
    tool_ids = bot.get("toolIds", [])
    if not isinstance(tool_ids, list) or not all(isinstance(value, str) for value in tool_ids):
        raise ValueError("Bot tool grants are invalid")
    connections = []
    for tool_id in tool_ids:
        if not re.fullmatch(r"connection_[a-f0-9]{20}", tool_id):
            continue
        connection = catalog._get_connection(owner_id, tool_id)
        if connection:
            connections.append({
                "id": tool_id,
                "status": connection.get("connectionStatus"),
                "updatedAt": connection.get("updatedAt"),
                "providerAccountId": connection.get("providerAccountId"),
            })
    scope = {
        "toolIds": tool_ids,
        "actionApprovalMode": action_approval_mode(bot),
        "updatedAt": bot.get("updatedAt"),
        "githubRepositoryAccess": bot.get("githubRepositoryAccess"),
        "jiraProjectAccess": bot.get("jiraProjectAccess"),
        "teamsChannelAccess": bot.get("teamsChannelAccess"),
        "resourceAccess": bot.get("resourceAccess"),
        "connections": connections,
    }
    return hashlib.sha256(json.dumps(scope, sort_keys=True, default=str).encode()).hexdigest()


def grant_enabled_interactive_tools(table, catalog, owner_id: str, bot: dict) -> list[str]:
    """Persist one owner decision for the bot's currently enabled interactive tools.

    Keep updatedAt unchanged so an already validated exact-action proposal can
    resume against the same grant digest. A later bot edit still invalidates it.
    """
    tool_ids = bot.get("toolIds", [])
    interactive = set(catalog.approval_tool_ids(owner_id, tool_ids))
    if not interactive:
        raise ValueError("The bot has no interactive tools to allow")
    previous = bot.get("alwaysAllowedToolIds", [])
    if not isinstance(previous, list) or any(not isinstance(item, str) for item in previous):
        raise ValueError("The bot's allowed tools are invalid")
    allowed = [item for item in tool_ids if item in interactive]
    if allowed == previous:
        return allowed
    condition = "updatedAt = :updated AND " + (
        "alwaysAllowedToolIds = :previous"
        if "alwaysAllowedToolIds" in bot else "attribute_not_exists(alwaysAllowedToolIds)"
    )
    table.update_item(
        Key={"pk": bot["pk"], "sk": bot["sk"]},
        UpdateExpression="SET alwaysAllowedToolIds = :allowed",
        ConditionExpression=condition,
        ExpressionAttributeValues={
            ":updated": bot["updatedAt"], ":allowed": allowed,
            **({":previous": previous} if "alwaysAllowedToolIds" in bot else {}),
        },
    )
    return allowed
