from __future__ import annotations

import ast
import operator
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import tool
from strands.tools.mcp.mcp_client import MCPClient
from strands.vended_plugins.skills import AgentSkills, Skill
from strands_stan import harness_agent
from strands_tools.browser import AgentCoreBrowser
from strands_tools.code_interpreter import AgentCoreCodeInterpreter

from group_context import collaboration_instructions
from model.load import load_model

app = BedrockAgentCoreApp()
log = app.logger

MAX_HISTORY_MESSAGES = 40
MAX_MESSAGE_CHARS = 12_000
MAX_INSTRUCTIONS_CHARS = 12_000
MAX_SKILL_INSTRUCTIONS_CHARS = 20_000
MAX_SKILLS = 12
MAX_TOOLS = 12
SKILL_ROOT = Path(__file__).parent / "skill_catalog"
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
    """Evaluate basic arithmetic using numbers, parentheses, and +, -, *, /, //, %, or **."""
    if (
        not isinstance(expression, str)
        or not expression.strip()
        or len(expression) > 200
    ):
        raise ValueError("expression must be a non-empty string up to 200 characters")
    result = _evaluate_number(ast.parse(expression, mode="eval").body)
    if abs(float(result)) > 1e100:
        raise ValueError("Result is too large")
    return str(result)


@tool
def current_time(timezone: str = "UTC") -> str:
    """Return the current date and time in an IANA timezone such as UTC or America/New_York."""
    if not isinstance(timezone, str) or len(timezone) > 64:
        raise ValueError("timezone must be an IANA timezone string")
    try:
        now = datetime.now(ZoneInfo(timezone))
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone}") from exc
    return now.isoformat(timespec="seconds")


CUSTOM_TOOLS = {
    "calculator": calculate,
    "current_time": current_time,
}
STAN_BUILTIN_TOOLS = {"web_fetch"}
STAN_PLUGINS = {"todos"}
STAN_SUBAGENTS = {"generalist"}
AGENTCORE_TOOLS = {"browser", "code_interpreter"}
LEGACY_TOOL_BINDINGS = {
    "web": {"kind": "stan_builtin", "name": "web_fetch"},
    "web_search": {"kind": "gateway", "operations": ["WebSearch"]},
    "calculator": {"kind": "local", "name": "calculator"},
    "current_time": {"kind": "local", "name": "current_time"},
    "x_search": {"kind": "gateway", "operations": ["x_search_recent"]},
    "youtube_search": {
        "kind": "gateway",
        "operations": ["youtube_search", "youtube_video_details", "youtube_comments"],
    },
    "task_list": {"kind": "stan_plugin", "name": "todos"},
    "delegate": {"kind": "stan_subagent", "name": "generalist"},
    "code_interpreter": {"kind": "agentcore", "name": "code_interpreter"},
    "browser": {"kind": "agentcore", "name": "browser"},
}
SKILLS = {
    "researcher": SKILL_ROOT / "researcher",
    "writer": SKILL_ROOT / "writer",
    "planner": SKILL_ROOT / "planner",
}


def _prepare_playwright_driver() -> None:
    import playwright

    source = Path(playwright.__file__).resolve().parent / "driver" / "node"
    if not source.is_file():
        raise RuntimeError("Playwright driver is missing")
    if not os.access(source, os.X_OK):
        try:
            source.chmod(source.stat().st_mode | 0o111)
        except OSError:
            target = Path("/tmp/frogbot-playwright-node")
            if not target.is_file() or target.stat().st_size != source.stat().st_size:
                shutil.copyfile(source, target)
            target.chmod(0o700)
            source = target
    if not os.access(source, os.X_OK):
        raise RuntimeError("Playwright driver is not executable")
    os.environ["PLAYWRIGHT_NODEJS_PATH"] = str(source)


