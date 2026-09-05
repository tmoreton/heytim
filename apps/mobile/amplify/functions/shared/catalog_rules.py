from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

MAX_SKILLS_PER_BOT = 12
MAX_TOOLS_PER_BOT = 12
MAX_SKILL_INSTRUCTIONS = 20_000
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
TOOL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
RUNTIME_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,127}$")
RUNTIME_NAMES = {
    "agentcore": {"browser", "code_interpreter"},
    "local": {"calculator", "current_time"},
    "stan_builtin": {"web_fetch"},
    "stan_plugin": {"todos"},
    "stan_subagent": {"generalist"},
}
TOOL_RISKS = {"read", "sandbox", "interactive"}
LEGACY_TOOL_RISKS = {
    "web": "read",
    "web_search": "read",
    "calculator": "read",
    "current_time": "read",
    "x_search": "read",
    "youtube_search": "read",
    "task_list": "sandbox",
    "delegate": "sandbox",
    "code_interpreter": "sandbox",
    "browser": "interactive",
}


class CatalogError(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _version_key(version: int) -> str:
    return f"VERSION#{version:09d}"


def _validate_id(value: Any, field: str = "id") -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise CatalogError(f"{field} is invalid")
    return value


def _validate_tool_id(value: Any) -> str:
    if not isinstance(value, str) or not TOOL_ID_PATTERN.fullmatch(value):
        raise CatalogError("tool id is invalid")
    return value


def _validate_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{field} is required")
    clean = value.strip()
    if len(clean) > maximum:
        raise CatalogError(f"{field} must be at most {maximum} characters")
    return clean


def _validate_tool_ids(value: Any, allowed: set[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CatalogError("requiredToolIds must be a list")
    unique = list(dict.fromkeys(value))
    unknown = set(unique) - allowed
    if unknown:
        raise CatalogError(f"Unknown required tools: {', '.join(sorted(unknown))}")
    if len(unique) > MAX_TOOLS_PER_BOT:
        raise CatalogError(f"A skill can require at most {MAX_TOOLS_PER_BOT} tools")
    return unique


def _validate_runtime_binding(value: Any) -> dict:
    if not isinstance(value, dict):
        raise CatalogError("tool runtime binding is required")
    kind = value.get("kind")
    if kind == "gateway":
        operations = value.get("operations")
        if (
            not isinstance(operations, list)
            or not 1 <= len(operations) <= 8
            or len(set(operations)) != len(operations)
            or any(
                not isinstance(operation, str)
                or not RUNTIME_NAME_PATTERN.fullmatch(operation)
                for operation in operations
            )
        ):
            raise CatalogError("gateway tool operations are invalid")
        return {"kind": kind, "operations": operations}
    allowed_names = RUNTIME_NAMES.get(kind)
    name = value.get("name")
    if not allowed_names or name not in allowed_names:
        raise CatalogError("tool runtime binding is unsupported")
    return {"kind": kind, "name": name}


def _public_skill(item: dict) -> dict:
    keys = (
        "id",
        "version",
        "name",
        "description",
        "requiredToolIds",
        "source",
        "visibility",
        "editable",
        "relationship",
        "updatedAt",
    )
    return {key: item[key] for key in keys if key in item}
