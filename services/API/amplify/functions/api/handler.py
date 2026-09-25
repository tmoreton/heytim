from __future__ import annotations

import logging
from typing import Any

from . import authenticated_routes
from .account import _begin_account_deletion
from .billing import stripe_webhook
from .external_oauth import _external_callback
from .finance_connections import _plaid_callback, _quickbooks_callback
from .github_oauth import _github_callback
from .github_webhook import github_issue_webhook
from .google_oauth import _google_callback
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
from .x_oauth import _x_callback

logger = logging.getLogger(__name__)


def _public_route(event: dict, method: str, path: str, params: dict) -> dict | None:
    if method == "POST" and path == "/public/webhooks/github":
        return github_issue_webhook(event)
    if method == "POST" and path == "/public/webhooks/stripe":
        return stripe_webhook(event)
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
        return _google_callback(event.get("queryStringParameters") or {})
    if method == "GET" and path == "/public/oauth/github/callback":
        return _github_callback(event.get("queryStringParameters") or {})
    if method == "GET" and path == "/public/oauth/x/callback":
        return _x_callback(event.get("queryStringParameters") or {})
    if method == "GET" and path == "/public/oauth/provider/callback":
        return _external_callback(event.get("queryStringParameters") or {})
    if method == "GET" and path == "/public/oauth/quickbooks/callback":
        return _quickbooks_callback(event.get("queryStringParameters") or {})
    if method == "GET" and path == "/public/plaid/callback":
        return _plaid_callback(event.get("queryStringParameters") or {})
    return None


def handler(event: dict, _context: Any) -> dict:
    route_key = ""
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