def strip_trailing_tool_use(messages: Any) -> list[dict]:
    """Strip toolUse blocks from the tail until the final message is safe to resume."""
    if not isinstance(messages, list):
        raise ValueError("messages must be a list")

    cleaned = list(messages)
    while cleaned:
        last = cleaned[-1]
        if not isinstance(last, dict):
            raise ValueError("each message must be an object")
        original_content = last.get("content", [])
        if not isinstance(original_content, list) or not all(
            isinstance(block, dict) for block in original_content
        ):
            raise ValueError(
                "each message content value must be a list of content blocks"
            )
        content = [block for block in original_content if "toolUse" not in block]
        if len(content) == len(original_content):
            break
        if content:
            cleaned[-1] = {**last, "content": content}
            break
        cleaned.pop()
    return cleaned


def _messages_from_payload(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    raw_messages = payload.get("messages")
    if raw_messages is None:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        raw_messages = [{"role": "user", "content": [{"text": prompt.strip()}]}]
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ValueError("messages must be a non-empty list")

    raw_messages = strip_trailing_tool_use(raw_messages)
    messages: list[dict] = []
    for message in raw_messages[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(message, dict) or message.get("role") not in {
            "user",
            "assistant",
        }:
            raise ValueError("each message must have a user or assistant role")
        content = message.get("content")
        if not isinstance(content, list) or not content:
            raise ValueError("each message must contain at least one content block")
        text_blocks = []
        for block in content:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                raise ValueError("only text content blocks are accepted")
            text = block["text"].strip()
            if not text or len(text) > MAX_MESSAGE_CHARS:
                raise ValueError(
                    f"message text must be between 1 and {MAX_MESSAGE_CHARS} characters"
                )
            text_blocks.append({"text": text})
        messages.append({"role": message["role"], "content": text_blocks})
    return messages


def _dynamic_skills(bot: dict) -> list[Skill]:
    raw_skills = bot.get("skills")
    if raw_skills is None:
        return []
    if not isinstance(raw_skills, list) or len(raw_skills) > MAX_SKILLS:
        raise ValueError(f"bot.skills must be a list with at most {MAX_SKILLS} items")

    skills = []
    seen = set()
    for raw in raw_skills:
        if not isinstance(raw, dict):
            raise ValueError("each bot skill must be an object")
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


def _tool_bindings(bot: dict) -> list[dict]:
    raw_bindings = bot.get("tools")
    if raw_bindings is None:
        raw_ids = bot.get("toolIds", [])
        if not isinstance(raw_ids, list) or not all(
            isinstance(value, str) for value in raw_ids
        ):
            raise ValueError("bot.toolIds must be a list of strings")
        unknown = set(raw_ids) - set(LEGACY_TOOL_BINDINGS)
        if unknown:
            raise ValueError(f"Unknown tool ids: {', '.join(sorted(unknown))}")
        raw_bindings = [
            {"id": tool_id, "runtime": LEGACY_TOOL_BINDINGS[tool_id]}
            for tool_id in raw_ids
        ]
    if not isinstance(raw_bindings, list) or len(raw_bindings) > MAX_TOOLS:
        raise ValueError(f"bot.tools must be a list with at most {MAX_TOOLS} items")

    bindings = []
    seen = set()
    for raw in raw_bindings:
        if not isinstance(raw, dict):
            raise ValueError("each bot tool must be an object")
        tool_id = raw.get("id")
        runtime = raw.get("runtime")
        if not isinstance(tool_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_]{0,63}", tool_id
        ):
            raise ValueError("bot tool id is invalid")
        if tool_id in seen:
            raise ValueError(f"bot tool id is duplicated: {tool_id}")
        if not isinstance(runtime, dict):
            raise ValueError(f"bot tool runtime is invalid: {tool_id}")

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
        application_name="FrogBot",
    )


