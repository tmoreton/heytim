from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from strands import tool

from .meeting_provider_tools import zoom_tools  # noqa: F401 - re-exported factory


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
    def x_search_recent(query: str, max_results: int = 10) -> str:
        """Search recent public X posts using the connected account."""
        search_query = runtime._text(query, "query", 512)
        count = runtime._limit(max_results, minimum=10, maximum=100)
        runtime._record(usage, "x", "x_search_recent")
        parameters = urllib.parse.urlencode(
            {
                "query": search_query,
                "max_results": str(count),
                "tweet.fields": "id,text,created_at,author_id,public_metrics",
            }
        )
        value = runtime._api_json(
            f"{runtime.X_API_URL}/tweets/search/recent?{parameters}",
            runtime._x_access_token(binding),
        )
        return json.dumps(
            {"posts": value.get("data", []), "meta": value.get("meta", {})},
            separators=(",", ":"),
        )

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

    return [x_search_recent, x_my_profile, x_my_posts, x_my_mentions]


def slack_tools(binding: dict, usage: Any) -> list[Any]:
    runtime = _runtime()
    allowed_channels = set(binding["resourceIds"]) if "resourceIds" in binding else None

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
                "content_types": (
                    ["messages"] if allowed_channels is not None
                    else ["messages", "files", "channels", "users"]
                ),
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
        if allowed_channels is not None:
            results = value.get("results")
            messages = results.get("messages") if isinstance(results, dict) else None
            if not isinstance(messages, list):
                messages = []
            return json.dumps(
                {"ok": True, "results": {"messages": [
                    item for item in messages
                    if isinstance(item, dict) and item.get("channel_id") in allowed_channels
                ]}},
                separators=(",", ":"),
            )
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
        if allowed_channels is not None and channel not in allowed_channels:
            raise ValueError("This bot is not assigned that Slack channel")
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
    selected_pages = (
        {value.replace("-", "").lower() for value in binding["resourceIds"]}
        if "resourceIds" in binding else None
    )
    visited_blocks = set(selected_pages or set())

    def normalized_id(value: str) -> str:
        return value.replace("-", "").lower()

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
        if selected_pages is not None:
            results = value.get("results")
            value = {"results": [
                item for item in results if isinstance(item, dict)
                and normalized_id(str(item.get("id", ""))) in selected_pages
            ] if isinstance(results, list) else []}
        return json.dumps(value, separators=(",", ":"))

    @tool
    def notion_page(page_id: str) -> str:
        """Read metadata and properties for one shared Notion page."""
        page = runtime._text(page_id, "page_id", 40)
        if not re.fullmatch(r"[A-Fa-f0-9-]{32,40}", page):
            raise ValueError("Notion page id is invalid")
        if selected_pages is not None and normalized_id(page) not in selected_pages:
            raise ValueError("This bot is not assigned that Notion page")
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
        if selected_pages is not None and normalized_id(block) not in visited_blocks:
            raise ValueError("This bot is not assigned that Notion page or block")
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
        if selected_pages is not None:
            results = value.get("results")
            if isinstance(results, list):
                visited_blocks.update(
                    normalized_id(item["id"])
                    for item in results
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                )
        return json.dumps(value, separators=(",", ":"))

    return [notion_search, notion_page, notion_block_children]


