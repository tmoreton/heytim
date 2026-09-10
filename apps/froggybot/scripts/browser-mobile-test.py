"""Real Chromium extension test, isolated profile and localhost requests only.

Run with the agent-runtime virtualenv; set BROWSER_TEST_EXECUTABLE to an installed
Playwright Chromium if its default executable is unavailable. No AWS calls.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from playwright.async_api import async_playwright

EXTENSION_ID = "ekdfphibopiegakkjgnbbkjnjlonaheh"


class Headers(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(dict(self.headers)).encode())

    def log_message(self, *args):
        pass


async def main():
    extension = Path(__file__).resolve().parents[1] / "amplify/browser-extension"
    functions = extension.parent / "functions"
    sys.path.insert(0, str(functions))
    sys.path.insert(0, str(functions / "vendor/websocket_client-1.9.0-py3-none-any.whl"))
    from shared.browser_display import prepare_browser
    from websocket import create_connection
    server = ThreadingHTTPServer(("127.0.0.1", 0), Headers)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="frogbot-mobile-browser-") as profile:
            async with async_playwright() as p:
                context = await p.chromium.launch_persistent_context(
                    profile, headless=True, channel="chromium",
                    executable_path=os.getenv("BROWSER_TEST_EXECUTABLE"),
                    args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}", "--remote-debugging-port=0"],
                )
                try:
                    port, endpoint = (Path(profile) / "DevToolsActivePort").read_text().splitlines()
                    await context.add_cookies([{"name": "test_session", "value": "kept", "url": f"http://127.0.0.1:{server.server_port}"}])
                    for display in ("mobile", "desktop"):
                        socket = create_connection(f"ws://127.0.0.1:{port}{endpoint}", suppress_origin=True, timeout=3)
                        with patch("shared.browser_display.connect_browser", return_value=socket):
                            await asyncio.to_thread(prepare_browser, None, {"mobileExtension": True}, display,
                                                    f"http://127.0.0.1:{server.server_port}/opened-by-chat")
                        print(f"PASS: production CDP setup opens a link in the same browser ({display}).")
                        # The private setup page is now CLOSED, so emulation
                        # cannot accidentally be kept alive by the controller.
                        for index in range(2):
                            page = await context.new_page()
                            response = await page.goto(f"http://127.0.0.1:{server.server_port}/page-{index}")
                            headers = {key.lower(): value for key, value in (await response.json()).items()}
                            assert ("Mobile" in headers["user-agent"]) == (display == "mobile"), headers
                            assert headers.get("sec-ch-ua-mobile") == ("?1" if display == "mobile" else "?0"), headers
                            assert headers.get("cookie") == "test_session=kept", headers
                            await page.close()
                        print(f"PASS: {display} request identity persists across new pages after setup closes.")
                finally:
                    await context.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


asyncio.run(main())
