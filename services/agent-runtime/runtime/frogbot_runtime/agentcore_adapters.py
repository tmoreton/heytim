from __future__ import annotations

import asyncio
import contextvars
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from bedrock_agentcore.tools.browser_client import BrowserClient
from bedrock_agentcore.tools.code_interpreter_client import (
    CodeInterpreter as CodeInterpreterClient,
)
from strands import tool
from strands_tools.browser import AgentCoreBrowser
from strands_tools.code_interpreter import AgentCoreCodeInterpreter

from .background_work import BackgroundWorkTracker, background_command_tool
from .browser_input import CompatibleBrowserInput
from .code_interpreter_input import CompatibleCodeInterpreterInput

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MANAGED_BROWSER_LOCAL_SESSION = "frogbot-private-browser"
MANAGED_BROWSER_GUIDANCE = (
    " This is the bot's private in-app browser, not the user's desktop browser. "
    "It supports one automation connection per run: call init_session once, reuse "
    "its sessionName for every site, and open tabs instead of another session. If a "
    "site requires sign-in or human control, ask the user to open the bot browser, "
    "complete it there, and resume the bot. Never request passwords, cookies, or "
    "session tokens in chat or bypass the block. A saved login does not authorize a "
    "new external action."
)


class PersistentAgentCoreBrowser(AgentCoreBrowser):
    """Reconnect a conversation to its active AgentCore browser session."""

    def __init__(
        self, session_name: str, managed_session: dict | None = None, **kwargs: Any
    ):
        # The upstream constructor changes the calling thread's default loop.
        # Keep that change out of the ASGI server and its background agent tasks.
        try:
            previous_loop = asyncio.get_event_loop()
        except RuntimeError:
            previous_loop = None
        try:
            super().__init__(**kwargs)
        finally:
            asyncio.set_event_loop(previous_loop)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self._dispose_lock = Lock()
        self._disposed = False
        self.session_name = session_name
        self.managed_session = managed_session

    @tool(
        name="browser",
        description=(
            AgentCoreBrowser.browser.tool_spec["description"]
            + MANAGED_BROWSER_GUIDANCE
        ),
    )
    async def browser(self, browser_input: CompatibleBrowserInput) -> dict[str, Any]:
        """Run a validated browser action with provider-compatible input decoding.

        Args:
            browser_input: Structured action object, not a quoted JSON string.
        """
        validated = self._managed_browser_input(
            CompatibleBrowserInput.model_validate(browser_input)
        )
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, contextvars.copy_context().run, super().browser, validated
        )

    def _managed_browser_input(
        self, browser_input: CompatibleBrowserInput
    ) -> CompatibleBrowserInput:
        """Map every managed action to one local handle for the remote browser."""
        if not self.managed_session:
            return browser_input
        action = browser_input.action
        if not hasattr(action, "session_name"):
            return browser_input
        return browser_input.model_copy(
            update={
                "action": action.model_copy(
                    update={"session_name": MANAGED_BROWSER_LOCAL_SESSION}
                )
            }
        )

    def _execute_async(self, action_coro) -> Any:
        # Every action runs on the single browser worker. Never apply the upstream
        # nest_asyncio global patch to the agent server's already-running loop.
        return self._loop.run_until_complete(action_coro)

    def close(self, action) -> dict[str, Any]:
        result = super().close(action)
        self._started = False
        if self.managed_session and result.get("status") == "success":
            result["content"] = [
                {
                    "text": (
                        "Browser connection released. The app keeps your private session "
                        "available until you disconnect it or it expires."
                    )
                }
            ]
        return result

    async def _async_cleanup(self) -> None:
        if not self.managed_session:
            await super()._async_cleanup()
            return
        # The app owns this session. Disconnect the driver without closing the
        # user's tabs, clearing their login, or terminating their remote browser.
        if self._playwright:
            await self._playwright.stop()
        self._playwright = None
        self._sessions.clear()

    async def _async_init_session(self, action) -> dict[str, Any]:
        if not self.managed_session:
            return await super()._async_init_session(action)
        action = action.model_copy(
            update={"session_name": MANAGED_BROWSER_LOCAL_SESSION}
        )
        existing = self._sessions.get(MANAGED_BROWSER_LOCAL_SESSION)
        if existing:
            return {
                "status": "success",
                "content": [
                    {
                        "json": {
                            "sessionName": MANAGED_BROWSER_LOCAL_SESSION,
                            "description": existing.description,
                            "reused": True,
                        }
                    }
                ],
            }
        return await super()._async_init_session(action)

    async def _setup_session_from_browser(self, browser_or_context):
        if not self.managed_session:
            return await super()._setup_session_from_browser(browser_or_context)
        if not browser_or_context.contexts:
            raise ValueError("The private browser has no active browser context")
        context = browser_or_context.contexts[0]
        page = context.pages[-1] if context.pages else await context.new_page()
        return browser_or_context, context, page

    def close_platform(self) -> None:
        super().close_platform()
        self._client_dict.clear()

    def _dispose(self) -> None:
        with self._dispose_lock:
            if self._disposed:
                return
            try:
                self._cleanup()
            finally:
                if not self._loop.is_closed():
                    self._loop.close()
                self._disposed = True

    async def aclose(self) -> None:
        """Release the local automation connection before the turn returns."""
        if self._disposed:
            return
        try:
            await asyncio.get_running_loop().run_in_executor(
                self._executor, self._dispose
            )
        finally:
            self._executor.shutdown(wait=True, cancel_futures=True)

    def __del__(self):
        # Cleanup must use the same worker as Playwright, never the server loop.
        try:
            self._executor.submit(self._dispose)
            self._executor.shutdown(wait=False)
        except AttributeError, RuntimeError:
            pass  # Partial construction or interpreter shutdown.

    def _ready_sessions(self, client: BrowserClient) -> list[dict]:
        items = []
        next_token = None
        while True:
            response = client.list_sessions(
                browser_id=self.identifier,
                status="READY",
                max_results=100,
                next_token=next_token,
            )
            items.extend(response.get("items", []))
            next_token = response.get("nextToken")
            if not isinstance(next_token, str) or not next_token:
                return items

    async def create_browser_session(self):
        if not self._playwright:
            raise RuntimeError("Playwright not initialized")
        client = BrowserClient(region=self.region, integration_source="strands")
        if self.managed_session:
            session = self.managed_session
            info = await asyncio.to_thread(
                client.get_session, session["browserIdentifier"], session["sessionId"]
            )
            if info.get("name") != session["sessionName"]:
                raise ValueError("Browser session ownership does not match this bot")
            if info.get("status") != "READY":
                raise ValueError(
                    "Browser session expired. Open bot browser to reconnect."
                )
            stream = info.get("streams", {}).get("automationStream", {})
            if stream.get("streamStatus") != "ENABLED":
                raise ValueError("The user controls this browser. Wait for Resume bot.")
            client.identifier = session["browserIdentifier"]
            client.session_id = session["sessionId"]
            cdp_url, cdp_headers = client.generate_ws_headers()
            return await self._playwright.chromium.connect_over_cdp(
                endpoint_url=cdp_url, headers=cdp_headers
            )
        sessions = await asyncio.to_thread(self._ready_sessions, client)
        existing = next(
            (item for item in sessions if item.get("name") == self.session_name),
            None,
        )
        if existing:
            client.identifier = existing["browserIdentifier"]
            client.session_id = existing["sessionId"]
        else:
            await asyncio.to_thread(
                client.start,
                identifier=self.identifier,
                name=self.session_name,
                session_timeout_seconds=self.session_timeout,
            )
        cdp_url, cdp_headers = client.generate_ws_headers()
        self._client_dict[client.session_id] = client
        return await self._playwright.chromium.connect_over_cdp(
            endpoint_url=cdp_url,
            headers=cdp_headers,
        )


