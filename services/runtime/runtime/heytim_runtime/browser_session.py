from __future__ import annotations

import hashlib
import re


def managed_browser_from_payload(
    payload: dict, actor_id: str | None, artifact_prefix: str | None
) -> dict | None:
    """Accept only app-issued, private direct-chat browser session references."""
    value = payload.get("browser")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("browser must be an object")
    fields = {"browserIdentifier", "sessionId", "sessionName", "actorId", "botId"}
    if set(value) != fields or any(not isinstance(value[key], str) for key in fields):
        raise ValueError("browser session reference is invalid")
    if payload.get("group") is not None:
        raise ValueError("Private browser logins are only available in direct chats")
    if not actor_id or value["actorId"] != actor_id:
        raise ValueError("browser session does not match the invoking user")
    bot_id = value["botId"]
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", bot_id)
        or not artifact_prefix
        or not artifact_prefix.startswith(f"users/{actor_id}/bots/{bot_id}/artifacts/")
    ):
        raise ValueError("browser session does not match this bot conversation")
    scope_hash = hashlib.sha256(f"{actor_id}:bot:{bot_id}".encode()).hexdigest()
    expected_name = f"heytim-browser-{scope_hash[:48]}"
    if (
        value["browserIdentifier"] != "aws.browser.v1"
        or value["sessionName"] != expected_name
        or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", value["sessionId"])
    ):
        raise ValueError("browser session reference is invalid")
    return {
        key: value[key] for key in ("browserIdentifier", "sessionId", "sessionName")
    }
