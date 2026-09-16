from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from strands import tool


def _runtime():
    # Imported lazily so provider_connections can re-export these factories
    # without a module-initialization cycle.
    from . import provider_connections

    return provider_connections


def _x_profile(binding: dict, access_token: str) -> dict:
    runtime = _runtime()
    query = urllib.parse.urlencode(
        {
            "user.fields": (
                "id,name,username,created_at,description,location,protected,"
                "public_metrics,verified"
            )
        }
    )
    value = runtime._api_json(f"{runtime.X_API_URL}/users/me?{query}", access_token)
    profile = value.get("data")
    user_id = profile.get("id") if isinstance(profile, dict) else None
    if not isinstance(user_id, str) or not re.fullmatch(r"[0-9]{1,30}", user_id):
        raise ValueError("X could not identify the connected account")
    return profile


def x_tools(binding: dict, usage: Any) -> list[Any]:
    runtime = _runtime()

    @tool
    def x_my_profile() -> str:
        """Read the connected X user's profile and public account metrics."""
        runtime._record(usage, "x", "x_my_profile")
        access_token = runtime._x_access_token(binding)
        return json.dumps(_x_profile(binding, access_token), separators=(",", ":"))

    def timeline(path: str, count: int) -> str:
        access_token = runtime._x_access_token(binding)
        profile = _x_profile(binding, access_token)
        query = urllib.parse.urlencode(
            {
                "max_results": str(count),
                "tweet.fields": (
                    "id,text,created_at,conversation_id,public_metrics,referenced_tweets"
                ),
            }
        )
        value = runtime._api_json(
            f"{runtime.X_API_URL}/users/{profile['id']}/{path}?{query}", access_token
        )
        data = value.get("data")
        return json.dumps(
            {"posts": data if isinstance(data, list) else []},
            separators=(",", ":"),
        )

    @tool
    def x_my_posts(max_results: int = 10) -> str:
        """Read recent posts authored by the connected X user."""
        count = runtime._limit(max_results, minimum=5, maximum=100)
        runtime._record(usage, "x", "x_my_posts")
        return timeline("tweets", count)

    @tool
    def x_my_mentions(max_results: int = 10) -> str:
        """Read recent posts that mention the connected X user."""
        count = runtime._limit(max_results, minimum=5, maximum=100)
        runtime._record(usage, "x", "x_my_mentions")
        return timeline("mentions", count)

    return [x_my_profile, x_my_posts, x_my_mentions]


def slack_tools(binding: dict, usage: Any) -> list[Any]:
    runtime = _runtime()

    @tool
    def slack_search(query: str, max_results: int = 20) -> str:
        """Search Slack content visible to the connected user."""
        search_query = runtime._text(query, "query", 500)
        count = runtime._limit(max_results, minimum=1, maximum=20)
        runtime._record(usage, "slack", "slack_search")
        value = runtime._provider_api_json(
            f"{runtime.SLACK_API_URL}/assistant.search.context",
            runtime._provider_access_token(binding),
            payload={
                "query": search_query,
                "content_types": ["messages", "files", "channels", "users"],
                "channel_types": [
                    "public_channel",
                    "private_channel",
                    "mpim",
                    "im",
                ],
                "limit": count,
            },
        )
        if value.get("ok") is not True:
            raise ValueError("Slack search is unavailable")
        return json.dumps(value, separators=(",", ":"))

    @tool
    def slack_thread(
        channel_id: str, thread_timestamp: str, max_results: int = 100
    ) -> str:
        """Read a Slack thread selected from search results without changing it."""
        channel = runtime._text(channel_id, "channel_id", 32)
        timestamp = runtime._text(thread_timestamp, "thread_timestamp", 40)
        if not re.fullmatch(r"[A-Z0-9]{2,32}", channel) or not re.fullmatch(
            r"[0-9]{1,20}\.[0-9]{1,20}", timestamp
        ):
            raise ValueError("Slack thread identity is invalid")
        count = runtime._limit(max_results, minimum=1, maximum=200)
        runtime._record(usage, "slack", "slack_thread")
        query = urllib.parse.urlencode(
            {"channel": channel, "ts": timestamp, "limit": str(count)}
        )
        value = runtime._api_json(
            f"{runtime.SLACK_API_URL}/conversations.replies?{query}",
            runtime._provider_access_token(binding),
        )
        if value.get("ok") is not True:
            raise ValueError("Slack thread is unavailable")
        return json.dumps(
            {
                "messages": value.get("messages", []),
                "response_metadata": value.get("response_metadata", {}),
            },
            separators=(",", ":"),
        )

    return [slack_search, slack_thread]


