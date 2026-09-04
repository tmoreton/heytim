from __future__ import annotations

import ast
import operator
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import tool
from strands.tools.mcp.mcp_client import MCPClient
from strands.vended_plugins.skills import AgentSkills, Skill
from strands_stan import harness_agent

from model.load import load_model

app = BedrockAgentCoreApp()
log = app.logger

MAX_HISTORY_MESSAGES = 40
MAX_MESSAGE_CHARS = 12_000
MAX_INSTRUCTIONS_CHARS = 12_000
MAX_SKILL_INSTRUCTIONS_CHARS = 20_000
MAX_SKILLS = 12
SKILL_ROOT = Path(__file__).parent / "skill_catalog"
GATEWAY_URL = os.environ.get("FROGBOT_GATEWAY_URL") or os.environ.get("AGENTCORE_GATEWAY_FROGBOTTOOLS_URL", "")
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
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
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
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 200:
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
BUILTIN_TOOLS = {"web": "web_fetch"}
GATEWAY_TOOL_PATTERNS = {
    "web_search": r".*___WebSearch$",
    "x_search": r".*___x_search_recent$",
    "youtube_search": r".*___youtube_(search|video_details|comments)$",
}
SKILLS = {
    "researcher": SKILL_ROOT / "researcher",
    "writer": SKILL_ROOT / "writer",
    "planner": SKILL_ROOT / "planner",
}


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
        if not isinstance(original_content, list) or not all(isinstance(block, dict) for block in original_content):
            raise ValueError("each message content value must be a list of content blocks")
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
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
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
                raise ValueError(f"message text must be between 1 and {MAX_MESSAGE_CHARS} characters")
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
        if not isinstance(skill_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", skill_id):
            raise ValueError("bot skill id is invalid")
        if skill_id in seen:
            raise ValueError(f"bot skill id is duplicated: {skill_id}")
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError(f"bot skill name is invalid: {skill_id}")
        if not isinstance(description, str) or not description.strip() or len(description) > 240:
            raise ValueError(f"bot skill description is invalid: {skill_id}")
        if not isinstance(instructions, str) or not instructions.strip() or len(instructions) > MAX_SKILL_INSTRUCTIONS_CHARS:
            raise ValueError(f"bot skill instructions are invalid: {skill_id}")
        seen.add(skill_id)
        skills.append(
            Skill(
                name=skill_id,
                description=description.strip(),
                instructions=instructions.strip(),
                metadata={"display_name": name.strip(), "version": int(raw.get("version", 1))},
            )
        )
    return skills


def _gateway_client(tool_ids: list[str]) -> MCPClient | None:
    requested = [tool_id for tool_id in tool_ids if tool_id in GATEWAY_TOOL_PATTERNS]
    if not requested:
        return None
    if not GATEWAY_URL:
        raise ValueError("One or more selected tools are not configured")

    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

    allowed = [re.compile(GATEWAY_TOOL_PATTERNS[tool_id]) for tool_id in requested]
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


def _bot_config(payload: dict) -> tuple[str, list[Any], list[str], list[Any], list[str]]:
    bot = payload.get("bot", {})
    if not isinstance(bot, dict):
        raise ValueError("bot must be an object")

    name = bot.get("name", "FrogBot")
    instructions = bot.get("prompt", "Be helpful, direct, and honest.")
    tool_ids = bot.get("toolIds", [])
    skill_ids = bot.get("skillIds", [])
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise ValueError("bot.name must be a non-empty string up to 60 characters")
    if not isinstance(instructions, str) or len(instructions) > MAX_INSTRUCTIONS_CHARS:
        raise ValueError(f"bot.prompt must be a string up to {MAX_INSTRUCTIONS_CHARS} characters")
    if not isinstance(tool_ids, list) or not all(isinstance(value, str) for value in tool_ids):
        raise ValueError("bot.toolIds must be a list of strings")
    if not isinstance(skill_ids, list) or not all(isinstance(value, str) for value in skill_ids):
        raise ValueError("bot.skillIds must be a list of strings")

    unknown_tools = set(tool_ids) - set(CUSTOM_TOOLS) - set(BUILTIN_TOOLS) - set(GATEWAY_TOOL_PATTERNS)
    dynamic_skills = _dynamic_skills(bot)
    unknown_skills = set() if bot.get("skills") is not None else set(skill_ids) - set(SKILLS)
    if unknown_tools:
        raise ValueError(f"Unknown tool ids: {', '.join(sorted(unknown_tools))}")
    if unknown_skills:
        raise ValueError(f"Unknown skill ids: {', '.join(sorted(unknown_skills))}")

    domain_instructions = (
        f"Your name is {name.strip()}. You are one member of the user's team of AI assistants.\n\n"
        f"Your role and working preferences:\n{instructions.strip()}"
    )
    tools = [CUSTOM_TOOLS[tool_id] for tool_id in tool_ids if tool_id in CUSTOM_TOOLS]
    gateway_client = _gateway_client(tool_ids)
    if gateway_client:
        tools.append(gateway_client)
    builtin_tools = [BUILTIN_TOOLS[tool_id] for tool_id in tool_ids if tool_id in BUILTIN_TOOLS]
    if dynamic_skills:
        plugins = [AgentSkills(skills=dynamic_skills, strict=True)]
        skill_paths = []
    else:
        plugins = []
        skill_paths = [str(SKILLS[skill_id]) for skill_id in skill_ids]
    return domain_instructions, tools, builtin_tools, plugins, skill_paths


@app.entrypoint
async def invoke(payload, context):
    messages = _messages_from_payload(payload)
    instructions, tools, builtin_tools, plugins, skill_paths = _bot_config(payload)
    session_id = getattr(context, "session_id", "unknown")
    log.info("Invoking FrogBot session %s with %d history messages", session_id, len(messages))

    agent = harness_agent(
        model=load_model(),
        web_fetch_model="global.anthropic.claude-haiku-4-5-20251001-v1:0",
        caching=False,
        instructions=instructions,
        tools=tools,
        builtin_tools=builtin_tools,
        plugins=plugins,
        builtin_plugins=[],
        builtin_subagents=[],
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
