from __future__ import annotations

import logging
from collections.abc import Callable

from shared.catalog import CatalogError
from shared.connection_providers import (
    SUPPORTED_CONNECTION_PROVIDER_IDS,
    connection_provider,
)

from .external_oauth import (
    _begin_hubspot_authorization,
    _begin_jira_authorization,
    _begin_microsoft_authorization,
    _begin_microsoft_teams_authorization,
    _begin_notion_authorization,
    _begin_slack_authorization,
    _begin_zoom_authorization,
)
from .github_oauth import _begin_github_authorization
from .google_oauth import (
    _begin_gmail_authorization,
    _begin_google_workspace_authorization,
    _begin_youtube_authorization,
)
from .support import ApiError, catalog
from .x_oauth import _begin_x_authorization

AuthorizationHandler = Callable[[str, dict], dict]
logger = logging.getLogger(__name__)
_AUTHORIZATION_HANDLERS: dict[str, AuthorizationHandler] = {
    "github": _begin_github_authorization,
    "gmail": _begin_gmail_authorization,
    "youtube": _begin_youtube_authorization,
    "google_workspace": _begin_google_workspace_authorization,
    "slack": _begin_slack_authorization,
    "microsoft": _begin_microsoft_authorization,
    "microsoft_teams": _begin_microsoft_teams_authorization,
    "notion": _begin_notion_authorization,
    "hubspot": _begin_hubspot_authorization,
    "jira": _begin_jira_authorization,
    "zoom": _begin_zoom_authorization,
    "x": _begin_x_authorization,
}
if frozenset(_AUTHORIZATION_HANDLERS) | {"home_assistant", "mcp_server"} != SUPPORTED_CONNECTION_PROVIDER_IDS:
    raise RuntimeError("Every visible connection provider must have an authorization adapter")


def _connections(user_id: str) -> dict:
    return {"connections": catalog.list_connections(user_id)}


def _connect_home_assistant(user_id: str, value: dict) -> dict:
    # Compatibility endpoint for older clients. Count requests before retiring it;
    # new clients use generic MCP servers and existing grant IDs remain stable.
    logger.info("Legacy Home Assistant connection route used")
    try:
        return catalog.save_home_assistant_connection(
            user_id, value.get("instanceUrl"), value.get("accessToken")
        )
    except CatalogError as exc:
        raise ApiError(400, str(exc)) from exc


def _connect_mcp_server(user_id: str, value: dict) -> dict:
    try:
        return catalog.save_mcp_server_connection(
            user_id, value.get("name"), value.get("url"), value.get("accessToken")
        )
    except CatalogError as exc:
        raise ApiError(400, str(exc)) from exc


def _rename_mcp_server(user_id: str, connection_id: str, value: dict) -> dict:
    try:
        return catalog.rename_mcp_server_connection(
            user_id, connection_id, value.get("name")
        )
    except CatalogError as exc:
        status = 404 if str(exc) == "MCP server not found" else 400
        raise ApiError(status, str(exc)) from exc


def _begin_connection_authorization(
    user_id: str, provider_id: str, value: dict
) -> dict:
    provider = connection_provider(provider_id)
    if not provider:
        raise ApiError(
            404,
            "Connection provider not found",
            code="connection_provider_not_found",
        )
    handler = _AUTHORIZATION_HANDLERS.get(provider["id"])
    if handler:
        return handler(user_id, value)
    raise ApiError(
        501,
        "This connection provider is not available",
        code="connection_provider_unavailable",
    )


def _delete_connection(user_id: str, connection_id: str) -> dict:
    try:
        return catalog.delete_connection(user_id, connection_id)
    except CatalogError as exc:
        status = 409 if "before deleting" in str(exc) else 404
        raise ApiError(status, str(exc)) from exc
