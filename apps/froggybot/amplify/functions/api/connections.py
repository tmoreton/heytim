from __future__ import annotations

from shared.catalog import CatalogError

from .support import ApiError, catalog


def _connections(user_id: str) -> dict:
    return {"connections": catalog.list_connections(user_id)}


def _delete_connection(user_id: str, connection_id: str) -> dict:
    try:
        return catalog.delete_connection(user_id, connection_id)
    except CatalogError as exc:
        status = 409 if "before deleting" in str(exc) else 404
        raise ApiError(status, str(exc)) from exc
