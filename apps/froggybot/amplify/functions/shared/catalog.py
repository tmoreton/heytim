from __future__ import annotations

import os
import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from shared.invites import invite_url

from .catalog_rules import (
    MAX_SKILL_INSTRUCTIONS,
    MAX_SKILLS_PER_BOT,
    MAX_TOOLS_PER_BOT,
    CatalogError,
    _public_bot_template,
    _public_skill,
    _public_tool,
    _validate_id,
    _validate_runtime_binding,
    _validate_text,
    _validate_tool_ids,
    _version_key,
)
from .catalog_sync import CatalogSyncMixin
from .connections import ConnectionMixin
from .time import utc_now_iso as _now

PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://froggybot.com")
CATALOG_REPOSITORY_URL = "https://github.com/tmoreton/frogbot-skills"

__all__ = [
    "CatalogError",
    "CatalogService",
]


class CatalogService(CatalogSyncMixin, ConnectionMixin):
    def __init__(
        self,
        table: Any,
        secrets_manager: Any = None,
        *,
        refresh_on_read: bool = True,
    ):
        self.table = table
        self.secrets_manager = secrets_manager
        self.refresh_on_read = refresh_on_read

    def _refresh_if_enabled(self) -> None:
        if self.refresh_on_read:
            self.sync_official()

    def _official_tool_items(self) -> list[dict]:
        self._refresh_if_enabled()
        return self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#TOOLS", ":prefix": "TOOL#"},
        ).get("Items", [])

    def _official_bot_items(self) -> list[dict]:
        self._refresh_if_enabled()
        return self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#BOTS", ":prefix": "BOT#"},
        ).get("Items", [])

    def _available_tool_items(self, user_id: str | None = None) -> list[dict]:
        items = self._official_tool_items()
        if user_id:
            items.extend(self._connection_items(user_id))
        return [item for item in items if item.get("enabled", True) is True]

    def list_tools(self, user_id: str | None = None) -> list[dict]:
        return sorted(
            (
                _public_tool(item)
                for item in self._available_tool_items(user_id)
                if item.get("listed", True) is True
            ),
            key=lambda item: item["name"].lower(),
        )

    def public_catalog(self) -> dict:
        tools = self.list_tools()
        tool_ids = {tool["id"] for tool in self._available_tool_items()}
        official = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#SKILLS", ":prefix": "SKILL#"},
        ).get("Items", [])
        skills = sorted(
            (
                _public_skill(item)
                for item in official
                if set(item.get("requiredToolIds", [])).issubset(tool_ids)
            ),
            key=lambda item: (not item.get("featured", False), item["name"].lower()),
        )
        skill_ids = {skill["id"] for skill in skills}
        bots = sorted(
            (
                _public_bot_template(item)
                for item in self._official_bot_items()
                if set(item.get("skillIds", [])).issubset(skill_ids)
                and set(item.get("toolIds", [])).issubset(tool_ids)
            ),
            key=lambda item: (not item.get("featured", False), item["name"].lower()),
        )
        return {
            "bots": bots,
            "skills": skills,
            "tools": tools,
            "repositoryUrl": CATALOG_REPOSITORY_URL,
            "contributionUrl": f"{CATALOG_REPOSITORY_URL}/blob/main/CONTRIBUTING.md",
        }

    def list_bot_templates(self, user_id: str) -> list[dict]:
        available_skill_ids = {skill["id"] for skill in self.list_skills(user_id)}
        available_tool_ids = {
            item["id"] for item in self._available_tool_items(user_id)
        }
        return sorted(
            (
                _public_bot_template(item)
                for item in self._official_bot_items()
                if set(item.get("skillIds", [])).issubset(available_skill_ids)
                and set(item.get("toolIds", [])).issubset(available_tool_ids)
            ),
            key=lambda item: (not item.get("featured", False), item["name"].lower()),
        )

    def get_bot_template(self, template_id: str) -> dict:
        template_id = _validate_id(template_id, "bot template id")
        self._refresh_if_enabled()

        def read() -> dict | None:
            return self.table.get_item(
                Key={"pk": "SYSTEM#BOTS", "sk": f"BOT#{template_id}"},
                ConsistentRead=True,
            ).get("Item")

        item = read()
        if not item and self.refresh_on_read:
            self.sync_official(force=True)
            item = read()
        if not item:
            raise CatalogError("Bot template not found")
        return _public_bot_template(item)

    def list_skills(self, user_id: str) -> list[dict]:
        self._refresh_if_enabled()
        official = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": "SYSTEM#SKILLS", ":prefix": "SKILL#"},
        ).get("Items", [])
        library = self.table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": f"USER#{user_id}", ":prefix": "SKILL#"},
        ).get("Items", [])
        available_tool_ids = {
            item["id"] for item in self._available_tool_items(user_id)
        }
        by_id = {
            item["id"]: _public_skill(item)
            for item in official + library
            if isinstance(item.get("id"), str)
            and set(item.get("requiredToolIds", [])).issubset(available_tool_ids)
        }
        return sorted(
            by_id.values(),
            key=lambda item: (item.get("source") != "official", item["name"].lower()),
        )

    def _accessible_listing(self, user_id: str, skill_id: str) -> dict | None:
        official = self.table.get_item(
            Key={"pk": "SYSTEM#SKILLS", "sk": f"SKILL#{skill_id}"}, ConsistentRead=True
        ).get("Item")
        if official:
            return official
        return self.table.get_item(
            Key={"pk": f"USER#{user_id}", "sk": f"SKILL#{skill_id}"},
            ConsistentRead=True,
        ).get("Item")

    def validate_and_pin(
        self, user_id: str, skill_ids: Any, existing: dict | None = None
    ) -> dict[str, int]:
        if not isinstance(skill_ids, list) or not all(
            isinstance(item, str) for item in skill_ids
        ):
            raise CatalogError("skillIds must be a list")
        unique = list(dict.fromkeys(skill_ids))
        if len(unique) > MAX_SKILLS_PER_BOT:
            raise CatalogError(f"A bot can use at most {MAX_SKILLS_PER_BOT} skills")
        existing = existing or {}
        available_tool_ids = {
            item["id"] for item in self._available_tool_items(user_id)
        }
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
                int(old_version)
                if isinstance(old_version, (int, float, Decimal))
                else int(listing["version"])
            )
            if not self.get_version(skill_id, pinned[skill_id]):
                pinned[skill_id] = int(listing["version"])
        return pinned

    def validate_tools(self, user_id: str, tool_ids: Any) -> list[str]:
        if not isinstance(tool_ids, list) or not all(
            isinstance(item, str) for item in tool_ids
        ):
            raise CatalogError("toolIds must be a list")
        unique = list(dict.fromkeys(tool_ids))
        allowed = {item["id"] for item in self._available_tool_items(user_id)}
        unknown = set(unique) - allowed
        if unknown:
            raise CatalogError(f"Unknown tools: {', '.join(sorted(unknown))}")
        if len(unique) > MAX_TOOLS_PER_BOT:
            raise CatalogError(f"A bot can use at most {MAX_TOOLS_PER_BOT} tools")
        return unique

    def resolve_tools_for_runtime(self, user_id: str, tool_ids: Any) -> list[dict]:
        selected = self.validate_tools(user_id, tool_ids)
        items = self._available_tool_items(user_id)
        by_id = {item.get("id"): item for item in items}
        resolved = []
        for tool_id in selected:
            item = by_id.get(tool_id)
            if not item:
                raise CatalogError(f"Tool is unavailable: {tool_id}")
            risk = item.get("risk")
            if risk not in {"read", "sandbox", "interactive"}:
                raise CatalogError(f"Tool risk is unavailable: {tool_id}")
            resolved.append(
                {
                    "id": tool_id,
                    "risk": risk,
                    "runtime": _validate_runtime_binding(item.get("runtime")),
                }
            )
        return resolved

    def approval_tools(self, user_id: str, tool_ids: Any) -> list[dict]:
        selected = set(self.validate_tools(user_id, tool_ids))
        return [
            {"id": item["id"], "name": item["name"]}
            for item in self.list_tools(user_id)
            if item["id"] in selected and item.get("risk") == "interactive"
        ]

    def approval_tool_names(self, user_id: str, tool_ids: Any) -> list[str]:
        return [item["name"] for item in self.approval_tools(user_id, tool_ids)]

    def approval_tool_ids(self, user_id: str, tool_ids: Any) -> list[str]:
        return [item["id"] for item in self.approval_tools(user_id, tool_ids)]

    def unapproved_tools(
        self, user_id: str, tool_ids: Any, always_allowed_tool_ids: Any
    ) -> list[dict]:
        allowed = (
            set(always_allowed_tool_ids)
            if isinstance(always_allowed_tool_ids, list)
            and all(isinstance(item, str) for item in always_allowed_tool_ids)
            else set()
        )
        return [
            item
            for item in self.approval_tools(user_id, tool_ids)
            if item["id"] not in allowed
        ]

    def get_version(self, skill_id: str, version: int) -> dict | None:
        return self.table.get_item(
            Key={"pk": f"SKILL#{skill_id}", "sk": _version_key(int(version))},
            ConsistentRead=True,
        ).get("Item")

    def get_skill(self, user_id: str, skill_id: str) -> dict:
        listing = self._accessible_listing(user_id, _validate_id(skill_id, "skill id"))
        if not listing:
            raise CatalogError("Skill not found")
        version = self.get_version(skill_id, int(listing["version"]))
        if not version:
            raise CatalogError("Skill version not found")
        return {**_public_skill(listing), "instructions": version["instructions"]}

    def save_skill(
        self, user_id: str, value: dict, skill_id: str | None = None
    ) -> dict:
        name = _validate_text(value.get("name"), "name", 80)
        description = _validate_text(value.get("description"), "description", 240)
        instructions = _validate_text(
            value.get("instructions"), "instructions", MAX_SKILL_INSTRUCTIONS
        )
        required_tools = _validate_tool_ids(
            value.get("requiredToolIds", []),
            {item["id"] for item in self._available_tool_items(user_id)},
        )
        visibility = value.get("visibility", "private")
        if visibility not in {"private", "link"}:
            raise CatalogError("visibility must be private or link")
        current = _now()

        if skill_id:
            skill_id = _validate_id(skill_id, "skill id")
            listing = self._accessible_listing(user_id, skill_id)
            if (
                not listing
                or listing.get("ownerId") != user_id
                or not listing.get("editable")
            ):
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
            batch.put_item(
                Item={
                    "pk": f"SKILL#{skill_id}",
                    "sk": "META",
                    "entity": "SKILL_META",
                    **common,
                }
            )
            batch.put_item(
                Item={
                    "pk": f"USER#{user_id}",
                    "sk": f"SKILL#{skill_id}",
                    "entity": "USER_SKILL",
                    **common,
                }
            )
        return {**_public_skill(common), "instructions": instructions}

    def create_share(self, user_id: str, skill_id: str) -> dict:
        skill = self.get_skill(user_id, skill_id)
        private_tool_ids = {
            connection["id"] for connection in self.list_connections(user_id)
        }
        if private_tool_ids.intersection(skill.get("requiredToolIds", [])):
            raise CatalogError(
                "Remove private connections from this skill before sharing it"
            )
        token = secrets.token_urlsafe(18)
        created_at = _now()
        expires_at = int(datetime.now(UTC).timestamp()) + 30 * 24 * 60 * 60
        self.table.put_item(
            Item={
                "pk": f"SKILL_SHARE#{token}",
                "sk": "META",
                "entity": "SKILL_SHARE",
                "ownerId": user_id,
                "snapshot": skill,
                "createdAt": created_at,
                "expiresAt": expires_at,
            }
        )
        return {
            "url": invite_url(PUBLIC_WEB_BASE_URL, "skill", token),
            "token": token,
            "createdAt": created_at,
            "expiresAt": expires_at,
        }

    def import_share(self, user_id: str, token: str) -> dict:
        if not isinstance(token, str) or len(token) > 128:
            raise CatalogError("Skill share link is invalid")
        share = self.table.get_item(
            Key={"pk": f"SKILL_SHARE#{token}", "sk": "META"}, ConsistentRead=True
        ).get("Item")
        if not share or int(share.get("expiresAt", 0)) < int(
            datetime.now(UTC).timestamp()
        ):
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
            Item={
                "pk": f"USER#{user_id}",
                "sk": f"SKILL#{skill_id}",
                "entity": "USER_SKILL",
                **listing,
            }
        )
        return self.get_skill(user_id, skill_id)

    def install_snapshot(self, user_id: str, snapshot: dict) -> None:
        skill_id = _validate_id(snapshot.get("id"), "skill id")
        version = int(snapshot.get("version", 0))
        if self._accessible_listing(user_id, skill_id):
            return
        if not self.get_version(skill_id, version):
            raise CatalogError("A shared skill version is no longer available")
        listing = {
            **snapshot,
            "editable": False,
            "relationship": "installed",
            "updatedAt": _now(),
        }
        listing.pop("instructions", None)
        self.table.put_item(
            Item={
                "pk": f"USER#{user_id}",
                "sk": f"SKILL#{skill_id}",
                "entity": "USER_SKILL",
                **listing,
            }
        )

    def resolve_for_runtime(self, skill_versions: Any) -> list[dict]:
        if not isinstance(skill_versions, dict):
            return []
        resolved = []
        for skill_id, version in list(skill_versions.items())[:MAX_SKILLS_PER_BOT]:
            if not isinstance(skill_id, str) or not isinstance(
                version, (int, float, Decimal)
            ):
                continue
            item = self.get_version(skill_id, int(version))
            if not item:
                raise CatalogError(
                    f"Skill version is unavailable: {skill_id} v{int(version)}"
                )
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
