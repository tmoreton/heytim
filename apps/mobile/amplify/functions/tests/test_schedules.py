from __future__ import annotations

import unittest
from datetime import UTC, datetime

from shared.schedules import occurrence_time, schedule_expression, scheduled_turn_id


class ScheduleTests(unittest.TestCase):
    def test_builds_daily_and_weekly_cron_expressions(self) -> None:
        self.assertEqual(schedule_expression("daily", "09:30"), "cron(30 9 * * ? *)")
        self.assertEqual(
            schedule_expression("weekly", "17:05", "FRI"),
            "cron(5 17 ? * FRI *)",
        )
        with self.assertRaises(ValueError):
            schedule_expression("monthly", "09:00")

    def test_scheduled_turn_identity_is_stable_per_execution(self) -> None:
        first = scheduled_turn_id("task-1", "execution-1")
        self.assertEqual(first, scheduled_turn_id("task-1", "execution-1"))
        self.assertNotEqual(first, scheduled_turn_id("task-1", "execution-2"))

    def test_occurrence_time_normalizes_and_falls_back(self) -> None:
        fallback = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
        self.assertEqual(
            occurrence_time("2026-09-04T08:00:00-04:00", fallback),
            "2026-09-04T12:00:00.000+00:00",
        )
        self.assertEqual(
            occurrence_time("not-a-date", fallback),
            "2026-09-04T12:00:00.000+00:00",
        )


if __name__ == "__main__":
    unittest.main()
