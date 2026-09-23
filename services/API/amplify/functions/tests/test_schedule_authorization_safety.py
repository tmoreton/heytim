from __future__ import annotations

from unittest.mock import patch

from api_test_case import ApiTestCase


class ScheduleAuthorizationSafetyTests(ApiTestCase):
    def test_active_schedule_requires_one_time_tool_grant(self) -> None:
        with (
            patch.object(self.schedules, "_get_bot", return_value={
                "id": "bot-1", "toolIds": ["browser"], "alwaysAllowedToolIds": []
            }),
            patch.object(self.schedules.catalog, "unapproved_tools", return_value=[
                {"id": "browser", "name": "Interactive browser"}
            ]),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.schedules._create_schedule("user-1", "bot-1", {
                "name": "Browser check", "prompt": "Check the dashboard.",
                "frequency": "daily", "time": "09:00", "timezone": "UTC", "enabled": True,
            })
        self.assertEqual(error.exception.status_code, 409)

    def test_existing_schedule_does_not_block_enabling_interactive_tool(self) -> None:
        previous = {
            "id": "bot-1", "systemRole": None,
            "createdAt": "2026-09-14T12:00:00Z",
        }
        values = {
            "name": "Mail helper", "tagline": "Prepares drafts.",
            "prompt": "Help with Gmail.", "color": "#58BEAA",
            "toolIds": ["connection_gmail"],
            "extraToolIds": ["connection_gmail"],
            "alwaysAllowedToolIds": [], "skillIds": [], "skillVersions": {},
        }
        with (
            patch.object(self.bots, "_get_bot", return_value=previous),
            patch.object(self.bots, "_bot_values", return_value=values),
            patch.object(self.bots, "_schedule_items", return_value=[{"id": "schedule-1"}]) as schedules,
            patch.object(self.bots, "_put_bot", return_value={"id": "bot-1"}) as put_bot,
        ):
            saved = self.bots._update_bot(
                "user-1", "bot-1", {"toolIds": ["connection_gmail"]}
            )
        self.assertEqual(saved, {"id": "bot-1"})
        schedules.assert_not_called()
        put_bot.assert_called_once_with(
            "user-1", values, "bot-1", None,
            expected_email_token=None, check_email_token=True,
        )

    def test_schedule_run_inbox_includes_output_and_pending_approval(self) -> None:
        turns = [
            {
                "id": "run-1", "source": "schedule", "scheduleId": "schedule-1",
                "scheduleName": "Morning priorities", "userText": "Review today.",
                "status": "AWAITING_APPROVAL", "createdAt": "2026-09-08T09:00:00Z",
                "approvalTools": ["Interactive browser"],
            },
            {"id": "chat-1", "source": "direct", "createdAt": "later"},
        ]
        with (
            patch.object(self.schedules, "_get_bot"),
            patch.object(self.schedules, "_list_turns", return_value=turns),
        ):
            runs = self.schedules._list_schedule_runs("user-1", "bot-1")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "awaiting_approval")
        self.assertEqual(runs[0]["approvalTools"], ["Interactive browser"])
