from __future__ import annotations

import os
from copy import deepcopy

from .github_app import GITHUB_MCP_ENDPOINT

GMAIL_MCP_ENDPOINT = "https://gmailmcp.googleapis.com/mcp/v1"
GMAIL_MCP_TOOLS = (
    "create_draft",
    "list_drafts",
    "get_draft",
    "get_thread",
    "get_message",
    "search_threads",
    "list_labels",
)
GOOGLE_WORKSPACE_MCP_SERVERS = (
    {
        "endpoint": "https://drivemcp.googleapis.com/mcp/v1",
        "allowedTools": (
            "download_file_content",
            "get_file_metadata",
            "get_file_permissions",
            "list_recent_files",
            "read_file_content",
            "search_files",
        ),
    },
    {
        "endpoint": "https://docsmcp.googleapis.com/mcp/v1",
        "allowedTools": ("read_doc",),
    },
    {
        "endpoint": "https://sheetsmcp.googleapis.com/mcp/v1",
        "allowedTools": ("get_spreadsheet", "get_values"),
    },
    {
        "endpoint": "https://calendarmcp.googleapis.com/mcp/v1",
        "allowedTools": (
            "get_event",
            "list_calendars",
            "list_events",
            "search_events",
            "suggest_time",
        ),
    },
)

PUBLIC_PROVIDER_FIELDS = (
    "id",
    "name",
    "description",
    "category",
    "iconText",
    "permissionsSummary",
    "privacyTitle",
    "privacyDescription",
    "connectLabel",
    "reconnectLabel",
)
OPTIONAL_PUBLIC_PROVIDER_FIELDS = (
    "familyId",
    "familyName",
    "familyDescription",
    "familyIconText",
    "familyLogoProviderId",
    "familyIncludedSummary",
    "familyIncludedToolIds",
    "serviceName",
)

GOOGLE_FAMILY = {
    "familyId": "google",
    "familyName": "Google",
    "familyDescription": (
        "Connect the Google accounts each bot needs. YouTube search is available "
        "through a connected YouTube account."
    ),
    "familyIconText": "G",
    "familyLogoProviderId": "google_workspace",
}

