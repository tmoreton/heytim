from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from shared.invites import invite_url

logger = logging.getLogger(__name__)

CATALOG_URL = os.environ.get(
    "CAPABILITY_CATALOG_URL",
    "https://raw.githubusercontent.com/tmoreton/frogbot-capabilities/main/catalog.json",
)
ALLOWED_REPOSITORY = "tmoreton/frogbot-capabilities"
PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://frogbot.expo.app")
MAX_SKILLS_PER_BOT = 12
MAX_TOOLS_PER_BOT = 12
MAX_SKILL_INSTRUCTIONS = 20_000
SYNC_SECONDS = 300
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

FALLBACK_TOOLS = [
    {
        "id": "web",
        "name": "Web reader",
        "description": "Open and summarize a specific web page.",
        "runtime": {"kind": "stan_builtin", "name": "web_fetch"},
        "enabled": True,
    },
    {
        "id": "web_search",
        "name": "Web search",
        "description": "Search the live web and return relevant sources.",
        "runtime": {"kind": "gateway", "operations": ["WebSearch"]},
        "enabled": True,
    },
    {
        "id": "calculator",
        "name": "Calculator",
        "description": "Do exact arithmetic safely.",
        "runtime": {"kind": "local", "name": "calculator"},
        "enabled": True,
    },
    {
        "id": "current_time",
        "name": "World clock",
        "description": "Check the current time in any timezone.",
        "runtime": {"kind": "local", "name": "current_time"},
        "enabled": True,
    },
    {
        "id": "x_search",
        "name": "X / Twitter search",
        "description": "Search recent public posts on X.",
        "runtime": {"kind": "gateway", "operations": ["x_search_recent"]},
        "enabled": False,
    },
    {
        "id": "youtube_search",
        "name": "YouTube research",
        "description": "Find public videos and inspect metadata and comments.",
        "runtime": {
            "kind": "gateway",
            "operations": ["youtube_search", "youtube_video_details", "youtube_comments"],
        },
        "enabled": False,
    },
    {
        "id": "task_list",
        "name": "Task tracker",
        "description": "Keep a live checklist during longer, multi-step work.",
        "runtime": {"kind": "stan_plugin", "name": "todos"},
        "enabled": True,
    },
    {
        "id": "delegate",
        "name": "Focused delegate",
        "description": "Hand a focused subtask to a fresh agent and bring back its conclusion.",
        "runtime": {"kind": "stan_subagent", "name": "generalist"},
        "enabled": True,
    },
    {
        "id": "code_interpreter",
        "name": "Code interpreter",
        "description": "Run Python, JavaScript, or TypeScript in an isolated AgentCore sandbox.",
        "runtime": {"kind": "agentcore", "name": "code_interpreter"},
        "enabled": True,
    },
    {
        "id": "browser",
        "name": "Interactive browser",
        "description": "Open websites, navigate pages, interact with controls, and extract visible information.",
        "runtime": {"kind": "agentcore", "name": "browser"},
        "enabled": True,
    },
]

FALLBACK_SKILLS = [
    {
        "id": "planner",
        "version": 1,
        "name": "Planner",
        "description": "Turn goals into practical next steps.",
        "requiredToolIds": [],
        "instructions": "Turn a goal into a concise, ordered plan. State assumptions, dependencies, risks, and the next concrete action.",
        "source": "official",
        "visibility": "public",
        "editable": False,
    },
    {
        "id": "researcher",
        "version": 1,
        "name": "Researcher",
        "description": "Investigate questions and synthesize evidence.",
        "requiredToolIds": ["web", "web_search"],
        "instructions": "Research the question using reliable sources. Separate facts from inference, cite sources, and call out uncertainty.",
        "source": "official",
        "visibility": "public",
        "editable": False,
    },
    {
        "id": "writer",
        "version": 1,
        "name": "Writer",
        "description": "Draft polished, audience-aware copy.",
        "requiredToolIds": [],
        "instructions": "Create usable, audience-aware writing. Preserve supplied facts, prefer clear language, and match the requested voice.",
        "source": "official",
        "visibility": "public",
        "editable": False,
    },
]

_last_sync_at = 0.0