def hubspot_tools(binding: dict, usage: Any) -> list[Any]:
    runtime = _runtime()

    def search(object_type: str, query: str, count: int, properties: list[str]) -> str:
        value = runtime._provider_api_json(
            f"{runtime.HUBSPOT_API_URL}/crm/objects/2026-03/{object_type}/search",
            runtime._provider_access_token(binding),
            payload={
                "query": query,
                "limit": count,
                "properties": properties,
            },
        )
        return json.dumps(
            {"results": value.get("results", []), "total": value.get("total", 0)},
            separators=(",", ":"),
        )

    @tool
    def hubspot_contacts(query: str, max_results: int = 20) -> str:
        """Search contacts in this connected HubSpot account without changing them."""
        search_query = runtime._text(query, "query", 300)
        count = runtime._limit(max_results, minimum=1, maximum=50)
        runtime._record(usage, "hubspot", "hubspot_contacts")
        return search(
            "contacts", search_query, count,
            ["firstname", "lastname", "email", "company"],
        )

    @tool
    def hubspot_companies(query: str, max_results: int = 20) -> str:
        """Search companies in this connected HubSpot account without changing them."""
        search_query = runtime._text(query, "query", 300)
        count = runtime._limit(max_results, minimum=1, maximum=50)
        runtime._record(usage, "hubspot", "hubspot_companies")
        return search(
            "companies", search_query, count,
            ["name", "domain", "industry"],
        )

    @tool
    def hubspot_deals(query: str, max_results: int = 20) -> str:
        """Search deals in this connected HubSpot account without changing them."""
        search_query = runtime._text(query, "query", 300)
        count = runtime._limit(max_results, minimum=1, maximum=50)
        runtime._record(usage, "hubspot", "hubspot_deals")
        return search(
            "deals", search_query, count,
            ["dealname", "amount", "dealstage", "closedate"],
        )

    return [hubspot_contacts, hubspot_companies, hubspot_deals]


def jira_tools(binding: dict, usage: Any) -> list[Any]:
    runtime = _runtime()
    base = f"{runtime.JIRA_API_URL}/ex/jira/{binding['siteId']}/rest/api/3"
    allowed_projects = binding.get("projectKeys")

    def require_project(project: str) -> None:
        if allowed_projects is not None and project not in allowed_projects:
            raise ValueError("This bot is not assigned that Jira project")

    @tool
    def jira_projects(max_results: int = 50) -> str:
        """List projects visible in this connected Jira site."""
        count = runtime._limit(max_results, minimum=1, maximum=100)
        runtime._record(usage, "jira", "jira_projects")
        query = urllib.parse.urlencode(
            {
                "maxResults": count,
                "startAt": 0,
                **({"keys": allowed_projects} if allowed_projects is not None else {}),
            },
            doseq=True,
        )
        value = runtime._provider_api_json(
            f"{base}/project/search?{query}", runtime._provider_access_token(binding)
        )
        projects = value.get("values", [])
        if not isinstance(projects, list):
            projects = []
        if allowed_projects is not None:
            projects = [
                item for item in projects
                if isinstance(item, dict) and item.get("key") in allowed_projects
            ]
        return json.dumps(
            {"projects": projects, "total": len(projects)},
            separators=(",", ":"),
        )

    @tool
    def jira_search_issues(
        project_key: str, query: str, max_results: int = 20
    ) -> str:
        """Search issue text within one project of this connected Jira site."""
        project = runtime._text(project_key, "project_key", 32).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}", project):
            raise ValueError("Jira project key is invalid")
        require_project(project)
        search_query = runtime._text(query, "query", 200)
        count = runtime._limit(max_results, minimum=1, maximum=50)
        runtime._record(usage, "jira", "jira_search_issues")
        # Quote the search term as a JQL string and limit the returned fields.
        literal = json.dumps(search_query)
        params = urllib.parse.urlencode(
            {
                "jql": f"project = {project} AND text ~ {literal} ORDER BY updated DESC",
                "maxResults": count,
                "fields": "summary,status,assignee,updated,description",
            }
        )
        value = runtime._provider_api_json(
            f"{base}/search/jql?{params}", runtime._provider_access_token(binding)
        )
        return json.dumps(
            {"issues": value.get("issues", []), "nextPageToken": value.get("nextPageToken")},
            separators=(",", ":"),
        )

    @tool
    def jira_issue(issue_key: str) -> str:
        """Read an issue from this connected Jira site."""
        issue = runtime._text(issue_key, "issue_key", 40).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}-[1-9][0-9]{0,15}", issue):
            raise ValueError("Jira issue key is invalid")
        require_project(issue.rsplit("-", 1)[0])
        runtime._record(usage, "jira", "jira_issue")
        params = urllib.parse.urlencode(
            {"fields": "summary,status,assignee,updated,description"}
        )
        value = runtime._provider_api_json(
            f"{base}/issue/{issue}?{params}", runtime._provider_access_token(binding)
        )
        return json.dumps(value, separators=(",", ":"))

    return [jira_projects, jira_search_issues, jira_issue]


