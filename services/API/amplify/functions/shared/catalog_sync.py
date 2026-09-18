from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .catalog_rules import (
    BOT_CATALOG_FIELDS,
    BOT_COLORS,
    MAX_BOT_PROMPT,
    MAX_SKILL_INSTRUCTIONS,
    MAX_SKILLS_PER_BOT,
    MAX_TOOLS_PER_BOT,
    TOOL_RISKS,
    CatalogError,
    _public_bot_template,
    _public_skill,
    _validate_catalog_metadata,
    _validate_id,
    _validate_runtime_binding,
    _validate_text,
    _validate_tool_id,
    _validate_tool_ids,
    _version_key,
)
from .time import utc_now_iso as _now

CATALOG_URL = os.environ.get(
    "CAPABILITY_CATALOG_URL",
    "https://froggybot.com/catalog.json",
)
ALLOWED_REPOSITORY = "tmoreton/frogbot-skills"
SYNC_SECONDS = 300
SYNC_LEASE_SECONDS = 180
SYNC_RETRY_SECONDS = 60
TRUSTED_CATALOG_HOST = "froggybot.com"
TRUSTED_CATALOG_PATHS = ("/catalog.json", "/skills/")
_last_sync_at = 0.0
_local_sync_delay = SYNC_SECONDS

logger = logging.getLogger(__name__)


