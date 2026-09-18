"""Version the effective owner grants across approval and execution."""
from __future__ import annotations

import hashlib
import json
import re


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
        "updatedAt": bot.get("updatedAt"),
        "githubRepositoryAccess": bot.get("githubRepositoryAccess"),
        "jiraProjectAccess": bot.get("jiraProjectAccess"),
        "teamsChannelAccess": bot.get("teamsChannelAccess"),
        "resourceAccess": bot.get("resourceAccess"),
        "connections": connections,
    }
    return hashlib.sha256(json.dumps(scope, sort_keys=True, default=str).encode()).hexdigest()