class CatalogError(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _version_key(version: int) -> str:
    return f"VERSION#{version:09d}"


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "FrogBot/1.0"})
    with urllib.request.urlopen(request, timeout=5) as response:
        value = json.loads(response.read(500_001).decode("utf-8"))
    if not isinstance(value, dict):
        raise CatalogError("Capability catalog must be a JSON object")
    return value


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"accept": "text/plain", "user-agent": "FrogBot/1.0"})
    with urllib.request.urlopen(request, timeout=5) as response:
        value = response.read(MAX_SKILL_INSTRUCTIONS + 4_001).decode("utf-8")
    if len(value) > MAX_SKILL_INSTRUCTIONS + 4_000:
        raise CatalogError("Skill document is too large")
    return value


def _skill_instructions(document: str) -> str:
    if not document.startswith("---\n"):
        raise CatalogError("Skill document must start with YAML frontmatter")
    boundary = document.find("\n---\n", 4)
    if boundary < 0:
        raise CatalogError("Skill document frontmatter is incomplete")
    instructions = document[boundary + 5 :].strip()
    if not instructions or len(instructions) > MAX_SKILL_INSTRUCTIONS:
        raise CatalogError("Skill instructions are empty or too large")
    return instructions


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
            or any(not isinstance(operation, str) or not RUNTIME_NAME_PATTERN.fullmatch(operation) for operation in operations)
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