def _trusted_catalog_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != TRUSTED_CATALOG_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not (
            parsed.path == TRUSTED_CATALOG_PATHS[0]
            or parsed.path.startswith(TRUSTED_CATALOG_PATHS[1])
        )
        or parsed.query
        or parsed.fragment
    ):
        raise CatalogError("Capability catalog URL is not trusted")
    return url


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        _trusted_catalog_url(url),
        headers={"accept": "application/json", "user-agent": "FroggyBot/1.0"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
        _trusted_catalog_url(response.geturl())
        value = json.loads(response.read(500_001).decode("utf-8"))
    if not isinstance(value, dict):
        raise CatalogError("Capability catalog must be a JSON object")
    return value


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(
        _trusted_catalog_url(url),
        headers={"accept": "text/plain", "user-agent": "FroggyBot/1.0"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
        _trusted_catalog_url(response.geturl())
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


class CatalogSyncMixin:
    def sync_official(self, *, force: bool = False) -> None:
        global _last_sync_at, _local_sync_delay
        current = time.monotonic()
        if (
            not force
            and _last_sync_at > 0
            and current - _last_sync_at < _local_sync_delay
        ):
            return

        now_epoch = int(time.time())
        metadata = self.table.get_item(
            Key={"pk": "SYSTEM#CATALOG", "sk": "METADATA"},
            ConsistentRead=True,
        ).get("Item")
        if metadata and not force and int(metadata.get("nextSyncAt", 0)) > now_epoch:
            _last_sync_at = current
            _local_sync_delay = min(
                SYNC_SECONDS, max(1, int(metadata["nextSyncAt"]) - now_epoch)
            )
            return

        lease_id = uuid.uuid4().hex
        if not self._acquire_sync_lease(now_epoch, lease_id):
            _last_sync_at = current
            _local_sync_delay = SYNC_RETRY_SECONDS
            return

        try:
            self._sync_remote()
        except (
            CatalogError,
            OSError,
            UnicodeError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ):
            logger.exception(
                "Could not refresh the capability catalog; using the last known catalog"
            )
            self._finish_sync_lease(lease_id, SYNC_RETRY_SECONDS, "RETRY")
            _local_sync_delay = SYNC_RETRY_SECONDS
        else:
            self._finish_sync_lease(lease_id, SYNC_SECONDS, "READY")
            _local_sync_delay = SYNC_SECONDS
        _last_sync_at = current

    def _acquire_sync_lease(self, now_epoch: int, lease_id: str) -> bool:
        try:
            self.table.update_item(
                Key={"pk": "SYSTEM#CATALOG", "sk": "METADATA"},
                UpdateExpression=(
                    "SET #entity = :entity, #lease_until = :lease_until, "
                    "#lease_id = :lease_id, #status = :syncing"
                ),
                ConditionExpression=(
                    "attribute_not_exists(#lease_until) OR #lease_until <= :now"
                ),
                ExpressionAttributeNames={
                    "#entity": "entity",
                    "#lease_until": "syncLeaseUntil",
                    "#lease_id": "syncLeaseId",
                    "#status": "syncStatus",
                },
                ExpressionAttributeValues={
                    ":entity": "CATALOG_METADATA",
                    ":lease_until": now_epoch + SYNC_LEASE_SECONDS,
                    ":lease_id": lease_id,
                    ":syncing": "SYNCING",
                    ":now": now_epoch,
                },
            )
            return True
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") == (
                "ConditionalCheckFailedException"
            ):
                return False
            raise

    def _finish_sync_lease(
        self, lease_id: str, refresh_after_seconds: int, status: str
    ) -> None:
        try:
            self.table.update_item(
                Key={"pk": "SYSTEM#CATALOG", "sk": "METADATA"},
                UpdateExpression=(
                    "SET #next_sync = :next_sync, #last_sync = :last_sync, "
                    "#status = :status REMOVE #lease_until, #lease_id"
                ),
                ConditionExpression="#lease_id = :lease_id",
                ExpressionAttributeNames={
                    "#next_sync": "nextSyncAt",
                    "#last_sync": "lastSyncedAt",
                    "#status": "syncStatus",
                    "#lease_until": "syncLeaseUntil",
                    "#lease_id": "syncLeaseId",
                },
                ExpressionAttributeValues={
                    ":next_sync": int(time.time()) + refresh_after_seconds,
                    ":last_sync": _now(),
                    ":status": status,
                    ":lease_id": lease_id,
                },
            )
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") != (
                "ConditionalCheckFailedException"
            ):
                raise

    def _sync_remote(self) -> None:
        catalog = _fetch_json(CATALOG_URL)
        if (
            catalog.get("schemaVersion") != 3
            or catalog.get("repository") != ALLOWED_REPOSITORY
        ):
            raise CatalogError("Capability catalog source is not trusted")
        release = catalog.get("release")
        if not isinstance(release, str) or not re.fullmatch(r"skills-v[0-9]+", release):
            raise CatalogError("Capability catalog release is invalid")
        raw_tools = catalog.get("tools")
        raw_skills = catalog.get("skills")
        raw_bots = catalog.get("bots")
        if (
            not isinstance(raw_tools, list)
            or not isinstance(raw_skills, list)
            or not isinstance(raw_bots, list)
        ):
            raise CatalogError("Capability catalog lists are invalid")

        parsed_tools = []
        for raw in raw_tools:
            if not isinstance(raw, dict):
                raise CatalogError("Capability catalog tool is invalid")
            tool_id = _validate_tool_id(raw.get("id"))
            risk = raw.get("risk")
            if risk not in TOOL_RISKS:
                raise CatalogError(f"{tool_id} must declare a supported tool risk")
            parsed_tools.append(
                {
                    "id": tool_id,
                    "name": _validate_text(raw.get("name"), "tool name", 80),
                    "description": _validate_text(
                        raw.get("description"), "tool description", 240
                    ),
                    "provider": str(raw.get("provider", "frogbot"))[:80],
                    "risk": risk,
                    "credential": str(raw.get("credential", ""))[:80],
                    "runtime": _validate_runtime_binding(raw.get("runtime")),
                    "enabled": raw.get("enabled") is True,
                    "listed": raw.get("listed", True) is True,
                    **_validate_catalog_metadata(raw, actions=True),
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
            if not isinstance(path, str) or not re.fullmatch(
                r"skills/[a-z0-9-]+/SKILL\.md", path
            ):
                raise CatalogError(f"{skill_id} path is invalid")
            document = _fetch_text(f"https://{TRUSTED_CATALOG_HOST}/{path}")
            skills.append(
                {
                    "id": skill_id,
                    "version": version,
                    "name": _validate_text(raw.get("name"), "skill name", 80),
                    "description": _validate_text(
                        raw.get("description"), "skill description", 240
                    ),
                    "requiredToolIds": _validate_tool_ids(
                        raw.get("requiredToolIds", []), tool_ids
                    ),
                    "instructions": _skill_instructions(document),
                    "source": "official",
                    "visibility": "public",
                    "editable": False,
                    "release": release,
                    **_validate_catalog_metadata(raw),
                }
            )
        if len({item["id"] for item in skills}) != len(skills):
            raise CatalogError("Capability catalog skill IDs must be unique")
        skill_ids = {item["id"] for item in skills}

        bots = []
        for raw in raw_bots:
            if not isinstance(raw, dict):
                raise CatalogError("Bot catalog entry is invalid")
            bot_id = _validate_id(raw.get("id"), "bot id")
            unsupported_fields = set(raw) - BOT_CATALOG_FIELDS
            if unsupported_fields:
                raise CatalogError(
                    f"{bot_id} has unsupported bot fields: "
                    f"{', '.join(sorted(unsupported_fields))}"
            )
            version = raw.get("version")
            if (
                not isinstance(version, int)
                or isinstance(version, bool)
                or not 1 <= version <= 1_000_000
            ):
                raise CatalogError(f"{bot_id} version is invalid")
            selected_skills = raw.get("skillIds", [])
            selected_tools = raw.get("toolIds", [])
            if (
                not isinstance(selected_skills, list)
                or len(selected_skills) > MAX_SKILLS_PER_BOT
                or any(not isinstance(item, str) for item in selected_skills)
                or len(selected_skills) != len(set(selected_skills))
                or set(selected_skills) - skill_ids
            ):
                raise CatalogError(f"{bot_id} skillIds are invalid")
            if (
                not isinstance(selected_tools, list)
                or len(selected_tools) > MAX_TOOLS_PER_BOT
                or any(not isinstance(item, str) for item in selected_tools)
                or len(selected_tools) != len(set(selected_tools))
                or set(selected_tools) - tool_ids
            ):
                raise CatalogError(f"{bot_id} toolIds are invalid")
            color = raw.get("color", "#58BEAA")
            if color not in BOT_COLORS:
                raise CatalogError(f"{bot_id} color is invalid")
            bots.append(
                {
                    "id": bot_id,
                    "version": version,
                    "name": _validate_text(raw.get("name"), "bot name", 48),
                    "tagline": _validate_text(raw.get("tagline"), "bot tagline", 120),
                    "prompt": _validate_text(
                        raw.get("prompt"), "bot prompt", MAX_BOT_PROMPT
                    ),
                    "color": color,
                    "skillIds": selected_skills,
                    "toolIds": selected_tools,
                    "source": "official",
                    **_validate_catalog_metadata(raw),
                }
            )
        if len({item["id"] for item in bots}) != len(bots):
            raise CatalogError("Bot catalog IDs must be unique")
        self._store_official(tools, skills, bots)

    def _store_official(
        self, tools: list[dict], skills: list[dict], bots: list[dict]
    ) -> None:
        current = _now()
        existing_tools = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#TOOLS", ":prefix": "TOOL#"},
        ).get("Items", [])
        existing_skills = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#SKILLS", ":prefix": "SKILL#"},
        ).get("Items", [])
        existing_bots = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#BOTS", ":prefix": "BOT#"},
        ).get("Items", [])
        tool_keys = {f"TOOL#{tool['id']}" for tool in tools}
        skill_keys = {f"SKILL#{skill['id']}" for skill in skills}
        bot_keys = {f"BOT#{bot['id']}" for bot in bots}

        def version_is_new(prefix: str, item: dict) -> bool:
            key = {"pk": f"{prefix}#{item['id']}", "sk": _version_key(item["version"])}
            existing = self.table.get_item(Key=key, ConsistentRead=True).get("Item")
            if not existing:
                return True
            metadata = {"pk", "sk", "entity", "updatedAt", "release"}
            stored_content = {k: v for k, v in existing.items() if k not in metadata}
            new_content = {k: v for k, v in item.items() if k not in metadata}
            if stored_content != new_content:
                raise CatalogError(
                    f"{prefix.lower()} {item['id']} version {item['version']} changed; "
                    "publish a new version"
                )
            return False

        new_skill_versions = {
            skill["id"] for skill in skills if version_is_new("SKILL", skill)
        }
        new_bot_versions = {
            bot["id"] for bot in bots if version_is_new("BOT_TEMPLATE", bot)
        }
        with self.table.batch_writer() as batch:
            for item in existing_tools:
                if item.get("sk") not in tool_keys:
                    batch.delete_item(Key={"pk": "SYSTEM#TOOLS", "sk": item["sk"]})
            for item in existing_skills:
                if item.get("sk") not in skill_keys:
                    batch.delete_item(Key={"pk": "SYSTEM#SKILLS", "sk": item["sk"]})
            for item in existing_bots:
                if item.get("sk") not in bot_keys:
                    batch.delete_item(Key={"pk": "SYSTEM#BOTS", "sk": item["sk"]})
            for tool in tools:
                batch.put_item(
                    Item={
                        "pk": "SYSTEM#TOOLS",
                        "sk": f"TOOL#{tool['id']}",
                        "entity": "TOOL",
                        **tool,
                        "source": "official",
                    }
                )
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
                if skill["id"] in new_skill_versions:
                    batch.put_item(Item=version)
            for bot in bots:
                listing = {
                    "pk": "SYSTEM#BOTS",
                    "sk": f"BOT#{bot['id']}",
                    "entity": "BOT_TEMPLATE_LISTING",
                    **_public_bot_template({**bot, "updatedAt": current}),
                }
                version = {
                    "pk": f"BOT_TEMPLATE#{bot['id']}",
                    "sk": _version_key(bot["version"]),
                    "entity": "BOT_TEMPLATE_VERSION",
                    **bot,
                    "updatedAt": current,
                }
                batch.put_item(Item=listing)
                if bot["id"] in new_bot_versions:
                    batch.put_item(Item=version)
