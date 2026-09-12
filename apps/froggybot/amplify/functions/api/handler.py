from __future__ import annotations

import logging
from typing import Any

from . import authenticated_routes
from .account import _begin_account_deletion
from .google_oauth import _gmail_callback
from .sharing import _public_invite_preview
from .support import (
    ApiError,
    _display_name,
    _ensure_account_active,
    _response,
    _user_id,
    _username,
    catalog,
)

logger = logging.getLogger(__name__)


def _public_route(event: dict, method: str, path: str, params: dict) -> dict | None:
    if method == "GET" and path.startswith("/public/invites/"):
        return _response(
            200,
            _public_invite_preview(params.get("kind", ""), params.get("token", "")),
        )
    if method == "GET" and path == "/public/catalog":
        response = _response(200, catalog.public_catalog())
        response["headers"]["cache-control"] = (
            "public, max-age=60, stale-while-revalidate=300"
        )
        return response
    if method == "GET" and path == "/public/oauth/google/callback":
        return _gmail_callback(event.get("queryStringParameters") or {})
    return None


def handler(event: dict, _context: Any) -> dict:
    try:
        request_context = event.get("requestContext", {})
        method = request_context.get("http", {}).get("method", "")
        route_key = request_context.get("routeKey", "")
        path = event.get("rawPath", "")
        params = event.get("pathParameters") or {}

        public_response = _public_route(event, method, path, params)
        if public_response is not None:
            return public_response

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
        return _response(
            exc.status_code, {"code": exc.code, "message": exc.message}
        )
    except Exception:
        logger.exception("Unhandled API error")
        return _response(
            500, {"code": "internal_error", "message": "Something went wrong"}
        )
