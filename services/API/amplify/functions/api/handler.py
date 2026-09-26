from __future__ import annotations

import logging
from typing import Any

from . import authenticated_routes
from .account import _begin_account_deletion
from .support import (
    ApiError,
    _display_name,
    _ensure_account_active,
    _response,
    _user_id,
    _username,
)

logger = logging.getLogger(__name__)


def handler(event: dict, _context: Any) -> dict:
    route_key = ""
    try:
        request_context = event.get("requestContext", {})
        method = request_context.get("http", {}).get("method", "")
        route_key = request_context.get("routeKey", "")
        path = event.get("rawPath", "")
        params = event.get("pathParameters") or {}

        user_id = _user_id(event)
        if method == "DELETE" and path == "/account":
            return _response(202, _begin_account_deletion(user_id, _username(event)))

        _ensure_account_active(user_id)
        return authenticated_routes.route_authenticated(
            user_id,
            _display_name(event),
            method,
            path,
            params,
            event,
            route_key=route_key,
        )
    except ApiError as exc:
        logger.warning(
            "API request rejected route=%s status=%s code=%s",
            route_key,
            exc.status_code,
            exc.code,
        )
        return _response(exc.status_code, {"code": exc.code, "message": exc.message})
    except Exception:
        logger.exception("Unhandled API error")
        return _response(
            500, {"code": "internal_error", "message": "Something went wrong"}
        )
