from __future__ import annotations

import json
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from boto3.dynamodb.conditions import Attr
from shared.schedules import (
    DAYS_OF_WEEK,
    delete_remote_schedule,
    schedule_expression,
    scheduler_name,
)

from .attachments import _public_file
from .bots import _get_bot, _list_turns
from .support import (
    QUEUE_ARN,
    SCHEDULE_DLQ_ARN,
    SCHEDULE_GROUP_NAME,
    SCHEDULE_LIMIT,
    SCHEDULE_ROLE_ARN,
    ApiError,
    _now,
    _partition_items,
    _public_schedule,
    _schedule_key,
    _user_pk,
    _validate_string,
    scheduler,
    table,
)


def _schedule_items(user_id: str, bot_id: str | None = None) -> list[dict]:
    items = _partition_items(_user_pk(user_id), "SCHEDULE#")
    if bot_id is not None:
        items = [item for item in items if item.get("botId") == bot_id and not item.get("groupId")]
    return sorted(items, key=lambda item: item.get("createdAt", ""), reverse=True)


def _get_schedule(user_id: str, bot_id: str, schedule_id: str) -> dict:
    item = table.get_item(
        Key=_schedule_key(user_id, schedule_id), ConsistentRead=True
    ).get("Item")
    if not item or item.get("botId") != bot_id or item.get("groupId"):
        raise ApiError(404, "Scheduled task not found")
    return item


def _schedule_values(value: dict, previous: dict | None = None) -> dict:
    prior = previous or {}
    frequency = value.get("frequency", prior.get("frequency", "daily"))
    if frequency not in {"daily", "weekdays", "weekly", "monthly"}:
        raise ApiError(400, "Choose a supported schedule frequency")

    time_value = _validate_string(
        value.get("time", prior.get("time", "09:00")), "time", 5
    )
    parts = time_value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ApiError(400, "Enter a valid time")
    hour, minute = (int(part) for part in parts)
    if hour > 23 or minute > 59:
        raise ApiError(400, "Enter a valid time")

    timezone = _validate_string(
        value.get("timezone", prior.get("timezone", "UTC")), "timezone", 64
    )
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ApiError(400, "Choose a valid timezone") from exc

    enabled = value.get("enabled", prior.get("enabled", True))
    if not isinstance(enabled, bool):
        raise ApiError(400, "enabled must be true or false")

    values = {
        "name": _validate_string(value.get("name", prior.get("name")), "name", 64),
        "prompt": _validate_string(
            value.get("prompt", prior.get("prompt")), "prompt", 8_000
        ),
        "frequency": frequency,
        "time": f"{hour:02d}:{minute:02d}",
        "timezone": timezone,
        "enabled": enabled,
    }
    if frequency == "weekly":
        day_of_week = value.get("dayOfWeek", prior.get("dayOfWeek", "MON"))
        if day_of_week not in DAYS_OF_WEEK:
            raise ApiError(400, "Choose a valid day of the week")
        values["dayOfWeek"] = day_of_week
    if frequency == "monthly":
        day_of_month = value.get("dayOfMonth", prior.get("dayOfMonth", 1))
        if (
            not isinstance(day_of_month, int)
            or isinstance(day_of_month, bool)
            or not 1 <= day_of_month <= 28
        ):
            raise ApiError(400, "dayOfMonth must be between 1 and 28")
        values["dayOfMonth"] = day_of_month
    return values


def _schedule_target(item: dict) -> dict:
    return {
        "Arn": QUEUE_ARN,
        "RoleArn": SCHEDULE_ROLE_ARN,
        "Input": json.dumps(
            {
                "type": "SCHEDULED_GROUP_ROUND" if item.get("groupId") else "SCHEDULED_AGENT_REPLY",
                "userId": item["userId"],
                "botId": item["botId"],
                **({"groupId": item["groupId"]} if item.get("groupId") else {}),
                "scheduleId": item["id"],
                "executionId": "<aws.scheduler.execution-id>",
                "scheduledTime": "<aws.scheduler.scheduled-time>",
            },
            separators=(",", ":"),
        ),
        "DeadLetterConfig": {"Arn": SCHEDULE_DLQ_ARN},
        "RetryPolicy": {
            "MaximumEventAgeInSeconds": 3_600,
            "MaximumRetryAttempts": 3,
        },
    }