class CatalogService:
    def __init__(self, table: Any):
        self.table = table

    def sync_official(self, *, force: bool = False) -> None:
        global _last_sync_at
        current = time.monotonic()
        if not force and _last_sync_at > 0 and current - _last_sync_at < SYNC_SECONDS:
            return
        try:
            self._sync_remote()
        except (CatalogError, OSError, UnicodeError, urllib.error.URLError, json.JSONDecodeError):
            logger.exception("Could not refresh the capability catalog; using the last known catalog")
            self._ensure_fallbacks()
        _last_sync_at = current

    def _sync_remote(self) -> None:
        catalog = _fetch_json(CATALOG_URL)
        if catalog.get("schemaVersion") != 2 or catalog.get("repository") != ALLOWED_REPOSITORY:
            raise CatalogError("Capability catalog source is not trusted")
        release = catalog.get("release")
        if not isinstance(release, str) or not re.fullmatch(r"skills-v[0-9]+", release):
            raise CatalogError("Capability catalog release is invalid")
        raw_tools = catalog.get("tools")
        raw_skills = catalog.get("skills")
        if not isinstance(raw_tools, list) or not isinstance(raw_skills, list):
            raise CatalogError("Capability catalog lists are invalid")

        parsed_tools = []
        for raw in raw_tools:
            if not isinstance(raw, dict):
                raise CatalogError("Capability catalog tool is invalid")
            parsed_tools.append(
                {
                    "id": _validate_tool_id(raw.get("id")),
                    "name": _validate_text(raw.get("name"), "tool name", 80),
                    "description": _validate_text(raw.get("description"), "tool description", 240),
                    "provider": str(raw.get("provider", "frogbot"))[:80],
                    "credential": str(raw.get("credential", ""))[:80],
                    "runtime": _validate_runtime_binding(raw.get("runtime")),
                    "enabled": raw.get("enabled") is True,
                }
            )
        tool_ids = {item["id"] for item in parsed_tools}
        if len(tool_ids) != len(parsed_tools):
            raise CatalogError("Capability catalog tool IDs must be unique")
        tools = [item for item in parsed_tools if item["enabled"]]

        skills = []
        for raw in raw_skills:
            if not isinstance(raw, dict):
                raise CatalogError("Capability catalog skill is invalid")
            skill_id = _validate_id(raw.get("id"), "skill id")
            version = raw.get("version")
            path = raw.get("path")
            if not isinstance(version, int) or version < 1 or version > 1_000_000:
                raise CatalogError(f"{skill_id} version is invalid")
            if not isinstance(path, str) or not re.fullmatch(r"skills/[a-z0-9-]+/SKILL\.md", path):
                raise CatalogError(f"{skill_id} path is invalid")
            document = _fetch_text(f"https://raw.githubusercontent.com/{ALLOWED_REPOSITORY}/{release}/{path}")
            skills.append(
                {
                    "id": skill_id,
                    "version": version,
                    "name": _validate_text(raw.get("name"), "skill name", 80),
                    "description": _validate_text(raw.get("description"), "skill description", 240),
                    "requiredToolIds": _validate_tool_ids(raw.get("requiredToolIds", []), tool_ids),
                    "instructions": _skill_instructions(document),
                    "source": "official",
                    "visibility": "public",
                    "editable": False,
                    "release": release,
                }
            )
        if len({item["id"] for item in skills}) != len(skills):
            raise CatalogError("Capability catalog skill IDs must be unique")
        self._store_official(tools, skills)

    def _ensure_fallbacks(self) -> None:
        response = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#SKILLS", ":prefix": "SKILL#"},
            Limit=1,
        )
        if response.get("Items"):
            return
        self._store_official(FALLBACK_TOOLS, FALLBACK_SKILLS)

    def _store_official(self, tools: list[dict], skills: list[dict]) -> None:
        current = _now()
        existing_tools = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#TOOLS", ":prefix": "TOOL#"},
        ).get("Items", [])
        existing_skills = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#SKILLS", ":prefix": "SKILL#"},
        ).get("Items", [])
        tool_keys = {f"TOOL#{tool['id']}" for tool in tools}
        skill_keys = {f"SKILL#{skill['id']}" for skill in skills}
        with self.table.batch_writer() as batch:
            for item in existing_tools:
                if item.get("sk") not in tool_keys:
                    batch.delete_item(Key={"pk": "SYSTEM#TOOLS", "sk": item["sk"]})
            for item in existing_skills:
                if item.get("sk") not in skill_keys:
                    batch.delete_item(Key={"pk": "SYSTEM#SKILLS", "sk": item["sk"]})
            for tool in tools:
                batch.put_item(Item={"pk": "SYSTEM#TOOLS", "sk": f"TOOL#{tool['id']}", "entity": "TOOL", **tool})
            for skill in skills:
                listing = {
                    "pk": "SYSTEM#SKILLS",
                    "sk": f"SKILL#{skill['id']}",
                    "entity": "SKILL_LISTING",
                    **_public_skill({**skill, "updatedAt": current}),
                }
                version = {
                    "pk": f"SKILL#{skill['id']}",
                    "sk": _version_key(skill["version"]),
                    "entity": "SKILL_VERSION",
                    **skill,
                    "updatedAt": current,
                }
                batch.put_item(Item=listing)
                batch.put_item(Item=version)

    def list_tools(self) -> list[dict]:
        self.sync_official()
        items = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#TOOLS", ":prefix": "TOOL#"},
        ).get("Items", [])
        return sorted(
            (
                {key: item[key] for key in ("id", "name", "description") if key in item}
                for item in items
                if item.get("enabled") is True
            ),
            key=lambda item: item["name"].lower(),
        )

    def list_skills(self, user_id: str) -> list[dict]:
        self.sync_official()
        official = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#SKILLS", ":prefix": "SKILL#"},
        ).get("Items", [])
        library = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": f"USER#{user_id}", ":prefix": "SKILL#"},
        ).get("Items", [])
        available_tool_ids = {item["id"] for item in self.list_tools()}
        by_id = {
            item["id"]: _public_skill(item)
            for item in official + library
            if isinstance(item.get("id"), str)
            and set(item.get("requiredToolIds", [])).issubset(available_tool_ids)
        }
        return sorted(by_id.values(), key=lambda item: (item.get("source") != "official", item["name"].lower()))

    def _accessible_listing(self, user_id: str, skill_id: str) -> dict | None:
        official = self.table.get_item(
            Key={"pk": "SYSTEM#SKILLS", "sk": f"SKILL#{skill_id}"}, ConsistentRead=True
        ).get("Item")
        if official:
            return official
        return self.table.get_item(
            Key={"pk": f"USER#{user_id}", "sk": f"SKILL#{skill_id}"}, ConsistentRead=True
        ).get("Item")

    def validate_and_pin(self, user_id: str, skill_ids: Any, existing: dict | None = None) -> dict[str, int]:
        if not isinstance(skill_ids, list) or not all(isinstance(item, str) for item in skill_ids):
            raise CatalogError("skillIds must be a list")
        unique = list(dict.fromkeys(skill_ids))
        if len(unique) > MAX_SKILLS_PER_BOT:
            raise CatalogError(f"A bot can use at most {MAX_SKILLS_PER_BOT} skills")
        existing = existing or {}
        available_tool_ids = {item["id"] for item in self.list_tools()}
        pinned: dict[str, int] = {}
        for skill_id in unique:
            _validate_id(skill_id, "skill id")
            listing = self._accessible_listing(user_id, skill_id)
            if not listing:
                raise CatalogError(f"Unknown skill: {skill_id}")
            if not set(listing.get("requiredToolIds", [])).issubset(available_tool_ids):
                raise CatalogError(f"Skill is not available yet: {skill_id}")
            old_version = existing.get(skill_id)
            pinned[skill_id] = (
                int(old_version) if isinstance(old_version, (int, float, Decimal)) else int(listing["version"])
            )
            if not self.get_version(skill_id, pinned[skill_id]):
                pinned[skill_id] = int(listing["version"])
        return pinned

    def validate_tools(self, tool_ids: Any) -> list[str]:
        if not isinstance(tool_ids, list) or not all(isinstance(item, str) for item in tool_ids):
            raise CatalogError("toolIds must be a list")
        unique = list(dict.fromkeys(tool_ids))
        allowed = {item["id"] for item in self.list_tools()}
        unknown = set(unique) - allowed
        if unknown:
            raise CatalogError(f"Unknown tools: {', '.join(sorted(unknown))}")
        if len(unique) > MAX_TOOLS_PER_BOT:
            raise CatalogError(f"A bot can use at most {MAX_TOOLS_PER_BOT} tools")
        return unique

    def resolve_tools_for_runtime(self, tool_ids: Any) -> list[dict]:
        selected = self.validate_tools(tool_ids)
        items = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#TOOLS", ":prefix": "TOOL#"},
        ).get("Items", [])
        by_id = {item.get("id"): item for item in items}
        resolved = []
        for tool_id in selected:
            item = by_id.get(tool_id)
            if not item:
                raise CatalogError(f"Tool is unavailable: {tool_id}")
            resolved.append({"id": tool_id, "runtime": _validate_runtime_binding(item.get("runtime"))})
        return resolved

    def get_version(self, skill_id: str, version: int) -> dict | None:
        return self.table.get_item(
            Key={"pk": f"SKILL#{skill_id}", "sk": _version_key(int(version))}, ConsistentRead=True
        ).get("Item")

    def get_skill(self, user_id: str, skill_id: str) -> dict:
        listing = self._accessible_listing(user_id, _validate_id(skill_id, "skill id"))
        if not listing:
            raise CatalogError("Skill not found")
        version = self.get_version(skill_id, int(listing["version"]))
        if not version:
            raise CatalogError("Skill version not found")
        return {**_public_skill(listing), "instructions": version["instructions"]}

    def save_skill(self, user_id: str, value: dict, skill_id: str | None = None) -> dict:
        name = _validate_text(value.get("name"), "name", 80)
        description = _validate_text(value.get("description"), "description", 240)
        instructions = _validate_text(value.get("instructions"), "instructions", MAX_SKILL_INSTRUCTIONS)
        required_tools = _validate_tool_ids(value.get("requiredToolIds", []), {item["id"] for item in self.list_tools()})
        visibility = value.get("visibility", "private")
        if visibility not in {"private", "link"}:
            raise CatalogError("visibility must be private or link")
        current = _now()

        if skill_id:
            skill_id = _validate_id(skill_id, "skill id")
            listing = self._accessible_listing(user_id, skill_id)
            if not listing or listing.get("ownerId") != user_id or not listing.get("editable"):
                raise CatalogError("Only the skill owner can edit this skill")
            version = int(listing["version"]) + 1
            created_at = listing.get("createdAt", current)
        else:
            skill_id = f"skill-{uuid.uuid4().hex[:20]}"
            version = 1
            created_at = current

        common = {
            "id": skill_id,
            "version": version,
            "name": name,
            "description": description,
            "requiredToolIds": required_tools,
            "source": "user",
            "visibility": visibility,
            "editable": True,
            "ownerId": user_id,
            "relationship": "owner",
            "createdAt": created_at,
            "updatedAt": current,
        }
        with self.table.batch_writer() as batch:
            batch.put_item(
                Item={
                    "pk": f"SKILL#{skill_id}",
                    "sk": _version_key(version),
                    "entity": "SKILL_VERSION",
                    **common,
                    "instructions": instructions,
                }
            )
            batch.put_item(Item={"pk": f"SKILL#{skill_id}", "sk": "META", "entity": "SKILL_META", **common})
            batch.put_item(Item={"pk": f"USER#{user_id}", "sk": f"SKILL#{skill_id}", "entity": "USER_SKILL", **common})
        return {**_public_skill(common), "instructions": instructions}

    def create_share(self, user_id: str, skill_id: str) -> dict:
        skill = self.get_skill(user_id, skill_id)
        token = secrets.token_urlsafe(18)
        expires_at = int(datetime.now(UTC).timestamp()) + 30 * 24 * 60 * 60
        self.table.put_item(
            Item={
                "pk": f"SKILL_SHARE#{token}",
                "sk": "META",
                "entity": "SKILL_SHARE",
                "ownerId": user_id,
                "snapshot": skill,
                "expiresAt": expires_at,
            }
        )
        return {
            "url": invite_url(PUBLIC_WEB_BASE_URL, "skill", token),
            "token": token,
            "expiresAt": expires_at,
        }

    def import_share(self, user_id: str, token: str) -> dict:
        if not isinstance(token, str) or len(token) > 128:
            raise CatalogError("Skill share link is invalid")
        share = self.table.get_item(Key={"pk": f"SKILL_SHARE#{token}", "sk": "META"}, ConsistentRead=True).get("Item")
        if not share or int(share.get("expiresAt", 0)) < int(datetime.now(UTC).timestamp()):
            raise CatalogError("This skill link is invalid or expired")
        snapshot = share.get("snapshot")
        if not isinstance(snapshot, dict):
            raise CatalogError("This skill link is invalid")
        skill_id = _validate_id(snapshot.get("id"), "skill id")
        version = int(snapshot.get("version", 0))
        if not self.get_version(skill_id, version):
            raise CatalogError("This skill version is no longer available")
        listing = {
            **snapshot,
            "editable": False,
            "relationship": "installed",
            "updatedAt": _now(),
        }
        listing.pop("instructions", None)
        self.table.put_item(
            Item={"pk": f"USER#{user_id}", "sk": f"SKILL#{skill_id}", "entity": "USER_SKILL", **listing}
        )
        return self.get_skill(user_id, skill_id)

    def install_snapshot(self, user_id: str, snapshot: dict) -> None:
        skill_id = _validate_id(snapshot.get("id"), "skill id")
        version = int(snapshot.get("version", 0))
        if self._accessible_listing(user_id, skill_id):
            return
        if not self.get_version(skill_id, version):
            raise CatalogError("A shared skill version is no longer available")
        listing = {**snapshot, "editable": False, "relationship": "installed", "updatedAt": _now()}
        listing.pop("instructions", None)
        self.table.put_item(
            Item={"pk": f"USER#{user_id}", "sk": f"SKILL#{skill_id}", "entity": "USER_SKILL", **listing}
        )

    def resolve_for_runtime(self, skill_versions: Any) -> list[dict]:
        if not isinstance(skill_versions, dict):
            return []
        resolved = []
        for skill_id, version in list(skill_versions.items())[:MAX_SKILLS_PER_BOT]:
            if not isinstance(skill_id, str) or not isinstance(version, (int, float, Decimal)):
                continue
            item = self.get_version(skill_id, int(version))
            if not item:
                raise CatalogError(f"Skill version is unavailable: {skill_id} v{int(version)}")
            resolved.append(
                {
                    "id": item["id"],
                    "version": int(item["version"]),
                    "name": item["name"],
                    "description": item["description"],
                    "instructions": item["instructions"],
                    "requiredToolIds": item.get("requiredToolIds", []),
                }
            )
        return resolved
