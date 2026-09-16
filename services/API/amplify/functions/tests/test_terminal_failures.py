from __future__ import annotations

from unittest.mock import patch

from worker_test_case import WorkerTestCase


class TerminalFailureTests(WorkerTestCase):
    timeout_message = "I stopped this response after five minutes."

    def _result(self):
        return self.agent.AgentInvocationResult(
            text=self.timeout_message,
            terminal_error=self.timeout_message,
        )

    def test_direct_timeout_finishes_without_queue_retry(self) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "userId": "user-1",
            "status": "PENDING",
            "createdAt": "now",
        }
        self.table.items[(turn["pk"], turn["sk"])] = turn
        self.table.items[("USER#user-1", "BOT#bot-1")] = {
            "id": "bot-1",
            "name": "Thumbnail Studio",
            "toolIds": [],
        }
        with (
            patch.object(self.direct_job, "_account_is_active", return_value=True),
            patch.object(self.direct_job.catalog, "unapproved_tools", return_value=[]),
            patch.object(self.direct_job, "_claim_work", return_value="lease-1"),
            patch.object(self.direct_job, "_invoke", return_value=self._result()),
            patch.object(self.direct_job, "record_invocation_usage"),
            patch.object(self.direct_job, "_delete_generated_artifacts") as cleanup,
            patch.object(
                self.direct_job, "_finish_work", return_value="finished-at"
            ) as finish,
            patch.object(self.direct_job, "_update_schedule_result") as schedule,
            patch.object(self.direct_job, "_queue_reply_notification") as notify,
        ):
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {"userId": "user-1", "botId": "bot-1", "turnKey": turn["sk"]},
            )

        cleanup.assert_called_once_with("user-1", "bot-1", "turn-1")
        finish.assert_called_once_with(
            {"pk": turn["pk"], "sk": turn["sk"]},
            "lease-1",
            "ERROR",
            "assistantText",
            self.timeout_message,
        )
        schedule.assert_called_once_with(turn, "error", "finished-at")
        notify.assert_called_once()

    def test_group_timeout_finishes_without_queue_retry(self) -> None:
        reply = {
            "pk": "GROUP#group-1",
            "sk": "MESSAGE#now#reply-1",
            "id": "reply-1",
            "status": "PENDING",
            "createdAt": "now",
            "botOwnerId": "owner-1",
            "billingUserId": "user-1",
            "roundId": "message-1",
            "roundSize": 1,
        }
        self.table.items[(reply["pk"], reply["sk"])] = reply
        self.table.items[("USER#owner-1", "BOT#bot-1")] = {
            "id": "bot-1",
            "name": "Thumbnail Studio",
            "toolIds": [],
        }
        with (
            patch.object(self.group_job, "_account_is_active", return_value=True),
            patch.object(self.group_job.catalog, "approval_tool_names", return_value=[]),
            patch.object(self.group_job, "_claim_work", return_value="lease-1"),
            patch.object(self.group_job, "_invoke", return_value=self._result()),
            patch.object(self.group_job, "_get_group_history", return_value=[]),
            patch.object(self.group_job, "_get_group_context", return_value={}),
            patch.object(self.group_job, "record_invocation_usage"),
            patch.object(
                self.group_job, "_delete_group_generated_artifacts"
            ) as cleanup,
            patch.object(
                self.group_job, "_finish_work", return_value="finished-at"
            ) as finish,
            patch.object(self.group_job, "_queue_group_reply_notifications") as notify,
        ):
            answer = self.group_job._process_group_agent_reply(
                {"messageId": "queue-1"},
                {
                    "groupId": "group-1",
                    "botId": "bot-1",
                    "botOwnerId": "owner-1",
                    "replyKey": reply["sk"],
                },
            )

        self.assertEqual(answer, self.timeout_message)
        cleanup.assert_called_once_with("group-1", "reply-1")
        finish.assert_called_once_with(
            {"pk": reply["pk"], "sk": reply["sk"]},
            "lease-1",
            "ERROR",
            "text",
            self.timeout_message,
        )
        notify.assert_called_once()


if __name__ == "__main__":
    import unittest

    unittest.main()
