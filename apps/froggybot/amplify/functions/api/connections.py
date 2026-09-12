from __future__ import annotations

from collections.abc import Callable

from shared.catalog import CatalogError
from shared.connection_providers import connection_provider

from .google_oauth import _begin_gmail_authorization
from .support import ApiError, catalog

AuthorizationHandler = Callable[[str, dict], dict]
_AUTHORIZATION_HANDLERS: dict[str, AuthorizationHandler] = {
    "gmail": _begin_gmail_authorization,
}


def _connections(user_id: str) -> dict:
    return {"connections": catalog.list_connections(user_id)}


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
