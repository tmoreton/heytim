from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from boto3.dynamodb.conditions import Attr

from .support import table

logger = logging.getLogger(__name__)
PRICING_VERSION = "2026-09-06"
USAGE_RETENTION_DAYS = 400
MAX_TOKEN_COUNT = 1_000_000_000_000
MAX_PROVIDER_COST_USD = Decimal(10000)
USD_QUANTUM = Decimal("0.000000000001")
TOKEN_FIELDS = (
    "inputTokens",
    "outputTokens",
    "totalTokens",
    "cacheReadInputTokens",
    "cacheWriteInputTokens",
    "reasoningTokens",
)

# Fallback estimates only. OpenRouter normally supplies the exact provider cost.
# Values are USD per one million tokens and are deliberately versioned.
MODEL_PRICING_PER_MILLION_USD = {
    "z-ai/glm-5.3-flash": {
        "inputTokens": Decimal("0.15"),
        "outputTokens": Decimal("0.50"),
        "cacheReadInputTokens": Decimal("0.03"),
    },
    "z-ai/glm-5.3": {
        "inputTokens": Decimal("1.40"),
        "outputTokens": Decimal("4.40"),
        "cacheReadInputTokens": Decimal("0.26"),
    },
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0": {
        "inputTokens": Decimal("3.00"),
        "outputTokens": Decimal("15.00"),
        "cacheReadInputTokens": Decimal("0.30"),
        "cacheWriteInputTokens": Decimal("6.00"),
    },
}


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if 0 <= value <= MAX_TOKEN_COUNT else 0


def _money(value: Any) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or not 0 <= amount <= MAX_PROVIDER_COST_USD:
        return None
    try:
        return amount.quantize(USD_QUANTUM)
    except InvalidOperation:
        return None


def _identifier(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_length:
        return None
    return cleaned


def _estimated_cost(model_id: str, model: dict[str, Any]) -> Decimal | None:
    prices = MODEL_PRICING_PER_MILLION_USD.get(model_id)
    if prices is None:
        return None
    cost = sum(
        Decimal(model.get(field, 0)) * rate for field, rate in prices.items()
    ) / Decimal(1_000_000)
    return cost.quantize(USD_QUANTUM)


def _usage_item(
    user_id: str,
    event_id: str,
    usage: dict[str, Any],
    *,
    work_type: str,
    bot_id: str,
    group_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    safe_user_id = _identifier(user_id, 128)
    safe_event_id = _identifier(event_id, 256)
    safe_work_type = _identifier(work_type, 32)
    safe_bot_id = _identifier(bot_id, 128)
    raw_models = usage.get("models")
    if (
        safe_user_id is None
        or safe_event_id is None
        or safe_work_type is None
        or safe_bot_id is None
        or not isinstance(raw_models, list)
    ):
        return None

    models: list[dict[str, Any]] = []
    totals = {field: 0 for field in TOKEN_FIELDS}
    totals["callCount"] = 0
    normalized_cost = Decimal(0)
    provider_cost = Decimal(0)
    exact_models = 0
    estimated_models = 0
    unpriced_models = 0

    for raw_model in raw_models[:8]:
        if not isinstance(raw_model, dict):
            continue
        provider = _identifier(raw_model.get("provider"), 32)
        model_id = _identifier(raw_model.get("modelId"), 256)
        if provider is None or model_id is None:
            continue
        model = {
            "provider": provider,
            "modelId": model_id,
            "callCount": _count(raw_model.get("callCount")),
        }
        for field in TOKEN_FIELDS:
            value = _count(raw_model.get(field))
            model[field] = value
            totals[field] += value
        totals["callCount"] += model["callCount"]

        exact_cost = _money(raw_model.get("providerCostUsd"))
        if exact_cost is not None:
            model["costUsd"] = exact_cost
            model["costBasis"] = "provider_reported"
            provider_cost += exact_cost
            normalized_cost += exact_cost
            exact_models += 1
        else:
            estimate = _estimated_cost(model_id, model)
            if estimate is None:
                model["costBasis"] = "unpriced"
                unpriced_models += 1
            else:
                model["costUsd"] = estimate
                model["costBasis"] = "estimated"
                normalized_cost += estimate
                estimated_models += 1
        models.append(model)

    if not models:
        return None

    recorded_at = (now or datetime.now(UTC)).astimezone(UTC)
    timestamp = recorded_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    month = recorded_at.strftime("%Y-%m")
    if unpriced_models:
        cost_basis = "partial"
    elif exact_models and estimated_models:
        cost_basis = "mixed"
    elif exact_models:
        cost_basis = "provider_reported"
    else:
        cost_basis = "estimated"

    item: dict[str, Any] = {
        "pk": f"USER#{safe_user_id}",
        "sk": f"USAGE#{safe_event_id}",
        "entity": "USAGE",
        "id": safe_event_id,
        "usageMonth": month,
        "workType": safe_work_type,
        "botId": safe_bot_id,
        "models": models,
        **totals,
        "costUsd": normalized_cost.quantize(USD_QUANTUM),
        "providerReportedCostUsd": provider_cost.quantize(USD_QUANTUM),
        "costBasis": cost_basis,
        "costIncomplete": unpriced_models > 0,
        "pricingVersion": PRICING_VERSION,
        "createdAt": timestamp,
        "expiresAt": int(
            (recorded_at + timedelta(days=USAGE_RETENTION_DAYS)).timestamp()
        ),
    }
    safe_group_id = _identifier(group_id, 128)
    if safe_group_id is not None:
        item["groupId"] = safe_group_id
    return item


def record_invocation_usage(
    user_id: str,
    event_id: str,
    usage: dict[str, Any] | None,
    *,
    work_type: str,
    bot_id: str,
    group_id: str | None = None,
) -> bool:
    """Store one idempotent usage event without letting telemetry fail a reply."""
    if not isinstance(usage, dict):
        return False
    item = _usage_item(
        user_id,
        event_id,
        usage,
        work_type=work_type,
        bot_id=bot_id,
        group_id=group_id,
    )
    if item is None:
        return False
    try:
        table.put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    except Exception:
        logger.exception("Could not record usage event %s", event_id)
        return False
    return True
