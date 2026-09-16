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
        "Public YouTube research is included. Connect only the Google services "
        "each bot needs."
    ),
    "familyIconText": "G",
    "familyLogoProviderId": "google_workspace",
    "familyIncludedSummary": "Public YouTube research included",
    "familyIncludedToolIds": ["youtube_search"],
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
            "FroggyBot stores the installation grant, not a personal token. "
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
        "id": "gmail",
        "name": "Gmail",
        "description": "Search and summarize email, then create drafts for review.",
        "category": "Email",
        "iconText": "G",
        "permissionsSummary": "No sending, deleting, relabeling, or archiving",
        "privacyTitle": "Your Gmail account stays private",
        "privacyDescription": (
            "FroggyBot uses this connection only when a bot needs the account. "
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
            "Public YouTube research remains included without sign-in. Connect only "
            "when a bot needs your own channel or private channel data."
        ),
        "connectLabel": "Connect account",
        "reconnectLabel": "Reconnect account",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "youtube", "oauth"],
        "actions": ["Read channel details", "List uploaded videos"],
        "scopes": ["https://www.googleapis.com/auth/youtube.readonly"],
        **GOOGLE_FAMILY,
        "serviceName": "YouTube Studio",
    },
    {
        "id": "google_workspace",
        "name": "Google Workspace",
        "description": "Search and read Drive files, Docs, and Calendar events.",
        "category": "Productivity",
        "iconText": "GW",
        "permissionsSummary": "Read-only Drive, Docs, and Calendar access",
        "privacyTitle": "Workspace content stays user-scoped",
        "privacyDescription": (
            "FroggyBot requests read-only access and exposes only reviewed Drive, "
            "Docs, and Calendar tools. It cannot change files or calendar events."
        ),
        "connectLabel": "Connect account",
        "reconnectLabel": "Reconnect account",
        "authType": "oauth",
        "runtimeKind": "mcp_bundle",
        "risk": "read",
        "tags": ["private", "google", "workspace", "mcp"],
        "actions": ["Search Drive", "Read documents", "Read calendar events"],
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
            "FroggyBot uses a per-user Slack grant and cannot post, react, edit, "
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
            "FroggyBot acts only for the signed-in user. It cannot send mail, "
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
        "id": "notion",
        "name": "Notion",
        "description": "Search and read pages shared with the FroggyBot connection.",
        "category": "Knowledge",
        "iconText": "N",
        "permissionsSummary": "Read content only; users choose accessible pages",
        "privacyTitle": "Notion access is page-scoped",
        "privacyDescription": (
            "Each workspace chooses which pages to share. FroggyBot cannot insert, "
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
        "id": "x",
        "name": "X",
        "description": "Read your profile and account-visible posts with per-user OAuth.",
        "category": "Social",
        "iconText": "X",
        "permissionsSummary": "Read-only; no posting, liking, following, or messages",
        "privacyTitle": "Public X research remains included",
        "privacyDescription": (
            "Connect only for account-specific data. FroggyBot requests read scopes "
            "and offline access, never write permissions."
        ),
        "connectLabel": "Connect account",
        "reconnectLabel": "Reconnect account",
        "authType": "oauth",
        "risk": "read",
        "tags": ["private", "x", "oauth"],
        "actions": ["Read profile", "Read own posts", "Read mentions"],
        "scopes": ["tweet.read", "users.read", "offline.access"],
        "familyId": "x",
        "familyName": "X",
        "familyDescription": (
            "Search recent public posts without connecting an account. Connect only "
            "when a bot needs your profile, posts, or mentions."
        ),
        "familyIconText": "X",
        "familyLogoProviderId": "x",
        "familyIncludedSummary": "Public post search included",
        "familyIncludedToolIds": ["x_search"],
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
