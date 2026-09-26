"""Generated from packages/heytim-contract/src/platform-contract.json. Do not edit directly."""
from __future__ import annotations

GMAIL_MCP_ENDPOINT = "https://gmailmcp.googleapis.com/mcp/v1"
GMAIL_MCP_TOOLS = frozenset(["create_draft", "list_drafts", "get_draft", "get_thread", "get_message", "search_threads", "list_labels"])
GMAIL_OAUTH_SCOPES = ("https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose")
YOUTUBE_OAUTH_SCOPES = ("openid", "email", "https://www.googleapis.com/auth/youtube.readonly")
GOOGLE_WORKSPACE_OAUTH_SCOPES = ("https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/documents.readonly", "https://www.googleapis.com/auth/calendar.calendarlist.readonly", "https://www.googleapis.com/auth/calendar.events.freebusy", "https://www.googleapis.com/auth/calendar.events.readonly")
GOOGLE_WORKSPACE_SCOPES = frozenset(GOOGLE_WORKSPACE_OAUTH_SCOPES)
GOOGLE_WORKSPACE_MCP_SERVERS = {
    "https://drivemcp.googleapis.com/mcp/v1": frozenset(["download_file_content", "get_file_metadata", "get_file_permissions", "list_recent_files", "read_file_content", "search_files"]),
    "https://docsmcp.googleapis.com/mcp/v1": frozenset(["read_doc"]),
    "https://sheetsmcp.googleapis.com/mcp/v1": frozenset(["get_spreadsheet", "get_values"]),
    "https://calendarmcp.googleapis.com/mcp/v1": frozenset(["get_event", "list_calendars", "list_events", "search_events", "suggest_time"]),
}
SCOPED_GOOGLE_TOOLS = {
    "drivemcp.googleapis.com": {
        "get_file_metadata": "fileId",
        "get_file_permissions": "fileId",
        "read_file_content": "fileId",
        "download_file_content": "fileId",
    },
    "docsmcp.googleapis.com": {
        "read_doc": "documentId",
    },
    "sheetsmcp.googleapis.com": {
        "get_spreadsheet": "spreadsheetId",
        "get_values": "spreadsheetId",
    },
    "calendarmcp.googleapis.com": {
        "get_event": "calendarId",
        "list_events": "calendarId",
    },
}