def _bot_config(
    payload: dict, session_id: str = "unknown"
) -> tuple[str, list[Any], list[str], list[Any], list[str], list[str], list[str]]:
    bot = payload.get("bot", {})
    if not isinstance(bot, dict):
        raise ValueError("bot must be an object")

    name = bot.get("name", "FrogBot")
    instructions = bot.get("prompt", "Be helpful, direct, and honest.")
    skill_ids = bot.get("skillIds", [])
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise ValueError("bot.name must be a non-empty string up to 60 characters")
    if not isinstance(instructions, str) or len(instructions) > MAX_INSTRUCTIONS_CHARS:
        raise ValueError(
            f"bot.prompt must be a string up to {MAX_INSTRUCTIONS_CHARS} characters"
        )
    if not isinstance(skill_ids, list) or not all(
        isinstance(value, str) for value in skill_ids
    ):
        raise ValueError("bot.skillIds must be a list of strings")

    tool_bindings = _tool_bindings(bot)
    dynamic_skills = _dynamic_skills(bot)
    unknown_skills = (
        set() if bot.get("skills") is not None else set(skill_ids) - set(SKILLS)
    )
    if unknown_skills:
        raise ValueError(f"Unknown skill ids: {', '.join(sorted(unknown_skills))}")

    domain_instructions = (
        f"Your name is {name.strip()}. You are one member of the user's team of AI assistants.\n\n"
        f"Your role and working preferences:\n{instructions.strip()}"
    )
    group_instructions = collaboration_instructions(payload.get("group"))
    if group_instructions:
        domain_instructions = f"{domain_instructions}\n\n{group_instructions}"
    tools = [
        CUSTOM_TOOLS[binding["name"]]
        for binding in tool_bindings
        if binding["kind"] == "local"
    ]
    if any(
        binding["kind"] == "agentcore" and binding["name"] == "code_interpreter"
        for binding in tool_bindings
    ):
        interpreter = AgentCoreCodeInterpreter(
            region=AWS_REGION, session_name=f"frogbot-{session_id}"
        )
        tools.append(interpreter.code_interpreter)
    if any(
        binding["kind"] == "agentcore" and binding["name"] == "browser"
        for binding in tool_bindings
    ):
        _prepare_playwright_driver()
        browser = AgentCoreBrowser(region=AWS_REGION)
        tools.append(browser.browser)
    gateway_operations = list(
        dict.fromkeys(
            operation
            for binding in tool_bindings
            if binding["kind"] == "gateway"
            for operation in binding["operations"]
        )
    )
    gateway_client = _gateway_client(gateway_operations)
    if gateway_client:
        tools.append(gateway_client)
    builtin_tools = [
        binding["name"]
        for binding in tool_bindings
        if binding["kind"] == "stan_builtin"
    ]
    builtin_plugins = [
        binding["name"] for binding in tool_bindings if binding["kind"] == "stan_plugin"
    ]
    builtin_subagents = [
        binding["name"]
        for binding in tool_bindings
        if binding["kind"] == "stan_subagent"
    ]
    if dynamic_skills:
        plugins = [AgentSkills(skills=dynamic_skills, strict=True)]
        skill_paths = []
    else:
        plugins = []
        skill_paths = [str(SKILLS[skill_id]) for skill_id in skill_ids]
    return (
        domain_instructions,
        tools,
        builtin_tools,
        plugins,
        skill_paths,
        builtin_plugins,
        builtin_subagents,
    )


@app.entrypoint
async def invoke(payload, context):
    messages = _messages_from_payload(payload)
    session_id = getattr(context, "session_id", "unknown")
    (
        instructions,
        tools,
        builtin_tools,
        plugins,
        skill_paths,
        builtin_plugins,
        builtin_subagents,
    ) = _bot_config(payload, session_id)
    log.info(
        "Invoking FrogBot session %s with %d history messages",
        session_id,
        len(messages),
    )

    agent = harness_agent(
        model=load_model(),
        web_fetch_model="global.anthropic.claude-haiku-4-5-20251001-v1:0",
        caching=False,
        instructions=instructions,
        tools=tools,
        builtin_tools=builtin_tools,
        plugins=plugins,
        builtin_plugins=builtin_plugins,
        builtin_subagents=builtin_subagents,
        skills_dir=skill_paths or None,
        memory=False,
        context_management="auto",
    )
    async for event in agent.stream_async(messages):
        if not isinstance(event, dict) or "event" not in event:
            continue
        block_start = event["event"].get("contentBlockStart")
        if block_start is not None and not block_start.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()