# This is the single backend registry for connection identity, client presentation,
# and stored connection metadata. Authentication implementations remain private to
# the API/runtime and are never exposed in the bootstrap response.
CONNECTION_PROVIDER_SPECS = (
    {
        "id": "github",
        "name": "GitHub",
        "description": "Work with repositories selected during GitHub App installation.",
        "category": "Developer tools",
        "iconText": "GH",
        "permissionsSummary": "Only selected repositories and app permissions",
        "privacyTitle": "Repository access stays narrowly scoped",
        "privacyDescription": (
            "HeyTim stores the installation grant, not a personal token. "
            "It mints one-hour installation tokens only when a bot uses GitHub."
        ),
        "connectLabel": "Install app",
        "reconnectLabel": "Update installation",
        "authType": "github_app",
        "risk": "interactive",
        "endpoint": GITHUB_MCP_ENDPOINT,
        "tags": ["private", "github", "mcp"],
        "actions": ["Read repositories", "Create branches", "Open pull requests"],
    },
    {
        "id": "home_assistant",
        "name": "Home Assistant",
        "description": "Read exposed devices and request home actions through your own Home Assistant instance.",
        "category": "Smart home",
        "iconText": "HA",
        "permissionsSummary": "Only entities exposed to Assist; each action requires review",
        "privacyTitle": "Your home stays under your control",
        "privacyDescription": (
            "HeyTim stores your token privately on the server and uses only the "
            "Home Assistant Assist MCP endpoint. You choose which entities Assist exposes."
        ),
        "connectLabel": "Connect home",
        "reconnectLabel": "Update connection",
        "authType": "home_assistant_token",
        "risk": "interactive",
        "tags": ["private", "home", "devices", "mcp"],
        "actions": ["Read exposed device state", "Request device actions"],
    },
    {
        "id": "gmail",
        "name": "Gmail",
        "description": "Search and summarize email, then create drafts for review.",
        "category": "Email",
        "iconText": "G",
        "permissionsSummary": "No sending, deleting, relabeling, or archiving",
        "privacyTitle": "Your Gmail account stays private",
        "privacyDescription": (
            "HeyTim uses this connection only when a bot needs the account. "
            "It can search and read email and create drafts for review."
        ),
        "connectLabel": "Connect account",
        "reconnectLabel": "Reconnect account",
        "authType": "oauth",
        "risk": "interactive",
        "endpoint": GMAIL_MCP_ENDPOINT,
        "tags": ["private", "gmail", "mcp"],
        "actions": ["Search email", "Read threads", "Create drafts"],
        **GOOGLE_FAMILY,
        "serviceName": "Gmail",
    },
    {
        "id": "youtube",
        "name": "YouTube Studio",
        "description": "Read your own channel, uploads, and private channel data.",
        "category": "Video",
        "iconText": "YT",
        "permissionsSummary": "Read-only channel access; shared project quota still applies",
        "privacyTitle": "Your channel connection is optional",
        "privacyDescription": (
            "Connect a YouTube account before a bot can search videos or read "
            "your own channel data."
        ),
        "connectLabel": "Connect account",
        "reconnectLabel": "Reconnect account",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "youtube", "oauth"],
        "actions": ["Search videos", "Read channel details", "List uploaded videos"],
        "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
        **GOOGLE_FAMILY,
        "serviceName": "YouTube Studio",
    },
    {
        "id": "google_workspace",
        "name": "Google Workspace",
        "description": "Search and read Drive files, Docs, Sheets, and Calendar events.",
        "category": "Productivity",
        "iconText": "GW",
        "permissionsSummary": "Read-only Drive, Docs, Sheets, and Calendar access",
        "privacyTitle": "Workspace content stays user-scoped",
        "privacyDescription": (
            "HeyTim requests read-only access and exposes only reviewed Drive, "
            "Docs, Sheets, and Calendar tools. It cannot change files or calendar events."
        ),
        "connectLabel": "Connect account",
        "reconnectLabel": "Reconnect account",
        "authType": "oauth",
        "runtimeKind": "mcp_bundle",
        "risk": "read",
        "tags": ["private", "google", "workspace", "mcp"],
        "actions": ["Search Drive", "Read documents", "Read spreadsheets", "Read calendar events"],
        "scopes": [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/documents.readonly",
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "https://www.googleapis.com/auth/calendar.events.freebusy",
            "https://www.googleapis.com/auth/calendar.events.readonly",
        ],
        **GOOGLE_FAMILY,
        "serviceName": "Workspace",
    },
    {
        "id": "slack",
        "name": "Slack",
        "description": "Search messages and read threads from your connected workspace.",
        "category": "Team communication",
        "iconText": "S",
        "permissionsSummary": "Read-only search and conversation history",
        "privacyTitle": "Slack access follows your own workspace permissions",
        "privacyDescription": (
            "HeyTim uses a per-user Slack grant and cannot post, react, edit, "
            "or delete messages. Private results remain limited by Slack consent."
        ),
        "connectLabel": "Connect workspace",
        "reconnectLabel": "Reconnect workspace",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "slack", "oauth"],
        "actions": ["Search Slack", "Read conversations", "Read threads"],
        "scopes": [
            "search:read.public",
            "search:read.private",
            "search:read.mpim",
            "search:read.im",
            "search:read.files",
            "search:read.users",
            "channels:history",
            "groups:history",
            "im:history",
            "mpim:history",
        ],
    },
    {
        "id": "microsoft",
        "name": "Microsoft 365",
        "description": "Read Outlook mail and calendars, OneDrive, and SharePoint.",
        "category": "Productivity",
        "iconText": "M",
        "permissionsSummary": "Delegated read-only Microsoft Graph access",
        "privacyTitle": "Microsoft data stays user-scoped",
        "privacyDescription": (
            "HeyTim acts only for the signed-in user. It cannot send mail, "
            "change calendars, or modify OneDrive and SharePoint content."
        ),
        "connectLabel": "Connect Microsoft",
        "reconnectLabel": "Reconnect Microsoft",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "microsoft", "graph", "oauth"],
        "actions": ["Read Outlook mail", "Read calendars", "Search files and sites"],
        "scopes": [
            "openid",
            "profile",
            "email",
            "offline_access",
            "User.Read",
            "Mail.Read",
            "Calendars.Read",
            "Files.Read.All",
            "Sites.Read.All",
        ],
    },
    {
        "id": "microsoft_teams",
        "name": "Microsoft Teams",
        "description": "Read joined teams, channels, and channel messages.",
        "category": "Team communication",
        "iconText": "MT",
        "permissionsSummary": "Delegated, read-only Teams channel access",
        "privacyTitle": "Teams access is assigned per bot",
        "privacyDescription": (
            "Connect a Microsoft account and assign this connection only to bots "
            "that need Teams. Bots cannot post or edit messages."
        ),
        "connectLabel": "Connect Teams account",
        "reconnectLabel": "Reconnect Teams account",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "microsoft", "teams", "oauth"],
        "actions": ["List joined teams", "List channels", "Read channel messages"],
        "scopes": [
            "openid", "profile", "email", "offline_access", "User.Read",
            "Team.ReadBasic.All", "Channel.ReadBasic.All", "ChannelMessage.Read.All",
        ],
    },
    {
        "id": "notion",
        "name": "Notion",
        "description": "Search and read pages shared with the HeyTim connection.",
        "category": "Knowledge",
        "iconText": "N",
        "permissionsSummary": "Read content only; users choose accessible pages",
        "privacyTitle": "Notion access is page-scoped",
        "privacyDescription": (
            "Each workspace chooses which pages to share. HeyTim cannot insert, "
            "update, or delete Notion content."
        ),
        "connectLabel": "Connect workspace",
        "reconnectLabel": "Reconnect workspace",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "notion", "oauth"],
        "actions": ["Search pages", "Read pages", "Read page blocks"],
        "scopes": ["read_content"],
    },
    {
        "id": "hubspot",
        "name": "HubSpot",
        "description": "Search contacts, companies, and deals in a connected CRM account.",
        "category": "Sales & CRM",
        "iconText": "H",
        "permissionsSummary": "Read-only contacts, companies, and deals",
        "privacyTitle": "Each CRM account is assigned separately",
        "privacyDescription": (
            "A bot can use only the HubSpot accounts you assign. "
            "HeyTim cannot change CRM records."
        ),
        "connectLabel": "Connect HubSpot account",
        "reconnectLabel": "Reconnect HubSpot account",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "hubspot", "crm", "oauth"],
        "actions": ["Search contacts", "Search companies", "Search deals"],
        "scopes": [
            "crm.objects.contacts.read",
            "crm.objects.companies.read",
            "crm.objects.deals.read",
        ],
    },
    {
        "id": "jira",
        "name": "Jira",
        "description": "Read projects and issues from one connected Jira site.",
        "category": "Project management",
        "iconText": "J",
        "permissionsSummary": "Read-only access to the selected Jira site",
        "privacyTitle": "Each Jira site is assigned separately",
        "privacyDescription": (
            "Connect one Jira site at a time. A bot can read only the sites "
            "you assign to it, and cannot change issues."
        ),
        "connectLabel": "Connect Jira site",
        "reconnectLabel": "Reconnect Jira site",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "jira", "projects", "oauth"],
        "actions": ["List projects", "Search issues", "Read issues"],
        "scopes": ["offline_access", "read:jira-work"],
    },
    {
        "id": "zoom",
        "name": "Zoom",
        "description": "Read meetings from a connected Zoom account.",
        "category": "Meetings",
        "iconText": "Z",
        "permissionsSummary": "Read-only profile and meeting access",
        "privacyTitle": "Zoom meetings stay account-scoped",
        "privacyDescription": (
            "Only assigned bots can list or read meetings in this Zoom account. "
            "HeyTim cannot start, change, or delete meetings."
        ),
        "connectLabel": "Connect Zoom account",
        "reconnectLabel": "Reconnect Zoom account",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "zoom", "meetings", "oauth"],
        "actions": ["List meetings", "Read meeting details"],
        "scopes": ["user:read:user", "meeting:read:list_meetings", "meeting:read:meeting"],
    },
    {
        "id": "x",
        "name": "X",
        "description": "Read your profile and account-visible posts with per-user OAuth.",
        "category": "Social",
        "iconText": "X",
        "permissionsSummary": "Read-only; no posting, liking, following, or messages",
        "privacyTitle": "X access requires a connected account",
        "privacyDescription": (
            "Connect an X account before a bot can search posts or read your "
            "profile. HeyTim requests read scopes, never write permissions."
        ),
        "connectLabel": "Connect account",
        "reconnectLabel": "Reconnect account",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "x", "oauth"],
        "actions": ["Search recent posts", "Read profile", "Read own posts", "Read mentions"],
        "scopes": ["tweet.read", "users.read", "offline.access"],
        "familyId": "x",
        "familyName": "X",
        "familyDescription": (
            "Connect an X account to let selected bots search posts or read "
            "the account's profile, posts, and mentions."
        ),
        "familyIconText": "X",
        "familyLogoProviderId": "x",
        "serviceName": "Account access",
    },
)

