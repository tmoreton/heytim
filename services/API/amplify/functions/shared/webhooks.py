"""Bounded, user-scoped webhook storage and local routing policy."""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from decimal import Decimal
from typing import Any

MODEL_ID = "StrandsAgents/strands-decider-2B-qwen3.5-v1-2610"
MODEL_REVISION = "216d1ccb46a9e9b036eb9187b248db98480f77d4"
EFFORTS = {"low", "high", "max"}
MINIMUM_REASONING_CONFIDENCE = Decimal("0.60")
EVENT_RETENTION_SECONDS = 90 * 24 * 60 * 60
ROUTING_LEASE_SECONDS = 300
DEVICE_LEASE_SECONDS = 600
MAX_TEXT = 8_000
MAX_SOURCES = 20


class WebhookError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def identifier(value: Any, name: str = "id") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9-]{36}", value):
        raise WebhookError(400, f"{name} must be a UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except ValueError as exc:
        raise WebhookError(400, f"{name} must be a UUID") from exc
    return value


def source_key(user_id: str, source_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"WEBHOOK_SOURCE#{identifier(source_id)}"}


def owner_key(source_id: str) -> dict:
    return {"pk": f"WEBHOOK_SOURCE#{identifier(source_id)}", "sk": "OWNER"}


def event_key(user_id: str, event_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"WEBHOOK_EVENT#{identifier(event_id)}"}


def routing_device_key(user_id: str, device_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"ROUTING_DEVICE#{identifier(device_id)}"}


def partition(table: Any, user_id: str, prefix: str) -> list[dict]:
    request = {"KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
               "ExpressionAttributeValues": {":pk": f"USER#{user_id}", ":prefix": prefix},
               "ConsistentRead": True}
    items = []
    while True:
        result = table.query(**request)
        items.extend(result.get("Items", []))
        if not result.get("LastEvaluatedKey"):
            return items
        request["ExclusiveStartKey"] = result["LastEvaluatedKey"]


def get_source(table: Any, user_id: str, source_id: str, *, enabled: bool = False) -> dict:
    item = table.get_item(Key=source_key(user_id, source_id), ConsistentRead=True).get("Item")
    if not item or item.get("entity") != "WEBHOOK_SOURCE":
        raise WebhookError(404, "Webhook source not found")
    if enabled and not item.get("enabled"):
        raise WebhookError(409, "Webhook source is disabled")
    return item


def get_event(table: Any, user_id: str, event_id: str) -> dict:
    item = table.get_item(Key=event_key(user_id, event_id), ConsistentRead=True).get("Item")
    if not item or item.get("entity") != "WEBHOOK_EVENT":
        raise WebhookError(404, "Webhook event not found")
    return item


def public_source(item: dict, base_url: str = "") -> dict:
    names = ("id", "name", "kind", "allowedBotIds", "fallbackBotId", "routingMode",
             "enabled", "authentication", "textPath", "createdAt", "updatedAt", "credentialVersion")
    result = {key: item[key] for key in names if key in item}
    result["url"] = f"{base_url.rstrip('/')}/public/webhooks/incoming/{item['id']}"
    return result


def public_event(item: dict) -> dict:
    names = ("id", "sourceId", "sourceName", "text", "status", "createdAt", "recordedAt",
             "botId", "turnId", "routingDecision", "reviewReason", "isTest")
    return {key: item[key] for key in names if key in item}


def _compact_text(value: Any, byte_limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text.encode("utf-8", errors="replace")[:byte_limit].decode("utf-8", errors="ignore")


def _routing_bot(bot: dict) -> dict:
    tagline = _compact_text(bot.get("tagline"), 192) or _compact_text(bot.get("description"), 192)
    prompt = _compact_text(bot.get("prompt"), 256)
    # Keep the model's capability summary small without weakening stale-edit
    # detection: the server digest also binds the full authored routing fields.
    fields = {key: bot.get(key) for key in (
        "name", "tagline", "description", "prompt", "toolIds", "skillIds", "reasoningEffort")}
    fingerprint = hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":"),
                                            default=str).encode()).hexdigest()
    return {"id": bot["id"], "name": _compact_text(bot.get("name", "Bot"), 200),
            "description": " ".join(part for part in (tagline, prompt) if part),
            "toolIds": bot.get("toolIds", [])[:20], "skillIds": bot.get("skillIds", [])[:20],
            "reasoningEffort": bot.get("reasoningEffort", "high"), "catalogFingerprint": fingerprint}


def eligible_bots(table: Any, user_id: str, source: dict) -> list[dict]:
    allowed = source.get("allowedBotIds", [])
    bots = [bot for bot in partition(table, user_id, "BOT#")
            if bot.get("entity") == "BOT" and (not allowed or bot.get("id") in allowed)]
    return [_routing_bot(bot) for bot in bots[:100]]


def validate_choice(table: Any, user_id: str, source: dict, bot_id: Any, effort: Any) -> dict:
    if not isinstance(bot_id, str) or not any(bot["id"] == bot_id for bot in eligible_bots(table, user_id, source)):
        raise WebhookError(409, "The selected bot is no longer eligible")
    if not isinstance(effort, str) or effort not in EFFORTS:
        raise WebhookError(400, "reasoningEffort must be low, high, or max")
    return table.get_item(Key={"pk": f"USER#{user_id}", "sk": f"BOT#{bot_id}"},
                          ConsistentRead=True).get("Item", {})