def microsoft_tools(binding: dict, usage: Any) -> list[Any]:
    runtime = _runtime()

    @tool
    def microsoft_recent_mail(max_results: int = 20) -> str:
        """Read recent Outlook messages from the connected user's mailbox."""
        count = runtime._limit(max_results, minimum=1, maximum=50)
        runtime._record(usage, "microsoft", "microsoft_recent_mail")
        query = urllib.parse.urlencode(
            {
                "$top": str(count),
                "$select": (
                    "id,subject,from,receivedDateTime,bodyPreview,isRead,webLink"
                ),
                "$orderby": "receivedDateTime desc",
            }
        )
        value = runtime._api_json(
            f"{runtime.MICROSOFT_API_URL}/me/messages?{query}",
            runtime._provider_access_token(binding),
        )
        return json.dumps({"messages": value.get("value", [])}, separators=(",", ":"))

    @tool
    def microsoft_calendar_events(
        start_datetime: str, end_datetime: str, max_results: int = 20
    ) -> str:
        """Read Outlook calendar events in an ISO-8601 time window."""
        start = runtime._text(start_datetime, "start_datetime", 40)
        end = runtime._text(end_datetime, "end_datetime", 40)
        if not re.fullmatch(r"[0-9T:+.\-Z]{10,40}", start) or not re.fullmatch(
            r"[0-9T:+.\-Z]{10,40}", end
        ):
            raise ValueError("Calendar window is invalid")
        count = runtime._limit(max_results, minimum=1, maximum=100)
        runtime._record(usage, "microsoft", "microsoft_calendar_events")
        query = urllib.parse.urlencode(
            {
                "startDateTime": start,
                "endDateTime": end,
                "$top": str(count),
                "$select": (
                    "subject,start,end,location,organizer,attendees,isOnlineMeeting,"
                    "onlineMeeting,webLink"
                ),
                "$orderby": "start/dateTime",
            }
        )
        value = runtime._api_json(
            f"{runtime.MICROSOFT_API_URL}/me/calendarView?{query}",
            runtime._provider_access_token(binding),
        )
        return json.dumps({"events": value.get("value", [])}, separators=(",", ":"))

    @tool
    def microsoft_search_content(query: str, max_results: int = 20) -> str:
        """Search OneDrive and SharePoint content visible to the connected user."""
        search_query = runtime._text(query, "query", 500)
        count = runtime._limit(max_results, minimum=1, maximum=50)
        runtime._record(usage, "microsoft", "microsoft_search_content")
        value = runtime._provider_api_json(
            f"{runtime.MICROSOFT_API_URL}/search/query",
            runtime._provider_access_token(binding),
            payload={
                "requests": [
                    {
                        "entityTypes": ["driveItem", "listItem", "site"],
                        "query": {"queryString": search_query},
                        "from": 0,
                        "size": count,
                    }
                ]
            },
        )
        return json.dumps({"results": value.get("value", [])}, separators=(",", ":"))

    return [
        microsoft_recent_mail,
        microsoft_calendar_events,
        microsoft_search_content,
    ]


def notion_tools(binding: dict, usage: Any) -> list[Any]:
    runtime = _runtime()
    headers = {"notion-version": runtime.NOTION_API_VERSION}

    @tool
    def notion_search(query: str, max_results: int = 20) -> str:
        """Search pages and data sources shared with the Notion connection."""
        search_query = runtime._text(query, "query", 500)
        count = runtime._limit(max_results, minimum=1, maximum=100)
        runtime._record(usage, "notion", "notion_search")
        value = runtime._provider_api_json(
            f"{runtime.NOTION_API_URL}/search",
            runtime._provider_access_token(binding),
            payload={"query": search_query, "page_size": count},
            headers=headers,
        )
        return json.dumps(value, separators=(",", ":"))

    @tool
    def notion_page(page_id: str) -> str:
        """Read metadata and properties for one shared Notion page."""
        page = runtime._text(page_id, "page_id", 40)
        if not re.fullmatch(r"[A-Fa-f0-9-]{32,40}", page):
            raise ValueError("Notion page id is invalid")
        runtime._record(usage, "notion", "notion_page")
        value = runtime._provider_api_json(
            f"{runtime.NOTION_API_URL}/pages/{urllib.parse.quote(page, safe='')}",
            runtime._provider_access_token(binding),
            headers=headers,
        )
        return json.dumps(value, separators=(",", ":"))

    @tool
    def notion_block_children(block_id: str, max_results: int = 50) -> str:
        """Read child blocks for a shared Notion page or block."""
        block = runtime._text(block_id, "block_id", 40)
        if not re.fullmatch(r"[A-Fa-f0-9-]{32,40}", block):
            raise ValueError("Notion block id is invalid")
        count = runtime._limit(max_results, minimum=1, maximum=100)
        runtime._record(usage, "notion", "notion_block_children")
        query = urllib.parse.urlencode({"page_size": str(count)})
        value = runtime._provider_api_json(
            (
                f"{runtime.NOTION_API_URL}/blocks/{urllib.parse.quote(block, safe='')}"
                f"/children?{query}"
            ),
            runtime._provider_access_token(binding),
            headers=headers,
        )
        return json.dumps(value, separators=(",", ":"))

    return [notion_search, notion_page, notion_block_children]
