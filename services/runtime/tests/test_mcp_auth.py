from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from heytim_runtime import mcp_auth
from heytim_runtime.mcp_auth import AccessToken, RefreshingBearerAuth

ENDPOINT = "https://mcp.example.com/tools"


@pytest.fixture
def clock(monkeypatch):
    seconds = [1_000.0]
    monkeypatch.setattr(mcp_auth, "time", SimpleNamespace(
        monotonic=lambda: seconds[0], time=lambda: seconds[0],
    ))
    return seconds


def test_token_lifetimes_refresh_early_without_extending_provider_expiry(clock):
    assert AccessToken.expiring("private", 3_600).refresh_at == 4_540
    assert AccessToken.expiring("private", 10).refresh_at == 1_009
    assert AccessToken.expiring("private").refresh_at == 1_000
    assert AccessToken.until("private", "1970-01-01T00:18:20Z").refresh_at == 1_090
    with pytest.raises(ValueError, match="lifetime"):
        AccessToken.until("private", "1970-01-01T00:00:00Z")
    assert "private" not in repr(AccessToken.expiring("private", 10))
    with pytest.raises(ValueError, match="timezone"):
        AccessToken.until("private", "2026-09-26T00:00:00")


@pytest.mark.parametrize("lifetime", [True, 0, -1, float("nan"), float("inf"), "3600"])
def test_invalid_expiry_cannot_create_a_permanent_cached_token(lifetime):
    with pytest.raises(ValueError, match="lifetime"):
        AccessToken.expiring("private", lifetime)


def test_connection_threads_share_one_refresh_and_keep_accounts_isolated(clock):
    loads = []

    def load():
        loads.append(clock[0])
        return AccessToken.expiring(f"private-{len(loads)}", 3_600)

    auth = RefreshingBearerAuth(load, [ENDPOINT])
    other = RefreshingBearerAuth(lambda: AccessToken.expiring("other", 3_600), [ENDPOINT])
    clock[0] += 3_600
    sent = []

    async def request(credential):
        async with httpx.AsyncClient(
            auth=credential, transport=httpx.MockTransport(
                lambda req: sent.append(req.headers["authorization"]) or httpx.Response(200)
            ),
        ) as client:
            await client.post(ENDPOINT)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: asyncio.run(request(auth)), range(8)))
    asyncio.run(request(other))
    assert len(loads) == 2  # Initial token and one shared renewal.
    assert sent == ["Bearer private-2"] * 8 + ["Bearer other"]


def test_slow_refresh_does_not_block_the_agent_event_loop(clock):
    started, release = threading.Event(), threading.Event()
    loads = []

    def load():
        if loads:
            started.set()
            assert release.wait(2)
        loads.append(1)
        return AccessToken.expiring("private", 10)

    auth = RefreshingBearerAuth(load, [ENDPOINT])
    clock[0] += 10

    async def run():
        async with httpx.AsyncClient(
            auth=auth, transport=httpx.MockTransport(lambda _: httpx.Response(200)),
        ) as client:
            task = asyncio.create_task(client.post(ENDPOINT))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                # The HTTP task is waiting on refresh, but the loop still runs.
                assert not task.done()
            finally:
                release.set()
            assert (await task).status_code == 200

    asyncio.run(run())


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_failed_action_is_never_replayed_by_authentication(clock, status):
    loads, sent = [], []

    def load():
        loads.append(1)
        return AccessToken.expiring(f"private-{len(loads)}", 3_600)

    auth = RefreshingBearerAuth(load, [ENDPOINT])

    async def run():
        async with httpx.AsyncClient(
            auth=auth, transport=httpx.MockTransport(
                lambda req: sent.append(req.headers["authorization"]) or httpx.Response(status)
            ),
        ) as client:
            assert (await client.post(ENDPOINT)).status_code == status
            assert sent == ["Bearer private-1"]
            assert len(loads) == 1
            # A separate caller dispatch can refresh a rejected credential.
            await client.post(ENDPOINT)

    asyncio.run(run())
    assert len(sent) == 2
    assert len(loads) == (2 if status == 401 else 1)


def test_transport_timeout_is_not_replayed(clock):
    sent = []
    auth = RefreshingBearerAuth(lambda: AccessToken.expiring("private", 3_600), [ENDPOINT])

    def dispatch(request):
        sent.append(request)
        raise httpx.ReadTimeout("Unknown action outcome")

    async def run():
        async with httpx.AsyncClient(auth=auth, transport=httpx.MockTransport(dispatch)) as client:
            with pytest.raises(httpx.ReadTimeout):
                await client.post(ENDPOINT)

    asyncio.run(run())
    assert len(sent) == 1


def test_failed_renewal_stops_before_sending_expired_credential(clock):
    loads, sent = [], []

    def load():
        if loads:
            raise ValueError("Connection was revoked")
        loads.append(1)
        return AccessToken.expiring("private", 10)

    auth = RefreshingBearerAuth(load, [ENDPOINT])
    clock[0] += 10

    async def run():
        async with httpx.AsyncClient(
            auth=auth, transport=httpx.MockTransport(
                lambda req: sent.append(req) or httpx.Response(200)
            ),
        ) as client:
            with pytest.raises(ValueError, match="revoked"):
                await client.post(ENDPOINT)

    asyncio.run(run())
    assert sent == []


@pytest.mark.parametrize("url", ["https://other.example.com/tools", "http://mcp.example.com/tools"])
def test_authentication_is_bound_to_the_connections_https_origins(url, clock):
    auth = RefreshingBearerAuth(lambda: AccessToken.expiring("private", 3_600), [ENDPOINT])

    async def run():
        async with httpx.AsyncClient(auth=auth) as client:
            with pytest.raises(ValueError, match="origin"):
                await client.post(url)

    asyncio.run(run())
