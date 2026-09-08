from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bedrock_agentcore.tools.browser_client import BrowserClient
from bedrock_agentcore.tools.code_interpreter_client import (
    CodeInterpreter as CodeInterpreterClient,
)
from strands_tools.browser import AgentCoreBrowser
from strands_tools.code_interpreter import AgentCoreCodeInterpreter

from .background_work import BackgroundWorkTracker, background_command_tool

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class PersistentAgentCoreBrowser(AgentCoreBrowser):
    """Reconnect a conversation to its active AgentCore browser session."""

    def __init__(self, session_name: str, **kwargs: Any):
        super().__init__(**kwargs)
        self.session_name = session_name

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
) -> tuple[list[Any], PersistentAgentCoreCodeInterpreter | None]:
    tools = []
    code_interpreter = None
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
        tools.append(
            PersistentAgentCoreBrowser(
                region=AWS_REGION,
                session_name=f"frogbot-{session_id}",
                session_timeout=28800,
            ).browser
        )
    return tools, code_interpreter
