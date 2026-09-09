from __future__ import annotations

import asyncio
import contextvars
import importlib
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import nest_asyncio

from frogbot_runtime.agentcore_adapters import PersistentAgentCoreBrowser


async def invoke(browser, action):
    events = [
        event
        async for event in browser.browser.stream(
            {
                "name": "browser",
                "toolUseId": "execution-test",
                "input": {"browser_input": {"action": action}},
            },
            {},
        )
    ]
    return events[-1].tool_result


def test_browser_startup_does_not_patch_or_block_the_server_loop(monkeypatch):
    started, release = threading.Event(), threading.Event()
    stops = AsyncMock()
    original_run = asyncio.run
    correlation = contextvars.ContextVar("browser_test_correlation")
    driver_threads = []

    async def start():
        driver_threads.append(threading.get_ident())
        assert correlation.get() == "test-run"
        started.set()
        async with asyncio.timeout(3):
            while not release.is_set():
                await asyncio.sleep(0.001)
        return SimpleNamespace(stop=stops)

    def forbidden_patch(*_args, **_kwargs):
        raise AssertionError("Browser must not globally patch asyncio")

    module = importlib.import_module("strands_tools.browser.browser")
    monkeypatch.setattr(
        module, "async_playwright", lambda: SimpleNamespace(start=start)
    )
    monkeypatch.setattr(nest_asyncio, "apply", forbidden_patch)

    async def run():
        correlation.set("test-run")
        server_loop = asyncio.get_running_loop()
        server_thread = threading.get_ident()
        browser = PersistentAgentCoreBrowser(
            session_name="execution-test", region="us-east-1"
        )
        assert asyncio.get_event_loop() is server_loop
        monkeypatch.setattr(
            browser,
            "_async_init_session",
            AsyncMock(
                return_value={"status": "success", "content": [{"text": "ready"}]}
            ),
        )
        action = {
            "type": "init_session",
            "session_name": "execution-test",
            "description": "Test startup",
        }
        try:
            task = asyncio.create_task(invoke(browser, action))
            assert await asyncio.to_thread(started.wait, 1)
            # The main loop and AnyIO (used by ASGI health checks) remain usable
            # while browser startup is still awaiting its own I/O.
            assert not task.done()
            assert await anyio.to_thread.run_sync(lambda: "healthy") == "healthy"
            assert asyncio.run is original_run
            assert asyncio.get_running_loop() is server_loop
            release.set()
            assert (await task)["status"] == "success"
            assert (
                await invoke(
                    browser, {"type": "close", "session_name": "execution-test"}
                )
            )["status"] == "success"
            assert not browser._started
            assert (await invoke(browser, action))["status"] == "success"
            assert len(driver_threads) == 2
            assert len(set(driver_threads)) == 1
            assert driver_threads[0] != server_thread
        finally:
            release.set()
            await server_loop.run_in_executor(browser._executor, browser._dispose)
            browser._executor.shutdown(wait=True)
        assert stops.await_count == 2

    asyncio.run(run())


def test_parallel_browser_actions_are_serialized(monkeypatch):
    browser = PersistentAgentCoreBrowser(
        session_name="execution-test", region="us-east-1"
    )
    monkeypatch.setattr(browser, "_start", lambda: None)
    active = 0
    maximum = 0

    async def action(_action):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"status": "success", "content": [{"text": "ready"}]}

    monkeypatch.setattr(browser, "_async_init_session", action)

    async def run():
        request = {
            "type": "init_session",
            "session_name": "execution-test",
            "description": "Test ordering",
        }
        results = await asyncio.gather(
            invoke(browser, request), invoke(browser, request)
        )
        assert all(result["status"] == "success" for result in results)

    try:
        asyncio.run(run())
        assert maximum == 1
    finally:
        browser._executor.submit(browser._dispose).result(timeout=5)
        browser._executor.shutdown(wait=True)
