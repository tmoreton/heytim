from __future__ import annotations

import ast
import asyncio
import operator
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bedrock_agentcore.tools.browser_client import BrowserClient
from bedrock_agentcore.tools.code_interpreter_client import (
    CodeInterpreter as CodeInterpreterClient,
)
from strands import tool
from strands.tools.mcp.mcp_client import MCPClient
from strands.vended_plugins.skills import AgentSkills, Skill
from strands_tools.browser import AgentCoreBrowser
from strands_tools.code_interpreter import AgentCoreCodeInterpreter

from .artifacts import artifact_tool, image_tool
from .mcp_connections import connection_client, validated_connection_binding

MAX_SKILL_INSTRUCTIONS_CHARS = 20_000
MAX_SKILLS = 12
MAX_TOOLS = 12
GATEWAY_URL = os.environ.get("FROGBOT_GATEWAY_URL") or os.environ.get(
    "AGENTCORE_GATEWAY_FROGBOTTOOLS_URL", ""
)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


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


def _evaluate_number(node: ast.AST) -> int | float:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_number(node.left)
        right = _evaluate_number(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("Exponent is too large")
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_number(node.operand))
    raise ValueError("Expression contains an unsupported operation")


@tool
def calculate(expression: str) -> str:
    """Evaluate arithmetic using numbers, parentheses, and +, -, *, /, //, %, or **."""
    if not isinstance(expression, str):
        raise TypeError("expression must be a string")
    if not expression.strip() or len(expression) > 200:
        raise ValueError("expression must be non-empty and at most 200 characters")
    result = _evaluate_number(ast.parse(expression, mode="eval").body)
    if abs(float(result)) > 1e100:
        raise ValueError("Result is too large")
    return str(result)


@tool
def current_time(timezone: str = "UTC") -> str:
    """Return the current date and time in an IANA timezone such as UTC or America/New_York."""
    if not isinstance(timezone, str):
        raise TypeError("timezone must be a string")
    if len(timezone) > 64:
        raise ValueError("timezone must be at most 64 characters")
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone}") from exc
    return now.isoformat(timespec="seconds")


CUSTOM_TOOLS = {"calculator": calculate, "current_time": current_time}
STAN_BUILTIN_TOOLS = {"web_fetch"}
STAN_PLUGINS = {"todos"}
STAN_SUBAGENTS = {"generalist"}
AGENTCORE_TOOLS = {"browser", "code_interpreter"}


@dataclass(frozen=True)
class CapabilityConfiguration:
    tools: list[Any]
    builtin_tools: list[str]
    plugins: list[Any]
    skill_paths: list[str]
    builtin_plugins: list[str]
    builtin_subagents: list[str]


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


def dynamic_skills(bot: dict) -> list[Skill]:
    raw_skills = bot.get("skills")
    if raw_skills is None:
        return []
    if not isinstance(raw_skills, list) or len(raw_skills) > MAX_SKILLS:
        raise ValueError(f"bot.skills must be a list with at most {MAX_SKILLS} items")

    skills = []
    seen = set()
    for raw in raw_skills:
        if not isinstance(raw, dict):
            raise TypeError("each bot skill must be an object")
        skill_id = raw.get("id")
        name = raw.get("name")
        description = raw.get("description")
        instructions = raw.get("instructions")
        if not isinstance(skill_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,63}", skill_id
        ):
            raise ValueError("bot skill id is invalid")
        if skill_id in seen:
            raise ValueError(f"bot skill id is duplicated: {skill_id}")
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError(f"bot skill name is invalid: {skill_id}")
        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > 240
        ):
            raise ValueError(f"bot skill description is invalid: {skill_id}")
        if (
            not isinstance(instructions, str)
            or not instructions.strip()
            or len(instructions) > MAX_SKILL_INSTRUCTIONS_CHARS
        ):
            raise ValueError(f"bot skill instructions are invalid: {skill_id}")
        seen.add(skill_id)
        skills.append(
            Skill(
                name=skill_id,
                description=description.strip(),
                instructions=instructions.strip(),
                metadata={
                    "display_name": name.strip(),
                    "version": int(raw.get("version", 1)),
                },
            )
        )
    return skills


