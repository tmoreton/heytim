from __future__ import annotations

import json
import urllib.parse
from typing import Any

from strands import tool


def _runtime():
    from . import provider_connections

    return provider_connections


def _youtube_tools(binding: dict, usage: Any) -> list[Any]:
    @tool
    def youtube_search(query: str, max_results: int = 10) -> str:
        """Search public YouTube videos using the connected Google account."""
        search_query = _runtime()._text(query, "query", 200)
        count = _runtime()._limit(max_results, minimum=1, maximum=25)
        _runtime()._record(usage, "youtube", "youtube_search")
        parameters = urllib.parse.urlencode(
            {"part": "snippet", "q": search_query, "type": "video", "maxResults": str(count)}
        )
        value = _runtime()._api_json(
            f"{_runtime().YOUTUBE_API_URL}/search?{parameters}", _runtime()._google_access_token(binding)
        )
        return json.dumps(
            {"videos": value.get("items", []), "pageInfo": value.get("pageInfo", {})},
            separators=(",", ":"),
        )

    @tool
    def youtube_my_channel() -> str:
        """Read the connected user's YouTube channel profile and aggregate statistics."""
        _runtime()._record(usage, "youtube", "youtube_my_channel")
        query = urllib.parse.urlencode(
            {
                "part": "id,snippet,contentDetails,statistics,status",
                "mine": "true",
                "maxResults": "1",
            }
        )
        value = _runtime()._api_json(
            f"{_runtime().YOUTUBE_API_URL}/channels?{query}", _runtime()._google_access_token(binding)
        )
        items = value.get("items")
        channel = items[0] if isinstance(items, list) and items else None
        if not isinstance(channel, dict):
            raise TypeError("The connected Google account has no YouTube channel")
        return json.dumps(
            {
                "id": channel.get("id"),
                "snippet": channel.get("snippet"),
                "statistics": channel.get("statistics"),
                "status": channel.get("status"),
            },
            separators=(",", ":"),
        )

    @tool
    def youtube_my_videos(max_results: int = 10) -> str:
        """List recent uploads from the connected user's own YouTube channel."""
        count = _runtime()._limit(max_results, minimum=1, maximum=50)
        _runtime()._record(usage, "youtube", "youtube_my_videos")
        access_token = _runtime()._google_access_token(binding)
        channel_query = urllib.parse.urlencode(
            {"part": "contentDetails", "mine": "true", "maxResults": "1"}
        )
        channel_value = _runtime()._api_json(
            f"{_runtime().YOUTUBE_API_URL}/channels?{channel_query}", access_token
        )
        channels = channel_value.get("items")
        channel = channels[0] if isinstance(channels, list) and channels else None
        content = channel.get("contentDetails") if isinstance(channel, dict) else None
        related = content.get("relatedPlaylists") if isinstance(content, dict) else None
        uploads = related.get("uploads") if isinstance(related, dict) else None
        if not isinstance(uploads, str) or not uploads:
            raise ValueError("The connected YouTube channel has no uploads playlist")
        videos_query = urllib.parse.urlencode(
            {
                "part": "id,snippet,contentDetails,status",
                "playlistId": uploads,
                "maxResults": str(count),
            }
        )
        value = _runtime()._api_json(
            f"{_runtime().YOUTUBE_API_URL}/playlistItems?{videos_query}", access_token
        )
        items = value.get("items")
        videos = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet")
            content_details = item.get("contentDetails")
            status = item.get("status")
            videos.append(
                {
                    "videoId": (
                        content_details.get("videoId")
                        if isinstance(content_details, dict)
                        else None
                    ),
                    "title": snippet.get("title")
                    if isinstance(snippet, dict)
                    else None,
                    "publishedAt": (
                        content_details.get("videoPublishedAt")
                        if isinstance(content_details, dict)
                        else None
                    ),
                    "privacyStatus": (
                        status.get("privacyStatus")
                        if isinstance(status, dict)
                        else None
                    ),
                }
            )
        return json.dumps({"videos": videos}, separators=(",", ":"))

    return [youtube_search, youtube_my_channel, youtube_my_videos]


