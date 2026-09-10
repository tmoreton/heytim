"""Authenticated direct-chat browser endpoints. No token extraction or storage."""
from __future__ import annotations

from shared.browser_display import open_options
from shared.browser_session_aws import browser_clients
from shared.browser_session_store import BrowserSessionError, direct_only, validate_id
from shared.browser_sessions import BrowserSessionService

from .direct_chat import _claim_send_lease, _release_send_lease, _send_message
from .support import ApiError, _body, _response, catalog, table


def browser_session_route(user_id: str, _display_name: str, method: str,
                          path: str, params: dict, event: dict) -> dict:
    try:
        bot_id = validate_id(params.get("botId"), "botId")
        if set(params) != {"botId"}:
            raise BrowserSessionError(400, "Unexpected browser route parameters")
        query = event.get("queryStringParameters") or {}
        if not isinstance(query, dict) or set(query) - {"groupId"}:
            raise BrowserSessionError(400, "Unexpected browser query parameters")
        body = _body(event)
        action = path.rsplit("/", 1)[-1]
        allowed = {"groupId", "rememberLogin"} if action == "resume" else {"groupId"}
        if action == "open":
            allowed |= {"url", "display"}
        if method != "POST":
            allowed = set()
        if set(body) - allowed or (method == "POST" and query):
            raise BrowserSessionError(400, "Unexpected browser request fields")
        direct_only(body.get("groupId") if method == "POST" else query.get("groupId"))
        if action == "resume" and not isinstance(body.get("rememberLogin"), bool):
            raise BrowserSessionError(400, "rememberLogin must be a boolean")
        agentcore, control = browser_clients()
        service = BrowserSessionService(table, agentcore, user_id, bot_id,
                                        control=control, catalog=catalog)
        if method == "GET" and action == "browser":
            value = service.get()
        elif method == "POST" and action == "open":
            display, url = open_options(body)
            # Use the same lease as _send_message to exclude send/open races.
            service.store.authorize()
            lease = _claim_send_lease(user_id, bot_id)
            try:
                value = service.open(display=display, url=url)
            finally:
                _release_send_lease(user_id, bot_id, lease)
        elif method == "POST" and action == "resume":
            value = service.resume(body["rememberLogin"],
                                   lambda text: _send_message(user_id, bot_id, {"text": text}))
        elif method == "POST" and action == "close":
            value = service.close()
        elif method == "DELETE" and action == "profile":
            value = service.close(forget=True)
        else:
            raise BrowserSessionError(404, "Browser route not found")
        response = _response(200, value)
        response["headers"].update({"cache-control": "no-store", "referrer-policy": "no-referrer"})
        return response
    except BrowserSessionError as exc:
        raise ApiError(exc.status_code, exc.message) from None
    except ApiError:
        raise
    except Exception:  # noqa: BLE001 - sanitize all secret-bearing SDK failures
        # Do not send SDK exception text (or signed endpoints) to API logs/clients.
        raise ApiError(503, "Browser service is temporarily unavailable") from None
