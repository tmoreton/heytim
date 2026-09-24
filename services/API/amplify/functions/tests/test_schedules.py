from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from api_test_case import ApiTestCase
from shared.schedules import occurrence_time, schedule_expression, scheduled_turn_id


class ScheduleTests(unittest.TestCase):
    def test_builds_supported_recurring_cron_expressions(self) -> None:
        self.assertEqual(schedule_expression("hourly", "00:00"), "cron(0 * * * ? *)")
        self.assertEqual(schedule_expression("daily", "09:30"), "cron(30 9 * * ? *)")
        self.assertEqual(
            schedule_expression("weekdays", "08:15"),
            "cron(15 8 ? * MON-FRI *)",
        )
        self.assertEqual(
            schedule_expression("weekly", "17:05", "FRI"),
            "cron(5 17 ? * FRI *)",
        )
        self.assertEqual(
            schedule_expression("monthly", "09:00", day_of_month=15),
            "cron(0 9 15 * ? *)",
        )
        with self.assertRaises(ValueError):
            schedule_expression("monthly", "09:00", day_of_month=31)

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


class ScheduleDeletionTests(ApiTestCase):
    @staticmethod
    def schedule_value(**overrides) -> dict:
        return {
            "name": "Daily brief",
            "prompt": "Summarize the most important updates.",
            "frequency": "daily",
            "time": "08:00",
            "timezone": "America/New_York",
            "enabled": True,
            **overrides,
        }

    def test_schedule_delivery_defaults_to_app_and_validates_email(self) -> None:
        values = self.schedules._schedule_values(self.schedule_value())
        self.assertEqual(values["deliveryMode"], "app")

        values = self.schedules._schedule_values(
            self.schedule_value(deliveryMode="email")
        )
        self.assertEqual(values["deliveryMode"], "email")

        with self.assertRaises(self.support.ApiError) as raised:
            self.schedules._schedule_values(
                self.schedule_value(deliveryMode="somebody@example.com")
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_email_delivery_requires_the_bots_verified_owner_address(self) -> None:
        with (
            patch.object(
                self.schedules,
                "_get_bot",
                return_value={"id": "brief", "toolIds": []},
            ),
            self.assertRaises(self.support.ApiError) as raised,
        ):
            self.schedules._create_schedule(
                "owner",
                "brief",
                self.schedule_value(deliveryMode="email"),
            )
        self.assertEqual(raised.exception.status_code, 409)

    def test_email_delivery_is_saved_for_an_email_enabled_bot(self) -> None:
        with (
            patch.object(
                self.schedules,
                "_get_bot",
                return_value={
                    "id": "brief",
                    "toolIds": [],
                    "emailToken": "abcdefghijklmnop",
                    "emailOwnerAddress": "owner@example.com",
                },
            ),
            patch.object(self.schedules, "_schedule_items", return_value=[]),
            patch.object(self.schedules.catalog, "unapproved_tools", return_value=[]),
            patch.object(self.schedules, "_create_remote_schedule") as create_remote,
        ):
            result = self.schedules._create_schedule(
                "owner",
                "brief",
                self.schedule_value(deliveryMode="email"),
            )

        self.assertEqual(result["deliveryMode"], "email")
        create_remote.assert_called_once()

    def test_run_history_reports_schedule_email_delivery(self) -> None:
        with (
            patch.object(self.schedules, "_get_bot", return_value={"id": "brief"}),
            patch.object(
                self.schedules,
                "_list_turns",
                return_value=[
                    {
                        "id": "turn-1",
                        "source": "schedule",
                        "scheduleId": "daily",
                        "scheduleName": "Daily brief",
                        "scheduleDeliveryMode": "email",
                        "emailDeliveryStatus": "sent",
                        "userText": "Summarize updates.",
                        "status": "COMPLETE",
                        "createdAt": "2026-09-24T12:00:00+00:00",
                    }
                ],
            ),
        ):
            runs = self.schedules._list_schedule_runs("owner", "brief")

        self.assertEqual(runs[0]["deliveryMode"], "email")
        self.assertEqual(runs[0]["emailStatus"], "sent")

    def test_deleting_a_task_removes_its_remote_and_saved_schedule(self) -> None:
        item = {
            **self.schedules._schedule_key("owner", "daily"),
            "id": "daily",
            "botId": "chief",
            "name": "Daily brief",
            "enabled": False,
        }
        self.data_table.put_item(Item=item)
        with (
            patch.object(self.schedules, "table", self.data_table),
            patch.object(self.schedules, "_delete_remote_schedule") as remote_delete,
        ):
            self.assertEqual(
                self.schedules._delete_schedule("owner", "chief", "daily"),
                {"deleted": True},
            )
        remote_delete.assert_called_once_with(item)
        self.assertNotIn(("USER#owner", "SCHEDULE#daily"), self.data_table.items)


if __name__ == "__main__":
    unittest.main()