def tool_bindings(bot: dict) -> list[dict]:
    raw_bindings = bot.get("tools")
    if raw_bindings is None:
        raise ValueError("bot.tools must be resolved by the catalog service")
    if not isinstance(raw_bindings, list) or len(raw_bindings) > MAX_TOOLS:
        raise ValueError(f"bot.tools must be a list with at most {MAX_TOOLS} items")

    bindings = []
    seen = set()
    for raw in raw_bindings:
        if not isinstance(raw, dict):
            raise TypeError("each bot tool must be an object")
        tool_id = raw.get("id")
        runtime = raw.get("runtime")
        if not isinstance(tool_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_]{0,63}", tool_id
        ):
            raise ValueError("bot tool id is invalid")
        if tool_id in seen:
            raise ValueError(f"bot tool id is duplicated: {tool_id}")
        if not isinstance(runtime, dict):
            raise TypeError(f"bot tool runtime is invalid: {tool_id}")

        kind = runtime.get("kind")
        if kind == "gateway":
            operations = runtime.get("operations")
            if (
                not isinstance(operations, list)
                or not 1 <= len(operations) <= 8
                or len(set(operations)) != len(operations)
                or any(
                    not isinstance(operation, str)
                    or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,127}", operation)
                    for operation in operations
                )
            ):
                raise ValueError(f"gateway operations are invalid: {tool_id}")
            binding = {"id": tool_id, "kind": kind, "operations": operations}
        elif kind == "mcp":
            binding = validated_connection_binding(tool_id, runtime)
        else:
            name = runtime.get("name")
            allowed = {
                "agentcore": AGENTCORE_TOOLS,
                "local": set(CUSTOM_TOOLS),
                "stan_builtin": STAN_BUILTIN_TOOLS,
                "stan_plugin": STAN_PLUGINS,
                "stan_subagent": STAN_SUBAGENTS,
            }.get(kind)
            if not allowed or name not in allowed:
                raise ValueError(f"bot tool runtime is unsupported: {tool_id}")
            binding = {"id": tool_id, "kind": kind, "name": name}
        seen.add(tool_id)
        bindings.append(binding)
    return bindings


def _gateway_client(operations: list[str]) -> MCPClient | None:
    if not operations:
        return None
    if not GATEWAY_URL:
        raise ValueError("One or more selected tools are not configured")

    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

    allowed = [re.compile(rf".*___{re.escape(operation)}$") for operation in operations]
    return MCPClient(
        lambda: aws_iam_streamablehttp_client(
            endpoint=GATEWAY_URL,
            aws_region=AWS_REGION,
            aws_service="bedrock-agentcore",
        ),
        tool_filters={"allowed": allowed},
        continue_on_error=False,
        startup_timeout=15,
        application_name="FroggyBot",
    )


def resolve_capabilities(
    bot: dict, session_id: str, artifact_prefix: str | None = None
) -> CapabilityConfiguration:
    bindings = tool_bindings(bot)
    skills = dynamic_skills(bot)
    tools = [CUSTOM_TOOLS[item["name"]] for item in bindings if item["kind"] == "local"]
    if artifact_prefix:
        tools.extend([artifact_tool(artifact_prefix), image_tool(artifact_prefix)])

    if any(
        item["kind"] == "agentcore" and item["name"] == "code_interpreter"
        for item in bindings
    ):
        interpreter = PersistentAgentCoreCodeInterpreter(
            region=AWS_REGION,
            session_name=f"frogbot-{session_id}",
            session_timeout_seconds=7200,
        )
        tools.append(interpreter.code_interpreter)
    if any(
        item["kind"] == "agentcore" and item["name"] == "browser" for item in bindings
    ):
        _prepare_playwright_driver()
        tools.append(
            PersistentAgentCoreBrowser(
                region=AWS_REGION,
                session_name=f"frogbot-{session_id}",
                session_timeout=7200,
            ).browser
        )

    gateway_operations = list(
        dict.fromkeys(
            operation
            for item in bindings
            if item["kind"] == "gateway"
            for operation in item["operations"]
        )
    )
    gateway_client = _gateway_client(gateway_operations)
    if gateway_client:
        tools.append(gateway_client)
    tools.extend(connection_client(item) for item in bindings if item["kind"] == "mcp")

    skill_ids = bot.get("skillIds", [])
    if not isinstance(skill_ids, list) or not all(
        isinstance(value, str) for value in skill_ids
    ):
        raise TypeError("bot.skillIds must be a list of strings")
    if bot.get("skills") is None:
        raise ValueError("bot.skills must be resolved by the catalog service")
    resolved_skill_ids = {skill.name for skill in skills}
    if set(skill_ids) != resolved_skill_ids:
        raise ValueError("bot.skillIds and resolved bot.skills do not match")

    return CapabilityConfiguration(
        tools=tools,
        builtin_tools=[
            item["name"] for item in bindings if item["kind"] == "stan_builtin"
        ],
        plugins=[AgentSkills(skills=skills, strict=True)] if skills else [],
        skill_paths=[],
        builtin_plugins=[
            item["name"] for item in bindings if item["kind"] == "stan_plugin"
        ],
        builtin_subagents=[
            item["name"] for item in bindings if item["kind"] == "stan_subagent"
        ],
    )
