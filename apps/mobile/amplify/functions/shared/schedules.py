from __future__ import annotations

import hashlib
from datetime import UTC, datetime

DAYS_OF_WEEK = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")


def schedule_expression(
    frequency: str, time_of_day: str, day_of_week: str | None = None
) -> str:
    hour, minute = time_of_day.split(":", 1)
    if frequency == "daily":
        return f"cron({int(minute)} {int(hour)} * * ? *)"
    if frequency == "weekly" and day_of_week in DAYS_OF_WEEK:
        return f"cron({int(minute)} {int(hour)} ? * {day_of_week} *)"
    raise ValueError("Unsupported schedule cadence")


def scheduler_name(user_id: str, schedule_id: str) -> str:
    digest = hashlib.sha256(f"{user_id}:{schedule_id}".encode()).hexdigest()
    return f"frogbot-{digest[:40]}"


def occurrence_time(value: object, fallback: datetime | None = None) -> str:
    current = fallback or datetime.now(UTC)
    if not isinstance(value, str):
        return current.isoformat(timespec="milliseconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return current.isoformat(timespec="milliseconds")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds")


def scheduled_turn_id(schedule_id: str, execution_id: str) -> str:
    return hashlib.sha256(f"{schedule_id}:{execution_id}".encode()).hexdigest()[:32]
