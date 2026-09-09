"""Private browser references; never store browser contents or bearer URLs here."""
from __future__ import annotations

import hashlib
import json
import re

from .catalog import CatalogService
from .catalog_rules import CatalogError
from .keys import bot_key, turn_pk, user_pk
from .work_state import IN_FLIGHT_STATUSES


class BrowserSessionError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def validate_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise BrowserSessionError(400, f"{field} is invalid")
    return value


def direct_only(group_id: object) -> None:
    if group_id is not None:
        raise BrowserSessionError(
            409, "Browser login is supported only in an owned bot's direct chat. "
            "Interactive tools are not supported in groups; use separate bot instances "
            "for personal and work logins.",
        )


def context_key(user_id: str, bot_id: str) -> dict:
    digest = hashlib.sha256(json.dumps([user_id, bot_id, "direct"]).encode()).hexdigest()
    return {"pk": user_pk(user_id), "sk": f"BROWSER#{digest}"}


class BrowserSessionStore:
    def __init__(self, table, user_id: str, bot_id: str, catalog=None):
        self.table = table
        self.user_id = validate_id(user_id, "userId")
        self.bot_id = validate_id(bot_id, "botId")
        self.key = context_key(user_id, bot_id)
        self.catalog = catalog

    def authorize(self, *, require_browser: bool = True) -> dict:
        bot = self.table.get_item(
            Key=bot_key(self.user_id, self.bot_id), ConsistentRead=True,
        ).get("Item")
        if not bot or bot.get("entity") != "BOT":
            raise BrowserSessionError(404, "Bot not found")
        if not require_browser:
            return bot
        catalog = self.catalog or CatalogService(self.table, refresh_on_read=False)
        try:
            versions = bot.get("skillVersions")
            if not isinstance(versions, dict):
                versions = catalog.validate_and_pin(self.user_id, bot.get("skillIds", []))
            tool_ids = list(bot.get("toolIds", []))
            for skill in catalog.resolve_for_runtime(versions):
                tool_ids.extend(skill.get("requiredToolIds", []))
            tools = catalog.resolve_tools_for_runtime(self.user_id, list(dict.fromkeys(tool_ids)))
        except CatalogError as exc:
            raise BrowserSessionError(409, "This bot's tools are unavailable") from exc
        if not any(t.get("runtime") == {"kind": "agentcore", "name": "browser"} for t in tools):
            raise BrowserSessionError(409, "Add the browser tool to this bot first")
        return bot

    def ensure_idle(self) -> None:
        # Lazy imports keep the legacy fake backend test loader compatible.
        from boto3.dynamodb.conditions import Attr, Key

        pages = self.table.meta.client.get_paginator("query").paginate(
            TableName=self.table.name,
            KeyConditionExpression=Key("pk").eq(turn_pk(self.user_id, self.bot_id)),
            FilterExpression=Attr("status").is_in(sorted(IN_FLIGHT_STATUSES)),
            ProjectionExpression="id",
            ConsistentRead=True,
        )
        if any(page.get("Items") for page in pages):
            raise BrowserSessionError(409, "Wait for the bot to finish or stop it before opening its browser")

    def read(self) -> dict:
        item = self.table.get_item(Key=self.key, ConsistentRead=True).get("Item")
        if item and (item.get("userId") != self.user_id or item.get("botId") != self.bot_id):
            raise BrowserSessionError(403, "Browser context mismatch")
        return item or {**self.key, "entity": "BROWSER_SESSION", "userId": self.user_id,
                        "botId": self.bot_id, "status": "CLOSED", "revision": 0}

    def write(self, before: dict, **changes) -> dict:
        from boto3.dynamodb.conditions import Attr

        item = {**before, **changes, "revision": int(before["revision"]) + 1}
        condition = (Attr("revision").eq(before["revision"]) if before["revision"]
                     else Attr("pk").not_exists())
        try:
            self.table.put_item(Item=item, ConditionExpression=condition)
        except self.table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise BrowserSessionError(409, "Browser state changed; refresh before trying again") from exc
        return item