@dataclass
class _CodeSession:
    session_id: str
    description: str
    client: CodeInterpreterClient


class PersistentAgentCoreCodeInterpreter(AgentCoreCodeInterpreter):
    """Reconnect a conversation after the runtime process has restarted."""

    @tool(
        name="code_interpreter",
        description=AgentCoreCodeInterpreter.code_interpreter.tool_spec["description"],
    )
    def code_interpreter(
        self, code_interpreter_input: CompatibleCodeInterpreterInput
    ) -> dict[str, Any]:
        """Run a validated code action with provider-compatible input decoding.

        Args:
            code_interpreter_input: Structured action object, not quoted JSON.
        """
        validated = CompatibleCodeInterpreterInput.model_validate(
            code_interpreter_input
        )
        return super().code_interpreter(code_interpreter_input=validated)

    def _ready_sessions(self, client: CodeInterpreterClient) -> list[dict]:
        items = []
        next_token = None
        while True:
            response = client.list_sessions(
                interpreter_id=self.identifier,
                status="READY",
                max_results=100,
                next_token=next_token,
            )
            items.extend(response.get("items", []))
            next_token = response.get("nextToken")
            if not isinstance(next_token, str) or not next_token:
                return items

    def _ensure_session(
        self, session_name: str | None
    ) -> tuple[str, dict[str, Any] | None]:
        target_session = session_name or self.default_session
        if target_session in self._sessions:
            return target_session, None

        client = CodeInterpreterClient(region=self.region, session=self.boto_session)
        existing = next(
            (
                item
                for item in self._ready_sessions(client)
                if item.get("name") == target_session
            ),
            None,
        )
        if existing:
            identifier = existing.get("codeInterpreterIdentifier")
            session_id = existing.get("sessionId")
            if not isinstance(identifier, str) or not isinstance(session_id, str):
                raise RuntimeError("AgentCore returned an invalid code session")
            client.identifier = identifier
            client.session_id = session_id
            self._sessions[target_session] = _CodeSession(
                session_id=session_id,
                description="Reconnected by conversation name",
                client=client,
            )
            return target_session, None

        return super()._ensure_session(target_session)


