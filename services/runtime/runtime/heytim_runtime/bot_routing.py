"""Model-visible, one-target dispatch into a saved teammate's own chat."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from strands import tool

from .client_contract import MESSAGE_MAX_LENGTH


def routing_tool(context: dict, tracker: Any, text: Callable[..., str]) -> Any:
    @tool
    def route_to_bot(bot_id_or_name: str, task: str) -> str:
        """Hand one user-requested task to the best existing saved teammate.

        Use the exact saved bot ID or unique name from list_bot_options. Forward
        only the requested task and necessary user-supplied context; do not copy
        private conversation history, files, credentials, or tool grants. The
        teammate uses its own tools and approvals and replies in its own chat.
        This does not wait for its answer. After success, call no more tools and
        finish by saying the task will be queued, never that it is completed.
        """
        identifier = text(bot_id_or_name, "bot_id_or_name", 80).casefold()
        matches = [
            item for item in context["bots"]
            if str(item.get("id", "")).casefold() == identifier
            or str(item.get("name", "")).strip().casefold() == identifier
        ]
        if len(matches) != 1:
            raise ValueError("Bot not found or name is ambiguous; call list_bot_options first")
        target = matches[0]
        if target.get("systemRole") == "chief" or target.get("id") == context["currentBot"]["id"]:
            raise ValueError("Choose an existing teammate other than Chief")
        tracker.stage("route_bot", {
            "botId": str(target["id"]), "task": text(task, "task", MESSAGE_MAX_LENGTH),
        })
        return json.dumps({
            "status": "ready_to_queue", "botId": target["id"], "botName": target["name"],
            "delivery": "The teammate's reply will appear in its own chat.",
            "instruction": "Finish the response now without calling another tool so the platform can queue the task. Do not claim the task is complete.",
        }, ensure_ascii=False, separators=(",", ":"))

    return route_to_bot


__all__ = ["routing_tool"]