def teams_tools(binding: dict, usage: Any) -> list[Any]:
    runtime = _runtime()
    selected = (
        [dict(zip(("teamId", "channelId"), entry.split("/", 1)))
         for entry in binding["channelAccess"]]
        if "channelAccess" in binding else None
    )

    def selected_channels(team_id: str) -> set[str] | None:
        if selected is None:
            return None
        return {
            item["channelId"] for item in selected if item["teamId"] == team_id
        }

    def team_id(value: str) -> str:
        clean = runtime._text(value, "team_id", 64)
        if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", clean):
            raise ValueError("Teams team identity is invalid")
        return clean.lower()

    def channel_id(value: str) -> str:
        clean = runtime._text(value, "channel_id", 200)
        if not re.fullmatch(r"[A-Za-z0-9:_@.\-]{5,200}", clean):
            raise ValueError("Teams channel identity is invalid")
        return clean

    @tool
    def teams_joined(max_results: int = 50) -> str:
        """List Microsoft Teams joined by the connected account."""
        count = runtime._limit(max_results, minimum=1, maximum=100)
        runtime._record(usage, "microsoft_teams", "teams_joined")
        query = urllib.parse.urlencode({"$top": count})
        value = runtime._api_json(
            f"{runtime.MICROSOFT_API_URL}/me/joinedTeams?{query}",
            runtime._provider_access_token(binding),
        )
        teams = value.get("value", [])
        if not isinstance(teams, list):
            teams = []
        if selected is not None:
            allowed = {item["teamId"] for item in selected}
            teams = [item for item in teams if isinstance(item, dict) and item.get("id") in allowed]
        return json.dumps({"teams": teams}, separators=(",", ":"))

    @tool
    def teams_channels(team: str) -> str:
        """List channels in an assigned Microsoft Team."""
        tid = team_id(team)
        allowed = selected_channels(tid)
        if allowed is not None and not allowed:
            raise ValueError("This bot is not assigned that Microsoft Team")
        runtime._record(usage, "microsoft_teams", "teams_channels")
        value = runtime._api_json(
            f"{runtime.MICROSOFT_API_URL}/teams/{tid}/channels",
            runtime._provider_access_token(binding),
        )
        channels = value.get("value", [])
        if not isinstance(channels, list):
            channels = []
        if allowed is not None:
            channels = [item for item in channels if isinstance(item, dict) and item.get("id") in allowed]
        return json.dumps({"channels": channels}, separators=(",", ":"))

    @tool
    def teams_messages(team: str, channel: str, max_results: int = 30) -> str:
        """Read messages from an assigned Microsoft Teams channel."""
        tid = team_id(team)
        cid = channel_id(channel)
        allowed = selected_channels(tid)
        if allowed is not None and cid not in allowed:
            raise ValueError("This bot is not assigned that Teams channel")
        count = runtime._limit(max_results, minimum=1, maximum=50)
        runtime._record(usage, "microsoft_teams", "teams_messages")
        query = urllib.parse.urlencode({"$top": count})
        value = runtime._api_json(
            f"{runtime.MICROSOFT_API_URL}/teams/{tid}/channels/{urllib.parse.quote(cid, safe='')}/messages?{query}",
            runtime._provider_access_token(binding),
        )
        messages = value.get("value", [])
        return json.dumps(
            {"messages": messages if isinstance(messages, list) else []},
            separators=(",", ":"),
        )

    return [teams_joined, teams_channels, teams_messages]
