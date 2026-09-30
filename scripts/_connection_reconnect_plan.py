"""Remove source-only connection bindings from migrated bot records."""

from __future__ import annotations

from typing import Any


class ReconnectPlanError(ValueError):
    """A source connection reference cannot be safely carried forward."""


def excluded_connection_ids(items: list[dict]) -> set[str]:
    ids: set[str] = set()
    for item in items:
        key = item.get("sk")
        if isinstance(key, str) and key.startswith("CONNECTION#"):
            connection_id = key.removeprefix("CONNECTION#")
            if not connection_id or connection_id in ids:
                raise ReconnectPlanError("Source connection identity is ambiguous")
            ids.add(connection_id)
    return ids


def remove_excluded_connection_references(
    item: dict[str, Any], category: str, excluded: set[str]
) -> int:
    """Strip optional bot bindings; refuse required or unknown references."""
    if not excluded:
        return 0
    trigger = item.get("trigger")
    if isinstance(trigger, dict) and trigger.get("connectionId") in excluded:
        raise ReconnectPlanError("A routine still depends on an excluded connection")
    required = item.get("requiredToolIds")
    if isinstance(required, list) and excluded.intersection(required):
        raise ReconnectPlanError("A required tool depends on an excluded connection")
    fields = ("toolIds", "extraToolIds")
    maps = (
        "githubRepositoryAccess", "jiraProjectAccess",
        "teamsChannelAccess", "resourceAccess",
    )
    if category != "USER/BOT":
        if any(
            isinstance(item.get(field), list) and excluded.intersection(item[field])
            for field in fields
        ) or any(
            isinstance(item.get(field), dict) and excluded.intersection(item[field])
            for field in maps
        ):
            raise ReconnectPlanError("A non-bot record references an excluded connection")
        return 0
    removed = 0
    for field in fields:
        values = item.get(field)
        if values is None:
            continue
        if not isinstance(values, list):
            raise ReconnectPlanError("Bot tool bindings are malformed")
        filtered = [value for value in values if value not in excluded]
        removed += len(values) - len(filtered)
        item[field] = filtered
    for field in maps:
        values = item.get(field)
        if values is None:
            continue
        if not isinstance(values, dict):
            raise ReconnectPlanError("Bot resource bindings are malformed")
        filtered = {key: value for key, value in values.items() if key not in excluded}
        removed += len(values) - len(filtered)
        item[field] = filtered
    return removed
