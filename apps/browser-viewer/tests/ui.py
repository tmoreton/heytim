"""Headless UI checks for the viewer; AWS is replaced only at the SDK boundary."""
import os
import socket
import subprocess
import time
import unittest
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = os.environ.get("HEYTIM_BROWSER_SCREENSHOTS")


class BrowserViewerUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        cls.url = f"http://127.0.0.1:{port}/browser-viewer/"
        cls.server = subprocess.Popen(
            ["npm", "exec", "--", "vite", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                with urlopen(cls.url, timeout=1):
                    break
            except OSError:
                if cls.server.poll() is not None:
                    raise RuntimeError("Local viewer server exited") from None
                time.sleep(0.1)
        else:
            cls.server.terminate()
            raise RuntimeError("Local viewer server did not become ready")
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)

    def setUp(self):
        self.page = self.browser.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.url + "tests/fixture.html")
        expect(self.page.locator('[data-browser-phase="connecting"]')).to_be_visible()

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.page.close()

    def drive(self, action):
        self.page.evaluate("window.fixture." + action)

    def ready(self):
        self.drive("authenticate()")
        expect(self.page.get_by_role("button", name="Remote action")).to_be_attached()
        expect(self.page.get_by_role("status")).to_have_text("Connecting to your secure browser…")
        self.drive("frame()")
        expect(self.page.locator('[data-browser-phase="connected"]')).to_be_visible()

    def test_startup_waits_for_actual_frame(self):
        self.ready()
        expect(self.page.get_by_role("status")).to_have_text("Live browser connected")

    def test_auth_failure_and_reconnect_control(self):
        self.drive("fail()")
        expect(self.page.get_by_role("alert")).to_contain_text("Couldn’t connect")
        button = self.page.get_by_role("button", name="Reconnect Live View")
        self.assertGreaterEqual(button.bounding_box()["height"], 44)
        button.focus()
        self.assertEqual(button.evaluate("el => getComputedStyle(el).outlineStyle"), "solid")
        self.page.keyboard.press("Enter")
        self.assertEqual(self.page.evaluate("window.fixture.metrics().bridge.at(-1)"), {"action": "reconnect"})
        self.drive("render()")
        expect(self.page.get_by_role("alert")).to_have_count(0)
        self.ready()

    def test_disconnect_explains_recovery(self):
        self.ready()
        self.drive("disconnect()")
        expect(self.page.get_by_role("alert")).to_contain_text("The live browser disconnected")
        expect(self.page.get_by_role("button", name="Reconnect Live View")).to_be_visible()
        self.assertEqual(self.page.evaluate("window.fixture.metrics().disconnects"), 1)

    def test_dark_mobile_error_and_reduced_motion(self):
        self.page.set_viewport_size({"width": 320, "height": 568})
        self.page.emulate_media(color_scheme="dark", reduced_motion="reduce")
        self.assertEqual(self.page.locator(".spinner").evaluate("el => getComputedStyle(el).animationName"), "none")
        self.drive("fail()")
        expect(self.page.get_by_role("alert")).to_be_visible()
        self.assertEqual(self.page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor"), "rgb(18, 18, 18)")
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
        if ARTIFACTS:
            self.page.screenshot(path=str(Path(ARTIFACTS) / "viewer-mobile-dark-recovery.png"))

    def test_phone_and_desktop_fitting_and_input(self):
        for width, height in [(320, 568), (390, 780), (768, 1024), (1280, 800), (1920, 1080)]:
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({"width": width, "height": height})
                self.drive(f"render({390 if width < 500 else 1440}, {780 if width < 500 else 900})")
                expect(self.page.locator('[data-browser-phase="connecting"]')).to_be_visible()
                self.ready()
                display = self.page.get_by_role("application").bounding_box()
                self.assertGreater(display["width"], 0)
                self.assertGreaterEqual(display["x"], -1)
                self.assertGreaterEqual(display["y"], -1)
                self.assertLessEqual(display["x"] + display["width"], width + 1)
                self.assertLessEqual(display["y"] + display["height"], height + 1)
                self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth || document.documentElement.scrollHeight > innerHeight"))
                before = self.page.evaluate("window.fixture.metrics().clicks")
                self.page.get_by_role("button", name="Remote action").click()
                self.assertEqual(self.page.evaluate("window.fixture.metrics().clicks"), before + 1)
                self.page.get_by_role("textbox", name="Remote input").fill("Keyboard input works")
                expect(self.page.get_by_role("textbox", name="Remote input")).to_have_value("Keyboard input works")
                if ARTIFACTS:
                    Path(ARTIFACTS).mkdir(parents=True, exist_ok=True)
                    self.page.screenshot(path=str(Path(ARTIFACTS) / f"viewer-{width}x{height}.png"))

    def test_ten_reconnects_and_close_release_every_viewer(self):
        for _ in range(10):
            self.ready()
            self.drive("render()")
            expect(self.page.locator('[data-browser-phase="connecting"]')).to_be_visible()
        self.drive("close()")
        expect(self.page.get_by_role("application")).to_have_count(0)
        metrics = self.page.evaluate("window.fixture.metrics()")
        self.assertEqual(metrics["connects"], 10)
        self.assertEqual(metrics["disconnects"], 10)

    def test_invalid_capability_fails_without_network_connection(self):
        self.page.goto(self.url)
        self.page.evaluate("window.heytimSetBrowserSession('https://untrusted.example/stream', 390, 780)")
        expect(self.page.get_by_role("alert")).to_contain_text("could not be opened")
        expect(self.page.get_by_role("application")).to_have_count(0)

    def test_early_injection_and_reconnect_with_identical_capability(self):
        self.page.goto(self.url + "tests/receiver.html")
        expect(self.page.locator('[data-browser-phase="connected"]')).to_be_visible()
        self.assertEqual(self.page.evaluate("window.receiver.metrics().connects"), 1)
        for count in range(2, 12):
            self.page.evaluate("window.receiver.inject()")
            self.page.wait_for_function("count => window.receiver.metrics().connects === count", arg=count)
            self.assertEqual(self.page.evaluate("window.receiver.metrics().disconnects"), count - 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