def _remote_schedule_request(item: dict) -> dict:
    return {
        "Name": item["schedulerName"],
        "GroupName": SCHEDULE_GROUP_NAME,
        "Description": "Runs a recurring FroggyBot task.",
        "ScheduleExpression": schedule_expression(
            item["frequency"],
            item["time"],
            item.get("dayOfWeek"),
            item.get("dayOfMonth"),
        ),
        "ScheduleExpressionTimezone": item["timezone"],
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "State": "ENABLED" if item["enabled"] else "DISABLED",
        "Target": _schedule_target(item),
    }


def _create_remote_schedule(item: dict) -> None:
    scheduler.create_schedule(**_remote_schedule_request(item))


def _update_remote_schedule(item: dict) -> None:
    try:
        scheduler.update_schedule(**_remote_schedule_request(item))
    except scheduler.exceptions.ResourceNotFoundException:
        _create_remote_schedule(item)


def _delete_remote_schedule(item: dict) -> None:
    delete_remote_schedule(scheduler, SCHEDULE_GROUP_NAME, item)


def _list_schedules(user_id: str, bot_id: str) -> list[dict]:
    _get_bot(user_id, bot_id)
    return [_public_schedule(item) for item in _schedule_items(user_id, bot_id)]


def _list_schedule_runs(user_id: str, bot_id: str) -> list[dict]:
    _get_bot(user_id, bot_id)
    runs = []
    for turn in reversed(_list_turns(user_id, bot_id)):
        if turn.get("source") != "schedule":
            continue
        runs.append(
            {
                key: value
                for key, value in {
                    "id": turn.get("id"),
                    "botId": bot_id,
                    "scheduleId": turn.get("scheduleId"),
                    "scheduleName": turn.get("scheduleName", "Scheduled task"),
                    "prompt": turn.get("userText", ""),
                    "status": str(turn.get("status", "PENDING")).lower(),
                    "createdAt": turn.get("createdAt"),
                    "completedAt": turn.get("completedAt"),
                    "output": turn.get("assistantText"),
                    "activity": turn.get("activity", []),
                    "approvalTools": turn.get("approvalTools"),
                    "attachments": [
                        _public_file(item)
                        for item in turn.get("artifacts", [])
                        if isinstance(item, dict)
                    ],
                }.items()
                if value is not None
            }
        )
    return runs


def _create_schedule(user_id: str, bot_id: str, value: dict) -> dict:
    _get_bot(user_id, bot_id)
    if len(_schedule_items(user_id)) >= SCHEDULE_LIMIT:
        raise ApiError(400, f"You can create up to {SCHEDULE_LIMIT} scheduled tasks")
    schedule_id = str(uuid.uuid4())
    current = _now()
    item = {
        **_schedule_key(user_id, schedule_id),
        "entity": "SCHEDULE",
        "id": schedule_id,
        "userId": user_id,
        "botId": bot_id,
        "schedulerName": scheduler_name(user_id, schedule_id),
        "createdAt": current,
        "updatedAt": current,
        **_schedule_values(value),
    }
    table.put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
    try:
        _create_remote_schedule(item)
    except Exception:
        table.delete_item(Key=_schedule_key(user_id, schedule_id))
        raise
    return _public_schedule(item)


def _update_schedule(user_id: str, bot_id: str, schedule_id: str, value: dict) -> dict:
    _get_bot(user_id, bot_id)
    previous = _get_schedule(user_id, bot_id, schedule_id)
    item = {
        **previous,
        **_schedule_values(value, previous),
        "updatedAt": _now(),
    }
    if item["frequency"] != "weekly":
        item.pop("dayOfWeek", None)
    if item["frequency"] != "monthly":
        item.pop("dayOfMonth", None)
    table.put_item(Item=item)
    try:
        _update_remote_schedule(item)
    except Exception:
        table.put_item(Item=previous)
        raise
    return _public_schedule(item)


def _delete_schedule(user_id: str, bot_id: str, schedule_id: str) -> dict:
    item = _get_schedule(user_id, bot_id, schedule_id)
    _delete_remote_schedule(item)
    table.delete_item(Key=_schedule_key(user_id, schedule_id))
    return {"deleted": True}
