from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from frogbot_runtime import agentcore_adapters
from frogbot_runtime.browser_session import managed_browser_from_payload

ACTOR = "a" * 64
BOT = "github-engineer"
PREFIX = f"users/{ACTOR}/bots/{BOT}/artifacts/12345678-1234-1234-1234-123456789012"


def reference():
    return {
        "browserIdentifier": "aws.browser.v1",
        "sessionId": "01M240KWTNDNGN7BD73X0226MY",
        "sessionName": "frogbot-browser-"
        + hashlib.sha256(f"{ACTOR}:bot:{BOT}".encode()).hexdigest()[:48],
        "actorId": ACTOR,
        "botId": BOT,
    }


def test_managed_reference_is_bound_to_actor_and_bot_artifact_scope():
    expected = reference()
    result = managed_browser_from_payload({"browser": expected}, ACTOR, PREFIX)
    assert result == {
        key: expected[key] for key in ("browserIdentifier", "sessionId", "sessionName")
    }
    assert managed_browser_from_payload({}, ACTOR, PREFIX) is None


@pytest.mark.parametrize(
    "mutation",
    [
        {"actorId": "b" * 64},
        {"botId": "different-bot"},
        {"browserIdentifier": "someone-elses-browser"},
        {"sessionName": "another-session"},
        {"profileIdentifier": "not-allowed-in-runtime"},
        {"liveViewUrl": "secret-url"},
        {"sessionId": "bad"},
        {"sessionId": 42},
    ],
)
def test_invalid_managed_reference_fails_closed(mutation):
    with pytest.raises(ValueError):
        managed_browser_from_payload(
            {"browser": {**reference(), **mutation}}, ACTOR, PREFIX
        )


def test_private_browser_is_never_accepted_in_a_group():
    with pytest.raises(ValueError, match="direct chats"):
        managed_browser_from_payload(
            {"browser": reference(), "group": {}}, ACTOR, PREFIX
        )


@pytest.mark.parametrize("failure", [None, "ownership", "expired", "human-control"])
def test_managed_browser_verifies_live_ownership_and_control(monkeypatch, failure):
    ref = reference()
    managed = managed_browser_from_payload({"browser": ref}, ACTOR, PREFIX)
    client = MagicMock()
    client.get_session.return_value = {
        "name": "someone-else" if failure == "ownership" else ref["sessionName"],
        "status": "TERMINATED" if failure == "expired" else "READY",
        "streams": {
            "automationStream": {
                "streamStatus": "DISABLED" if failure == "human-control" else "ENABLED"
            }
        },
    }
    client.generate_ws_headers.return_value = ("wss://browser.example", {})
    monkeypatch.setattr(agentcore_adapters, "BrowserClient", lambda **_kwargs: client)
    browser = agentcore_adapters.PersistentAgentCoreBrowser(
        session_name="run", managed_session=managed, region="us-east-1"
    )
    chromium = SimpleNamespace(connect_over_cdp=AsyncMock(return_value="connected"))
    browser._playwright = SimpleNamespace(chromium=chromium)
    try:
        if failure:
            with pytest.raises(ValueError):
                asyncio.run(browser.create_browser_session())
            chromium.connect_over_cdp.assert_not_awaited()
        else:
            assert asyncio.run(browser.create_browser_session()) == "connected"
        client.list_sessions.assert_not_called()
        client.start.assert_not_called()
        client.stop.assert_not_called()
    finally:
        browser._executor.submit(browser._dispose).result(timeout=5)
        browser._executor.shutdown(wait=True)


def test_managed_cleanup_preserves_remote_tabs_and_login():
    browser = agentcore_adapters.PersistentAgentCoreBrowser(
        session_name="run", managed_session=reference(), region="us-east-1"
    )
    page = object()
    context = SimpleNamespace(
        pages=[object(), page], new_page=AsyncMock(), close=AsyncMock()
    )
    remote = SimpleNamespace(contexts=[context], close=AsyncMock())
    stop = AsyncMock()
    browser._playwright = SimpleNamespace(stop=stop)
    browser._sessions["local-session"] = SimpleNamespace(close=AsyncMock())

    async def run():
        assert await browser._setup_session_from_browser(remote) == (
            remote,
            context,
            page,
        )
        await browser._async_cleanup()

    try:
        asyncio.run(run())
        stop.assert_awaited_once()
        context.new_page.assert_not_awaited()
        context.close.assert_not_awaited()
        remote.close.assert_not_awaited()
        assert not browser._sessions
    finally:
        browser._executor.submit(browser._dispose).result(timeout=5)
        browser._executor.shutdown(wait=True)
