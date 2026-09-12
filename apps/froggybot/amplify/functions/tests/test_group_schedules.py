from __future__ import annotations

import json
from unittest.mock import patch

from api_test_case import ApiTestCase
from worker_test_case import WorkerTestCase


class GroupScheduleApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.module = self.group_schedules
        self.addCleanup(patch.stopall)
        patch.object(self.module, "table", self.data_table).start()
        self.require_member = patch.object(self.module, "_require_group_member", return_value=({}, [])).start()
        self.team = patch.object(self.module, "_group_schedule_team", return_value=[{"botId": "chief"}]).start()
        patch.object(self.module, "_schedule_items", return_value=[]).start()
        self.create = patch.object(self.module, "_create_remote_schedule").start()
        self.update = patch.object(self.module, "_update_remote_schedule").start()
        self.draft = {"name": "Daily brief", "prompt": "Research our group's topics.", "time": "07:00", "timezone": "America/New_York"}

    def test_group_schedule_preserves_timezone_and_targets_group_job(self):
        result = self.module._save_group_schedule("owner", "work", self.draft)
        self.assertEqual(result["groupId"], "work")
        self.assertEqual(result["timezone"], "America/New_York")
        item = self.create.call_args.args[0]
        target = json.loads(self.schedules._schedule_target(item)["Input"])
        self.assertEqual(target["type"], "SCHEDULED_GROUP_ROUND")
        self.assertEqual(target["groupId"], "work")
        self.assertNotIn("prompt", target)

    def test_group_schedule_supports_hourly_tasks(self):
        result = self.module._save_group_schedule(
            "owner", "work", {**self.draft, "frequency": "hourly"}
        )
        item = self.create.call_args.args[0]
        request = self.schedules._remote_schedule_request(item)

        self.assertEqual(result["frequency"], "hourly")
        self.assertEqual(request["ScheduleExpression"], "cron(0 * * * ? *)")

    def test_cannot_update_another_groups_schedule(self):
        item = self.module._save_group_schedule("owner", "work", self.draft)
        with self.assertRaises(self.support.ApiError):
            self.module._save_group_schedule("owner", "personal", self.draft, item["id"])
        self.update.assert_not_called()

    def test_failed_remote_create_rolls_back_local_schedule(self):
        self.create.side_effect = RuntimeError("Scheduler unavailable")
        with self.assertRaises(RuntimeError):
            self.module._save_group_schedule("owner", "work", self.draft)
        self.assertFalse(self.data_table.items)

    def test_owner_required_to_read_group_schedules(self):
        self.module._list_group_schedules("member", "work")
        self.require_member.assert_called_once_with("member", "work", owner=True)

    def test_direct_route_cannot_access_group_schedule(self):
        item = self.module._save_group_schedule("owner", "work", self.draft)
        with (
            patch.object(self.schedules, "table", self.data_table),
            self.assertRaises(self.support.ApiError),
        ):
            self.schedules._get_schedule("owner", "chief", item["id"])


class ScheduledGroupWorkerTests(WorkerTestCase):
    def setUp(self):
        super().setUp()
        self.module = self.scheduled_group_job
        self.addCleanup(patch.stopall)
        patch.object(self.module, "table", self.table).start()
        patch.object(self.module, "_account_is_active", return_value=True).start()
        patch.object(self.module.catalog, "approval_tool_names", return_value=[]).start()
        self.process = patch.object(self.module, "_process_group_agent_round").start()
        for item in [
            {"pk": "GROUP#work", "sk": "META", "ownerId": "owner"},
            {"pk": "GROUP#work", "sk": "USER#owner", "name": "Owner"},
            {"pk": "USER#owner", "sk": "SCHEDULE#daily", "groupId": "work", "enabled": True, "name": "Morning", "prompt": "Work topics only"},
        ]:
            self.table.put_item(Item=item)
        for bot_id, name, role in [("chief", "Chief", "chief"), ("twitter", "Twitter Research", None)]:
            self.table.put_item(Item={"pk": "GROUP#work", "sk": f"BOT#{bot_id}", "entity": "GROUP_BOT", "botId": bot_id, "botOwnerId": "owner", "name": name, "systemRole": role})
            self.table.put_item(Item={"pk": "USER#owner", "sk": f"BOT#{bot_id}", "id": bot_id, "toolIds": []})
        self.request = {"userId": "owner", "groupId": "work", "scheduleId": "daily", "executionId": "occurrence", "scheduledTime": "2026-09-09T11:00:00Z"}

    def test_retry_reuses_round_and_never_overwrites_completed_reply(self):
        self.module._process_scheduled_group_round({}, self.request)
        first = self.process.call_args.args[1]
        replies = first["replies"]
        self.assertEqual([entry["roundRole"] for entry in replies], ["lead", "contributor", "synthesizer"])
        self.assertTrue(
            all(
                self.table.items[("GROUP#work", entry["replyKey"])]["billingUserId"]
                == "owner"
                for entry in replies
            )
        )
        key = ("GROUP#work", replies[0]["replyKey"])
        self.table.items[key].update(status="COMPLETE", text="Already researched")
        count = len(self.table.items)
        self.module._process_scheduled_group_round({}, self.request)
        self.assertEqual(len(self.table.items), count)
        self.assertEqual(self.table.items[key]["text"], "Already researched")
        self.assertEqual(self.process.call_args.args[1]["messageId"], first["messageId"])

    def test_paused_schedule_does_not_start_but_manual_run_does(self):
        self.table.items[("USER#owner", "SCHEDULE#daily")]["enabled"] = False
        self.module._process_scheduled_group_round({}, self.request)
        self.process.assert_not_called()
        self.module._process_scheduled_group_round({}, {**self.request, "manual": True})
        self.process.assert_called_once()

    def test_missing_membership_stops_execution(self):
        self.table.items.pop(("GROUP#work", "USER#owner"))
        self.module._process_scheduled_group_round({}, self.request)
        self.process.assert_not_called()

    def test_forged_group_id_cannot_run_another_groups_task(self):
        self.module._process_scheduled_group_round({}, {**self.request, "groupId": "personal"})
        self.process.assert_not_called()

    def test_invalid_time_is_rejected_instead_of_creating_new_retry_identity(self):
        with self.assertRaises(ValueError):
            self.module._process_scheduled_group_round({}, {**self.request, "scheduledTime": "not-a-date"})
        self.process.assert_not_called()

    def test_tool_policy_is_rechecked_at_execution(self):
        self.module.catalog.approval_tool_names.return_value = ["GitHub write"]
        with self.assertRaises(ValueError):
            self.module._process_scheduled_group_round({}, self.request)
        self.process.assert_not_called()

    def test_completed_notified_reply_still_finishes_a_retried_round(self):
        self.table.put_item(Item={
            "pk": "GROUP#work", "sk": "MESSAGE#reply", "id": "reply",
            "status": "COMPLETE", "text": "Final brief", "botOwnerId": "owner",
            "billingUserId": "owner", "notificationQueued": True,
        })
        with (
            patch.object(self.group_job, "table", self.table),
            patch.object(self.group_job, "_account_is_active", return_value=True),
            patch.object(self.group_job, "_queue_group_reply_notifications") as notify,
            patch.object(self.group_job, "_invoke") as invoke,
        ):
            answer = self.group_job._process_group_agent_reply({}, {
                "groupId": "work", "botId": "chief", "botOwnerId": "owner",
                "replyKey": "MESSAGE#reply",
            })
        self.assertEqual(answer, "Final brief")
        notify.assert_not_called()
        invoke.assert_not_called()
