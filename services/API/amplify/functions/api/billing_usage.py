from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from boto3.dynamodb.conditions import Key

from .support import table


def _usage_count(value: Any) -> int:
    if (
        isinstance(value, Decimal)
        and value.is_finite()
        and value == value.to_integral_value()
    ):
        value = int(value)
    return value if type(value) is int and value >= 0 else 0


def _usage_cost(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)
    return amount if amount.is_finite() and amount >= 0 else Decimal(0)


def _usage_period_start(entitlement: Any, current: datetime) -> datetime:
    if entitlement.plan == "plus":
        start_epoch = int(entitlement.period_key.split(":", 1)[1])
        return datetime.fromtimestamp(start_epoch, UTC)
    return datetime(current.year, current.month, 1, tzinfo=UTC)


def _cache_coverage(item: dict[str, Any]) -> tuple[bool, bool, bool]:
    """Return whether model usage exists, cache data exists, and all calls report it."""
    raw_models = item.get("models")
    models = [
        model for model in raw_models
        if isinstance(model, dict) and model.get("provider") != "openrouter_image"
    ] if isinstance(raw_models, list) else []
    if not models:
        return False, False, True
    model_calls = sum(
        _usage_count(model.get("callCount"))
        for model in models if isinstance(model, dict)
    )
    cached_tokens = any(
        _usage_count(model.get("cacheReadInputTokens")) > 0
        for model in models if isinstance(model, dict)
    )
    calls = item.get("calls")
    calls = [call for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []
    reported = any(call.get("cacheReportAvailable") is True for call in calls)
    complete = (
        bool(calls)
        and len(calls) >= max(1, model_calls)
        and all(call.get("cacheReportAvailable") is True for call in calls)
    )
    return True, reported or cached_tokens, complete


def _usage_totals(user_id: str, entitlement: Any, current: datetime) -> dict[str, Any]:
    """Sum one recorded event per invocation across every bot and work type."""
    start = _usage_period_start(entitlement, current)
    end = datetime.fromisoformat(entitlement.resets_at.replace("Z", "+00:00"))
    input_tokens = output_tokens = cache_read_tokens = 0
    cache_write_tokens = reasoning_tokens = 0
    cost = Decimal(0)
    estimated = incomplete = False
    image_cost_incomplete = token_incomplete = False
    image_tokens = 0
    any_cache_usage = any_cache_report = False
    all_cache_complete = True
    query_args: dict[str, Any] = {
        "KeyConditionExpression": (
            Key("pk").eq(f"USER#{user_id}") & Key("sk").begins_with("USAGE#")
        ),
        "ProjectionExpression": (
            "#createdAt,#models,#calls,#tools,#costUsd,#costBasis,"
            "#costIncomplete,#imageCostIncomplete,#tokenIncomplete"
        ),
        "ExpressionAttributeNames": {
            "#createdAt": "createdAt",
            "#models": "models",
            "#calls": "calls",
            "#tools": "tools",
            "#costUsd": "costUsd",
            "#costBasis": "costBasis",
            "#costIncomplete": "costIncomplete",
            "#imageCostIncomplete": "imageCostIncomplete",
            "#tokenIncomplete": "tokenIncomplete",
        },
        "ConsistentRead": True,
    }
    while True:
        page = table.query(**query_args)
        for item in page.get("Items", []):
            recorded_at = item.get("createdAt")
            if not isinstance(recorded_at, str):
                continue
            try:
                recorded = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if recorded.tzinfo is None or not start <= recorded.astimezone(UTC) < end:
                continue

            cost += _usage_cost(item.get("costUsd"))
            incomplete |= (
                item.get("costIncomplete") is True
                or item.get("costBasis") == "partial"
            )
            estimated |= item.get("costBasis") in {"estimated", "mixed"}
            tools = item.get("tools")
            image_dispatches = sum(
                _usage_count(tool.get("callCount"))
                for tool in tools if isinstance(tool, dict)
                and tool.get("provider") == "openrouter"
                and tool.get("operation") in {"generate_image", "create_youtube_thumbnail"}
            ) if isinstance(tools, list) else 0
            raw_models = item.get("models")
            image_models = [
                model for model in raw_models
                if isinstance(model, dict) and model.get("provider") == "openrouter_image"
            ] if isinstance(raw_models, list) else []
            unreported_image = image_dispatches > sum(
                _usage_count(model.get("callCount")) for model in image_models
            )
            image_cost_flag = item.get("imageCostIncomplete")
            unpriced_image = (
                image_cost_flag if type(image_cost_flag) is bool
                else unreported_image
                or any(model.get("costBasis") == "unpriced" for model in image_models)
            )
            image_cost_incomplete |= unpriced_image
            incomplete |= unpriced_image
            token_flag = item.get("tokenIncomplete")
            token_incomplete |= (
                token_flag if type(token_flag) is bool
                else unreported_image
                or any(model.get("tokenReportAvailable") is not True for model in image_models)
            )
            has_usage, has_report, complete_report = _cache_coverage(item)
            any_cache_usage |= has_usage
            any_cache_report |= has_report
            all_cache_complete &= complete_report
            models = item.get("models")
            if not isinstance(models, list):
                continue
            for model in models:
                if not isinstance(model, dict):
                    continue
                prompt = _usage_count(model.get("inputTokens"))
                output = _usage_count(model.get("outputTokens"))
                cache_read = _usage_count(model.get("cacheReadInputTokens"))
                cache_write = _usage_count(model.get("cacheWriteInputTokens"))
                # OpenRouter includes cached tokens in prompt tokens; Bedrock
                # reports them separately. Reasoning tokens are part of output.
                if model.get("provider") == "bedrock":
                    normalized_input = prompt + cache_read + cache_write
                else:
                    normalized_input = prompt
                    cache_read = min(cache_read, prompt)
                    cache_write = min(cache_write, prompt - cache_read)
                input_tokens += normalized_input
                output_tokens += output
                if model.get("provider") == "openrouter_image":
                    image_tokens += normalized_input + output
                cache_read_tokens += cache_read
                cache_write_tokens += cache_write
                reasoning_tokens += min(
                    _usage_count(model.get("reasoningTokens")), output
                )
                estimated |= model.get("costBasis") == "estimated"

        last_key = page.get("LastEvaluatedKey")
        if not last_key:
            break
        query_args["ExclusiveStartKey"] = last_key

    return {
        "periodStart": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "periodEnd": entitlement.resets_at,
        "totalCostUsd": format(cost, "f"),
        "totalTokens": input_tokens + output_tokens,
        "imageTokens": image_tokens,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cacheReadInputTokens": cache_read_tokens,
        "cacheWriteInputTokens": cache_write_tokens,
        "reasoningTokens": reasoning_tokens,
        "costEstimated": estimated,
        "costIncomplete": incomplete,
        "imageCostIncomplete": image_cost_incomplete,
        "tokenIncomplete": token_incomplete,
        "cacheCoverage": (
            "complete" if not any_cache_usage or all_cache_complete
            else "partial" if any_cache_report else "unavailable"
        ),
    }
