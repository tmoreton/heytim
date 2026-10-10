"""Exercise the shipped browser tool against real, disposable local Chromium.

AWS ownership/transport is stubbed; Playwright, CDP and every action are real.
Opt in with HEYTIM_TEST_BROWSER=1 on hosts with Chrome installed.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest

from heytim_runtime import agentcore_adapters

pytestmark = pytest.mark.skipif(
    os.environ.get("HEYTIM_TEST_BROWSER") != "1", reason="Opt-in local Chrome integration"
)


@pytest.fixture
def local_browser(monkeypatch, tmp_path):
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        candidate = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if candidate.exists():
            chrome = str(candidate)
    if not chrome:
        pytest.fail("Install Chrome before running the browser integration gate")

    stop_stream = threading.Event()

    class Site(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"data: fixture\n\n")
                self.wfile.flush()
                stop_stream.wait(60)
                return
            body = ("<!doctype html><title>Browser fixture</title>"
                    f"<h1 id='heading'>{self.path}</h1>"
                    "<label>Name <input id='name'></label>"
                    "<button id='submit' onclick=\"document.querySelector('#result').textContent=document.querySelector('#name').value\">Submit</button>"
                    "<p id='result'>Ready</p><a href='/two' id='next'>Next page</a>"
                    "<div style='height:2000px'></div><p id='bottom'>Bottom</p>"
                    "<script>fetch('/stream').then(r => r.text())</script>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    site = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    thread = threading.Thread(target=site.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    args = [chrome, "--headless", "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking", "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}", f"--user-data-dir={tmp_path / 'chrome'}", "about:blank"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.append("--no-sandbox")
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = None
    try:
        for _ in range(100):
            try:
                with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                    endpoint = json.load(response)["webSocketDebuggerUrl"]
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("Disposable Chrome did not become ready")

        class Transport:
            def __init__(self, **_kwargs):
                pass

            def get_session(self, *_args):
                return {"name": "test-private-session", "status": "READY", "streams": {
                    "automationStream": {"streamStatus": "ENABLED"}}}

            def generate_ws_headers(self):
                return endpoint, {"x-heytim-fixture": "local-only"}

        monkeypatch.setattr(agentcore_adapters, "BrowserClient", Transport)
        browser = agentcore_adapters.PersistentAgentCoreBrowser(
            session_name="test-private-session", region="us-east-1", managed_session={
                "browserIdentifier": "aws.browser.v1", "sessionId": "local-test-session",
                "sessionName": "test-private-session"})
        browser._fixture_navigation_errors = []
        yield browser, f"http://127.0.0.1:{site.server_port}", tmp_path
    finally:
        if browser:
            asyncio.run(browser.aclose())
        process.terminate()
        process.wait(timeout=10)
        stop_stream.set()
        site.shutdown()
        site.server_close()
        thread.join(timeout=5)


async def action(browser, kind, *, expected="success", **fields):
    events = [event async for event in browser.browser.stream({
        "name": "browser", "toolUseId": "local-chromium-test", "input": {
            "browser_input": {"wait_time": 0, "action": {
                "type": kind, "session_name": "model-chosen-session", **fields}}}}, {})]
    result = events[-1].tool_result
    assert result["status"] == expected, (result, browser._fixture_navigation_errors[-3:])
    return result


async def initialize(browser):
    await action(browser, "init_session", description="Local browser regression")
    page = browser.get_session_page(agentcore_adapters.MANAGED_BROWSER_LOCAL_SESSION)
    if getattr(page, "_fixture_monitored", False):
        return
    page._fixture_monitored = True
    for method in ["goto", "go_back", "go_forward", "reload", "wait_for_load_state"]:
        original = getattr(page, method)

        async def monitored(*args, callback=original, **kwargs):
            try:
                return await callback(*args, **kwargs)
            except Exception as error:
                browser._fixture_navigation_errors.append(str(error))
                raise
        setattr(page, method, monitored)


def test_navigation_history_refresh_and_reading(local_browser):
    browser, url, _ = local_browser

    async def run():
        await initialize(browser)
        started = time.monotonic()
        await action(browser, "navigate", url=url + "/one")
        assert time.monotonic() - started < 5, "An active stream must not stall usable page navigation"
        assert "/one" in (await action(browser, "get_text", selector="#heading"))["content"][0]["text"]
        await action(browser, "click", selector="#next")
        assert "/two" in (await action(browser, "get_text", selector="#heading"))["content"][0]["text"]
        await action(browser, "back")
        assert "/one" in (await action(browser, "get_text", selector="#heading"))["content"][0]["text"]
        await action(browser, "forward")
        await action(browser, "refresh")
        assert "/two" in (await action(browser, "get_html", selector="h1"))["content"][0]["text"]
    asyncio.run(run())


def test_forms_keyboard_scroll_screenshot_and_cdp(local_browser):
    browser, url, tmp_path = local_browser

    async def run():
        await initialize(browser)
        await action(browser, "navigate", url=url + "/one")
        await action(browser, "type", selector="#name", text="Synthetic browser test")
        await action(browser, "press_key", key="Tab")
        await action(browser, "press_key", key="Enter")
        assert "Synthetic browser test" in (await action(browser, "get_text", selector="#result"))["content"][0]["text"]
        await action(browser, "evaluate", script="window.scrollTo(0, document.body.scrollHeight)")
        value = await action(browser, "evaluate", script="window.scrollY > 0")
        assert "true" in json.dumps(value).lower()
        await action(browser, "execute_cdp", method="Page.getLayoutMetrics")
        screenshot = tmp_path / "browser.png"
        await action(browser, "screenshot", path=str(screenshot))
        assert screenshot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    asyncio.run(run())


def test_tabs_failure_recovery_and_reconnect_preserve_context(local_browser):
    browser, url, _ = local_browser

    async def run():
        await initialize(browser)
        await action(browser, "navigate", url=url + "/one")
        await action(browser, "type", selector="#name", text="Unfinished form")
        await action(browser, "evaluate", script="localStorage.setItem('test-only', 'kept')")
        tabs = json.loads((await action(browser, "list_tabs"))["content"][0]["text"])
        original = next(iter(tabs))
        await action(browser, "new_tab", tab_id="second")
        await action(browser, "navigate", url=url + "/two")
        await action(browser, "new_tab", tab_id="second", expected="error")
        await action(browser, "switch_tab", tab_id="missing", expected="error")
        await action(browser, "switch_tab", tab_id=original)
        assert "Unfinished form" in json.dumps(await action(browser, "evaluate", script="document.querySelector('#name').value"))
        await action(browser, "close_tab", tab_id="second")
        for _ in range(3):
            await action(browser, "navigate", url="http://127.0.0.1:1/unavailable", expected="error")
            await action(browser, "navigate", url=url + "/one")
        for _ in range(3):
            await action(browser, "close")
            await initialize(browser)
            assert "kept" in json.dumps(await action(browser, "evaluate", script="localStorage.getItem('test-only')"))
    asyncio.run(run())