def _prepare_playwright_driver() -> None:
    import playwright

    source = Path(playwright.__file__).resolve().parent / "driver" / "node"
    if not source.is_file():
        raise RuntimeError("Playwright driver is missing")
    if not os.access(source, os.X_OK):
        try:
            source.chmod(source.stat().st_mode | 0o111)
        except OSError:
            target = Path(tempfile.gettempdir()) / "frogbot-playwright-node"
            if not target.is_file() or target.stat().st_size != source.stat().st_size:
                shutil.copyfile(source, target)
            target.chmod(0o700)
            source = target
    if not os.access(source, os.X_OK):
        raise RuntimeError("Playwright driver is not executable")
    os.environ["PLAYWRIGHT_NODEJS_PATH"] = str(source)


def agentcore_tools(
    bindings: list[dict],
    session_id: str,
    background_work: BackgroundWorkTracker,
    *,
    allow_background_work: bool,
    managed_browser: dict | None = None,
) -> tuple[
    list[Any],
    PersistentAgentCoreCodeInterpreter | None,
    PersistentAgentCoreBrowser | None,
]:
    tools = []
    code_interpreter = None
    browser = None
    names = {item["name"] for item in bindings if item["kind"] == "agentcore"}
    if "code_interpreter" in names:
        interpreter = PersistentAgentCoreCodeInterpreter(
            region=AWS_REGION,
            session_name=f"frogbot-{session_id}",
            session_timeout_seconds=28800,
        )
        tools.append(interpreter.code_interpreter)
        if allow_background_work:
            tools.append(background_command_tool(interpreter, background_work))
        code_interpreter = interpreter
    if "browser" in names:
        _prepare_playwright_driver()
        browser = PersistentAgentCoreBrowser(
            region=AWS_REGION,
            session_name=f"frogbot-{session_id}",
            session_timeout=28800,
            managed_session=managed_browser,
        )
        tools.append(browser.browser)
    return tools, code_interpreter, browser
