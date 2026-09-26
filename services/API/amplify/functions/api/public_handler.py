from __future__ import annotations

import logging
from typing import Any

from .billing import stripe_webhook
from .external_oauth import _external_callback
from .finance_connections import _plaid_callback, _quickbooks_callback
from .github_oauth import _github_callback
from .github_webhook import github_issue_webhook
from .google_oauth import _google_callback
from .sharing import _public_invite_preview
from .support import ApiError, _response, catalog
from .x_oauth import _x_callback

logger = logging.getLogger(__name__)


def route_public(event: dict, method: str, path: str, params: dict) -> dict | None:
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
    query = event.get("queryStringParameters") or {}
    if method == "GET" and path == "/public/oauth/google/callback":
        return _google_callback(query)
    if method == "GET" and path == "/public/oauth/github/callback":
        return _github_callback(query)
    if method == "GET" and path == "/public/oauth/x/callback":
        return _x_callback(query)
    if method == "GET" and path == "/public/oauth/provider/callback":
        return _external_callback(query)
    if method == "GET" and path == "/public/oauth/quickbooks/callback":
        return _quickbooks_callback(query)
    if method == "GET" and path == "/public/plaid/callback":
        return _plaid_callback(query)
    return None


def handler(event: dict, _context: Any) -> dict:
    route_key = ""
    try:
        request_context = event.get("requestContext", {})
        method = request_context.get("http", {}).get("method", "")
        route_key = request_context.get("routeKey", "")
        path = event.get("rawPath", "")
        params = event.get("pathParameters") or {}
        response = route_public(event, method, path, params)
        if response is None:
            raise ApiError(404, "Public route not found")
        return response
    except ApiError as exc:
        logger.warning(
            "Public API request rejected route=%s status=%s code=%s",
            route_key,
            exc.status_code,
            exc.code,
        )
        return _response(exc.status_code, {"code": exc.code, "message": exc.message})
    except Exception:
        logger.exception("Unhandled public API error")
        return _response(
            500, {"code": "internal_error", "message": "Something went wrong"}
        )
