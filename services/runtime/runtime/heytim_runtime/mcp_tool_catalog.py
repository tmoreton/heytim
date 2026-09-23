"""Reviewed Google Workspace MCP endpoints, scopes, and tool allowlists."""

GMAIL_MCP_ENDPOINT = "https://gmailmcp.googleapis.com/mcp/v1"
GMAIL_MCP_TOOLS = {
    "create_draft",
    "list_drafts",
    "get_draft",
    "get_thread",
    "get_message",
    "search_threads",
    "list_labels",
}
GOOGLE_WORKSPACE_MCP_SERVERS = {
    "https://drivemcp.googleapis.com/mcp/v1": {
        "download_file_content",
        "get_file_metadata",
        "get_file_permissions",
        "list_recent_files",
        "read_file_content",
        "search_files",
    },
    "https://docsmcp.googleapis.com/mcp/v1": {"read_doc"},
    "https://sheetsmcp.googleapis.com/mcp/v1": {
        "get_spreadsheet",
        "get_values",
    },
    "https://calendarmcp.googleapis.com/mcp/v1": {
        "get_event",
        "list_calendars",
        "list_events",
        "search_events",
        "suggest_time",
    },
}
GOOGLE_WORKSPACE_SCOPES = {
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
    "https://www.googleapis.com/auth/calendar.events.readonly",
}
SCOPED_GOOGLE_TOOLS = {
    "drivemcp.googleapis.com": {
        "get_file_metadata": "fileId",
        "get_file_permissions": "fileId",
        "read_file_content": "fileId",
        "download_file_content": "fileId",
    },
    "docsmcp.googleapis.com": {"read_doc": "documentId"},
    "sheetsmcp.googleapis.com": {
        "get_spreadsheet": "spreadsheetId",
        "get_values": "spreadsheetId",
    },
    "calendarmcp.googleapis.com": {
        "get_event": "calendarId",
        "list_events": "calendarId",
    },
}