_SPECS_BY_ID = {spec["id"]: spec for spec in CONNECTION_PROVIDER_SPECS}
SUPPORTED_CONNECTION_PROVIDER_IDS = frozenset(_SPECS_BY_ID)


def _public_provider(spec: dict) -> dict:
    return {
        field: deepcopy(spec[field])
        for field in (*PUBLIC_PROVIDER_FIELDS, *OPTIONAL_PUBLIC_PROVIDER_FIELDS)
        if field in spec
    }


def _disabled_provider_ids() -> frozenset[str]:
    return frozenset(
        provider_id.strip()
        for provider_id in os.environ.get(
            "DISABLED_CONNECTION_PROVIDER_IDS", ""
        ).split(",")
        if provider_id.strip() in SUPPORTED_CONNECTION_PROVIDER_IDS
    )


def connection_providers() -> list[dict]:
    disabled = _disabled_provider_ids()
    return [
        _public_provider(spec)
        for spec in CONNECTION_PROVIDER_SPECS
        if spec["id"] not in disabled
    ]


def connection_provider(provider_id: str) -> dict | None:
    if provider_id in _disabled_provider_ids():
        return None
    spec = _SPECS_BY_ID.get(provider_id)
    return _public_provider(spec) if spec else None


def connection_specs() -> dict[str, dict]:
    return {provider_id: deepcopy(spec) for provider_id, spec in _SPECS_BY_ID.items()}
