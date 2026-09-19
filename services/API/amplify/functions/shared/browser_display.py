"""Bounded, fixed browser setup commands; never an arbitrary client CDP proxy."""
from __future__ import annotations

import ipaddress
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from .browser_session_aws import BROWSER_IDENTIFIER
from .browser_session_store import BrowserSessionError

VIEWPORTS = {"mobile": {"width": 390, "height": 780}, "desktop": {"width": 1440, "height": 900}}
EXTENSION_ID = "ekdfphibopiegakkjgnbbkjnjlonaheh"


def open_options(body: dict) -> tuple[str | None, str | None]:
    display, url = body.get("display"), body.get("url")
    if display is not None and (not isinstance(display, str) or display not in VIEWPORTS):
        raise BrowserSessionError(400, "display must be mobile or desktop")
    if url is not None:
        if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 for c in url):
            raise BrowserSessionError(400, "Use a valid public website link")
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
            if (parsed.scheme not in {"https", "http"} or not host or parsed.username
                    or parsed.password or "\\" in url or parsed.port not in {None, 80, 443}
                    or host == "localhost" or host.endswith((".localhost", ".local", ".internal"))):
                raise ValueError()
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if "." not in host or host.replace(".", "").isdigit():
                    raise ValueError() from None
            else:
                if not address.is_global:
                    raise ValueError()
        except ValueError:
            raise BrowserSessionError(400, "Use a valid public website link") from None
    return display, url


def extension_configuration() -> list:
    bucket, key = os.getenv("HEYTIM_BROWSER_EXTENSION_BUCKET"), os.getenv("HEYTIM_BROWSER_EXTENSION_KEY")
    return [{"location": {"s3": {"bucket": bucket, "prefix": key}}}] if bucket and key else []


def connect_browser(agentcore, record):
    """Sign only the known AWS endpoint. Never accept an endpoint from the caller."""
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    wheel = str(Path(__file__).resolve().parents[1] / "vendor/websocket_client-1.9.0-py3-none-any.whl")
    if wheel not in sys.path:
        sys.path.insert(0, wheel)
    from websocket import create_connection

    endpoint = agentcore.meta.endpoint_url.rstrip("/")
    url = f"{endpoint}/browser-streams/{BROWSER_IDENTIFIER}/sessions/{quote(record['sessionId'], safe='')}/automation"
    credentials = boto3.Session().get_credentials().get_frozen_credentials()
    request = AWSRequest(method="GET", url=url, headers={"host": urlsplit(url).hostname})
    SigV4Auth(credentials, "bedrock-agentcore", agentcore.meta.region_name).add_auth(request)
    # Let the WebSocket library create the Host/Upgrade headers once. TLS remains verified.
    headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}
    return create_connection(url.replace("https://", "wss://", 1), header=headers,
                             timeout=3, suppress_origin=True, redirect_limit=0)


class BrowserSetup:
    def __init__(self, socket, seconds=9):
        self.socket, self.deadline, self.sequence = socket, time.monotonic() + seconds, 0

    def call(self, method, params=None, session_id=None):
        self.sequence += 1
        request = {"id": self.sequence, "method": method, "params": params or {}}
        if session_id:
            request["sessionId"] = session_id
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Browser setup timed out")
        self.socket.settimeout(min(3, remaining))
        self.socket.send(json.dumps(request))
        while time.monotonic() < self.deadline:
            self.socket.settimeout(min(3, max(0.01, self.deadline - time.monotonic())))
            result = json.loads(self.socket.recv())
            if result.get("id") == self.sequence:
                if result.get("error"):
                    raise RuntimeError("Browser setup command failed")
                return result.get("result", {})
        raise TimeoutError("Browser setup timed out")

    def display(self, display):
        # An extension keeps mobile request headers active AFTER CDP disconnects
        # and AWS disables automation for the human. Emulation alone does not.
        target = self.call("Target.createTarget", {"url": f"chrome-extension://{EXTENSION_ID}/configure.html#{display}", "background": True})["targetId"]
        try:
            session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            while time.monotonic() < self.deadline:
                result = self.call("Runtime.evaluate", {"expression": "document.documentElement.dataset.display", "returnByValue": True}, session)
                value = result.get("result", {}).get("value")
                if value == display:
                    return
                if value == "error":
                    raise RuntimeError("Mobile view could not be configured")
                time.sleep(0.05)
            raise TimeoutError("Browser display setup timed out")
        finally:
            self.call("Target.closeTarget", {"targetId": target})

    def navigate(self, url):
        # Open in the EXISTING default profile, leaving the user's current page
        # and any unfinished form untouched. Do not create an incognito context.
        target = self.call("Target.createTarget", {"url": url})["targetId"]
        self.call("Target.activateTarget", {"targetId": target})


def prepare_browser(agentcore, record, display, url=None):
    socket = connect_browser(agentcore, record)
    try:
        setup = BrowserSetup(socket)
        if record.get("mobileExtension"):
            setup.display(display)
        if url:
            setup.navigate(url)
        pages = setup.call("Target.getTargets").get("targetInfos", [])
        page = next((item for item in pages if item.get("type") == "page"), None)
        if page:
            window = setup.call("Browser.getWindowForTarget", {"targetId": page["targetId"]})
            # Fit the session's real desktop. Viewer dimensions must match its
            # original viewport even where DCV's resize channel is unavailable.
            setup.call("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": "maximized"}})
    finally:
        socket.close(timeout=0.2)
