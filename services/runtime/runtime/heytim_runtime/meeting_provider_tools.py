from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from strands import tool


def _runtime():
    from . import provider_connections

    return provider_connections


def zoom_tools(binding: dict, usage: Any) -> list[Any]:
    runtime = _runtime()

    def public_meeting(value: dict) -> dict:
        return {
            key: value.get(key) for key in (
                "id", "topic", "agenda", "start_time", "duration", "timezone", "join_url"
            )
        }

    @tool
    def zoom_meetings(max_results: int = 30) -> str:
        """List upcoming meetings in this connected Zoom account."""
        count = runtime._limit(max_results, minimum=1, maximum=100)
        runtime._record(usage, "zoom", "zoom_meetings")
        query = urllib.parse.urlencode({"type": "upcoming", "page_size": count})
        value = runtime._api_json(
            f"{runtime.ZOOM_API_URL}/users/me/meetings?{query}",
            runtime._provider_access_token(binding),
        )
        meetings = value.get("meetings", [])
        return json.dumps(
            {"meetings": [public_meeting(item) for item in meetings if isinstance(item, dict)]
             if isinstance(meetings, list) else []},
            separators=(",", ":"),
        )

    @tool
    def zoom_meeting(meeting_id: str) -> str:
        """Read basic details of a meeting in this connected Zoom account."""
        meeting = runtime._text(meeting_id, "meeting_id", 20)
        if not re.fullmatch(r"[0-9]{8,20}", meeting):
            raise ValueError("Zoom meeting identity is invalid")
        runtime._record(usage, "zoom", "zoom_meeting")
        value = runtime._api_json(
            f"{runtime.ZOOM_API_URL}/meetings/{meeting}",
            runtime._provider_access_token(binding),
        )
        return json.dumps(public_meeting(value), separators=(",", ":"))

    return [zoom_meetings, zoom_meeting]