def routing_source_policy(source: dict) -> dict:
    return {key: source.get(key) for key in ("routingMode", "allowedBotIds", "fallbackBotId")}


def request_digest(item: dict, bots: list[dict], source: dict | None = None) -> str:
    value = {"id": item["id"], "sourceId": item["sourceId"], "text": item["text"],
             "bots": bots, "modelId": MODEL_ID, "modelRevision": MODEL_REVISION}
    if source is not None:
        value["sourcePolicy"] = routing_source_policy(source)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def validate_routing_policy(source: dict, decision: dict) -> None:
    method = decision.get("method")
    if method not in {"local", "local_fallback", "fixed", "manual"}:
        raise WebhookError(409, "Webhook routing method is unsupported")
    if method == "manual" and "manualAttemptId" in decision:
        identifier(decision["manualAttemptId"], "manualAttemptId")
    if method in {"local", "fixed", "local_fallback"}:
        mode = "fixed" if method == "fixed" else "local"
        if source.get("routingMode") != mode:
            raise WebhookError(409, "Source routing mode changed")
    if method in {"fixed", "local_fallback"} and source.get("fallbackBotId") != decision.get("botId"):
        raise WebhookError(409, "Source fallback routing policy changed")


def routing_source_guard(user_id: str, source: dict) -> dict:
    values = {":enabled": True, ":mode": source.get("routingMode"), ":allowed": source.get("allowedBotIds", [])}
    condition = "enabled = :enabled AND routingMode = :mode AND allowedBotIds = :allowed"
    if source.get("fallbackBotId") is None:
        condition += " AND attribute_not_exists(fallbackBotId)"
    else:
        condition += " AND fallbackBotId = :fallback"
        values[":fallback"] = source["fallbackBotId"]
    return {"Key": source_key(user_id, source["id"]), "ConditionExpression": condition,
            "ExpressionAttributeValues": values}


def saved_reasoning_effort(bot: dict) -> str:
    saved = bot.get("reasoningEffort", "high")
    return saved if isinstance(saved, str) and saved in EFFORTS else "high"


def number(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise WebhookError(400, f"{name} must be between 0 and 1")
    converted = float(value)
    if not math.isfinite(converted) or not 0 <= converted <= 1:
        raise WebhookError(400, f"{name} must be between 0 and 1")
    return Decimal(str(value))


def retire_secret(catalog: Any, arn: str) -> None:
    """Secrets Manager scheduled deletion is already a successful revocation."""
    try:
        catalog._delete_secret(arn)
    except Exception as exc:
        error = getattr(exc, "response", {}).get("Error", {})
        message = str(error.get("Message", "")).lower()
        if error.get("Code") == "InvalidRequestException" and ("marked for deletion" in message or "scheduled for deletion" in message):
            return
        raise


def reasoning_decision(value: dict, bot: dict | None) -> dict:
    """Uncertain local effort classifications retain the bot's saved preference."""
    raw = value.get("reasoningEffort")
    if not isinstance(raw, str) or raw not in EFFORTS:
        raise WebhookError(400, "reasoningEffort must be low, high, or max")
    metadata = ("reasoningConfidence", "reasoningDeferred", "suggestedReasoningEffort")
    if not any(field in value for field in metadata):
        confidence, deferred, suggested = number(0, "reasoningConfidence"), True, raw
    else:
        confidence = number(value.get("reasoningConfidence"), "reasoningConfidence")
        deferred, suggested = value.get("reasoningDeferred"), value.get("suggestedReasoningEffort")
        if not isinstance(deferred, bool) or not isinstance(suggested, str) or suggested not in EFFORTS:
            raise WebhookError(400, "Reasoning decision metadata is invalid")
        if bot is not None and deferred != (confidence < MINIMUM_REASONING_CONFIDENCE):
            raise WebhookError(400, "reasoningDeferred does not match the reasoning confidence gate")
    effective = raw
    if bot is not None:
        saved = saved_reasoning_effort(bot)
        if deferred:
            if any(field in value for field in metadata) and raw != saved:
                raise WebhookError(400, "Uncertain reasoning must retain the bot's saved effort")
            effective = saved
        elif suggested != raw:
            raise WebhookError(400, "A confident reasoning choice must match its suggested effort")
    return {"reasoningEffort": effective, "reasoningConfidence": confidence,
            "reasoningDeferred": deferred, "suggestedReasoningEffort": suggested}


def validate_text_path(value: Any) -> str | None:
    """A bounded sequence of literal object keys, never an expression."""
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 520:
        raise WebhookError(400, "textPath must contain up to eight dot-separated object keys")
    import unicodedata
    keys = value.split(".")
    if not 1 <= len(keys) <= 8:
        raise WebhookError(400, "textPath must contain up to eight object keys")
    for key in keys:
        try:
            size = len(key.encode("utf-8"))
        except UnicodeError as exc:
            raise WebhookError(400, "textPath must contain valid Unicode object keys") from exc
        if (not 1 <= size <= 64 or key in {"__proto__", "prototype", "constructor"}
                or any(unicodedata.category(character).startswith("C") or character.isspace()
                       or character in "[]\\\"'" for character in key)):
            raise WebhookError(400, "textPath contains an unsupported object key")
    return value


def text_at_path(value: dict, path: str) -> str:
    current: Any = value
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise WebhookError(422, "The configured message field is missing; textPath traverses objects only")
        current = current[key]
    if not isinstance(current, str):
        raise WebhookError(422, "The configured message field must contain text")
    return current
