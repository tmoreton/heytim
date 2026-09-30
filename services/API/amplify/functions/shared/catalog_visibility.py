from __future__ import annotations

from typing import Any

from shared.connection_providers import connection_provider


def available_catalog_tool_items(
    items: list[dict[str, Any]], retired_tool_ids: frozenset[str]
) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if item.get("enabled", True) is True
        and item.get("id") not in retired_tool_ids
        and not (
            item.get("entity") == "CONNECTION"
            and connection_provider(item.get("provider")) is None
        )
        and not (
            item.get("entity") == "CONNECTION"
            and item.get("authType") in {"oauth", "github_app"}
            and item.get("connectionStatus") != "connected"
        )
    ]
