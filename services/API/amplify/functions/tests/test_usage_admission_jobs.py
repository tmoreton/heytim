from __future__ import annotations

from unittest.mock import patch

from worker_test_case import WorkerTestCase


class UsageAdmissionJobTests(WorkerTestCase):
    def test_group_round_uses_persisted_billing_identity_and_full_weight(self) -> None:
        reply = {
            "pk": "GROUP#work",
            "sk": "MESSAGE#now#reply-1",
            "id": "reply-1",
            "status": "PENDING",
            "botOwnerId": "bot-owner",
            "billingUserId": "billing-user",
            "roundId": "message-1",
            "roundPosition": 1,
            "roundSize": 3,
            "roundRole": "lead",
        }
        bot = {"id": "chief", "name": "Chief", "toolIds": []}
        self.table.items[(reply["pk"], reply["sk"])] = reply
        self.table.items[("USER#bot-owner", "BOT#chief")] = bot
        result = self.agent.AgentInvocationResult(text="Done")
        allowed = self.usage_controls.AdmissionDecision(True, "admitted")

        with (
            patch.object(self.group_job, "_account_is_active", return_value=True),
            patch.object(
                self.group_job.catalog, "approval_tool_names", return_value=[]
            ),
            patch.object(self.group_job, "_claim_work", return_value="lease-1"),
            patch.object(self.group_job, "admit_run", return_value=allowed) as admit,
            patch.object(self.group_job, "_invoke", return_value=result) as invoke,
            patch.object(self.group_job, "_get_group_history", return_value=[]),
            patch.object(self.group_job, "_get_group_context", return_value={}),
            patch.object(self.group_job, "record_invocation_usage") as usage,
            patch.object(
                self.group_job, "_collect_group_generated_artifacts", return_value=[]
            ),
            patch.object(self.group_job, "_finish_work", return_value="finished"),
            patch.object(self.group_job, "_queue_group_reply_notifications"),
        ):
            answer = self.group_job._process_group_agent_reply(
                {"messageId": "queue-1"},
                {
                    "groupId": "work",
                    "botId": "chief",
                    "botOwnerId": "request-owner",
                    "requestedBy": "request-attacker",
                    "replyKey": reply["sk"],
                    "messageId": "request-message",
                    "userText": "Plan it.",
                },
            )

        self.assertEqual(answer, "Done")
        admit.assert_called_once_with(
            "billing-user", "group:work:message-1", run_units=3
        )
        self.assertEqual(invoke.call_args.kwargs["billing_user_id"], "billing-user")
        usage.assert_called_once()
        self.assertEqual(usage.call_args.args[0], "billing-user")

    def test_denied_direct_run_is_terminal_and_never_invokes_provider(self) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "userId": "user-1",
            "status": "PENDING",
            "createdAt": "now",
        }
        bot = {"id": "bot-1", "name": "Bot", "toolIds": []}
        self.table.items[(turn["pk"], turn["sk"])] = turn
        self.table.items[("USER#user-1", "BOT#bot-1")] = bot
        denied = self.usage_controls.AdmissionDecision(False, "monthly_limit")

        with (
            patch.object(self.direct_job, "_account_is_active", return_value=True),
            patch.object(self.direct_job.catalog, "unapproved_tools", return_value=[]),
            patch.object(self.direct_job, "_claim_work", return_value="lease-1"),
            patch.object(self.direct_job, "admit_run", return_value=denied),
            patch.object(self.direct_job, "_invoke") as invoke,
            patch.object(self.direct_job, "begin_attempt") as begin,
            patch.object(self.direct_job, "_delete_generated_artifacts"),
            patch.object(
                self.direct_job, "_finish_work", return_value="finished"
            ) as finish,
            patch.object(self.direct_job, "_update_schedule_result"),
            patch.object(self.direct_job, "_queue_reply_notification"),
        ):
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {"userId": "user-1", "botId": "bot-1", "turnKey": turn["sk"]},
            )

        invoke.assert_not_called()
        begin.assert_not_called()
        self.assertEqual(finish.call_args.args[2], "ERROR")
        self.assertIn("usage limit", finish.call_args.args[4])

    def test_denied_group_run_is_terminal_and_never_invokes_provider(self) -> None:
        reply = {
            "pk": "GROUP#work",
            "sk": "MESSAGE#now#reply-1",
            "id": "reply-1",
            "status": "PENDING",
            "botOwnerId": "bot-owner",
            "billingUserId": "billing-user",
            "roundId": "message-1",
            "roundSize": 3,
        }
        self.table.items[(reply["pk"], reply["sk"])] = reply
        self.table.items[("USER#bot-owner", "BOT#chief")] = {
            "id": "chief",
            "name": "Chief",
            "toolIds": [],
        }
        denied = self.usage_controls.AdmissionDecision(False, "global_rate_limit")

        with (
            patch.object(self.group_job, "_account_is_active", return_value=True),
            patch.object(
                self.group_job.catalog, "approval_tool_names", return_value=[]
            ),
            patch.object(self.group_job, "_claim_work", return_value="lease-1"),
            patch.object(self.group_job, "admit_run", return_value=denied),
            patch.object(self.group_job, "_invoke") as invoke,
            patch.object(self.group_job, "begin_attempt") as begin,
            patch.object(self.group_job, "_delete_group_generated_artifacts"),
            patch.object(
                self.group_job,
                "_finish_group_admission_denial",
                return_value="finished",
            ) as finish,
            patch.object(self.group_job, "_queue_group_reply_notifications"),
        ):
            answer = self.group_job._process_group_agent_reply(
                {"messageId": "queue-1"},
                {
                    "groupId": "work",
                    "botId": "chief",
                    "replyKey": reply["sk"],
                },
            )

        self.assertIsInstance(answer, self.group_job._AdmissionDeniedText)
        invoke.assert_not_called()
        begin.assert_not_called()
        finish.assert_called_once()

    def test_group_billing_never_falls_back_to_queue_request_or_bot_owner(self) -> None:
        reply = {
            "pk": "GROUP#work",
            "sk": "MESSAGE#now#reply-1",
            "id": "reply-1",
            "status": "PENDING",
            "botOwnerId": "bot-owner",
            "roundId": "message-1",
            "roundSize": 1,
        }
        self.table.items[(reply["pk"], reply["sk"])] = reply
        self.table.items[("USER#bot-owner", "BOT#chief")] = {
            "id": "chief",
            "name": "Chief",
            "toolIds": [],
        }

        with (
            patch.object(self.group_job, "_account_is_active", return_value=True),
            patch.object(
                self.group_job.catalog, "approval_tool_names", return_value=[]
            ),
            patch.object(self.group_job, "_claim_work", return_value="lease-1"),
            patch.object(self.group_job, "admit_run") as admit,
            patch.object(self.group_job, "_invoke") as invoke,
            patch.object(self.group_job, "_delete_group_generated_artifacts"),
            patch.object(
                self.group_job,
                "_finish_group_admission_denial",
                return_value="finished",
            ),
            patch.object(self.group_job, "_queue_group_reply_notifications"),
        ):
            answer = self.group_job._process_group_agent_reply(
                {"messageId": "queue-1"},
                {
                    "groupId": "work",
                    "botId": "chief",
                    "botOwnerId": "request-owner",
                    "requestedBy": "request-user",
                    "replyKey": reply["sk"],
                },
            )

        self.assertIsInstance(answer, self.group_job._AdmissionDeniedText)
        self.assertIn("safely authorized", answer)
        admit.assert_not_called()
        invoke.assert_not_called()

    def test_deleting_group_billing_user_stops_pending_runtime_work(self) -> None:
        reply = {
            "pk": "GROUP#work",
            "sk": "MESSAGE#now#reply-1",
            "id": "reply-1",
            "status": "PENDING",
            "botOwnerId": "bot-owner",
            "billingUserId": "deleting-user",
            "roundId": "message-1",
            "roundSize": 1,
            "pendingWork": [{"provider": "agentcore_runtime"}],
        }
        self.table.items[(reply["pk"], reply["sk"])] = reply
        self.table.items[("USER#bot-owner", "BOT#chief")] = {
            "id": "chief",
            "name": "Chief",
            "toolIds": [],
        }

        with (
            patch.object(
                self.group_job,
                "_account_is_active",
                side_effect=lambda user_id: user_id == "bot-owner",
            ),
            patch.object(self.group_job, "_claim_work", return_value="lease-1"),
            patch.object(self.group_job, "admit_run") as admit,
            patch.object(self.group_job, "_invoke") as invoke,
            patch.object(self.group_job, "_queue_background_poll") as poll,
            patch.object(self.group_job, "_delete_group_generated_artifacts"),
            patch.object(
                self.group_job,
                "_finish_group_admission_denial",
                return_value="finished",
            ),
            patch.object(self.group_job, "_queue_group_reply_notifications"),
        ):
            answer = self.group_job._process_group_agent_reply(
                {"messageId": "queue-1"},
                {
                    "groupId": "work",
                    "botId": "chief",
                    "replyKey": reply["sk"],
                },
            )

        self.assertIsInstance(answer, self.group_job._AdmissionDeniedText)
        self.assertIn("no longer active", answer)
        admit.assert_not_called()
        invoke.assert_not_called()
        poll.assert_not_called()

    def test_background_continuation_reuses_the_turn_admission_id(self) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "userId": "user-1",
            "status": "PENDING",
            "createdAt": "now",
            "backgroundResults": [{"status": "completed", "exitCode": 0}],
        }
        bot = {"id": "bot-1", "name": "Bot", "toolIds": []}
        self.table.items[(turn["pk"], turn["sk"])] = turn
        self.table.items[("USER#user-1", "BOT#bot-1")] = bot
        result = self.agent.AgentInvocationResult(text="Done")
        allowed = self.usage_controls.AdmissionDecision(True, "duplicate", True)

        with (
            patch.object(self.direct_job, "_account_is_active", return_value=True),
            patch.object(self.direct_job.catalog, "unapproved_tools", return_value=[]),
            patch.object(self.direct_job, "_claim_work", return_value="lease-1"),
            patch.object(self.direct_job, "admit_run", return_value=allowed) as admit,
            patch.object(self.direct_job, "_invoke", return_value=result),
            patch.object(self.direct_job, "record_invocation_usage"),
            patch.object(
                self.direct_job, "_collect_generated_artifacts", return_value=[]
            ),
            patch.object(self.direct_job, "_finish_work", return_value="finished"),
            patch.object(self.direct_job, "_update_schedule_result"),
            patch.object(self.direct_job, "_queue_reply_notification"),
        ):
            for queue_id in ("initial-delivery", "continuation-delivery"):
                self.direct_job._process_agent_reply(
                    {"messageId": queue_id},
                    {
                        "userId": "user-1",
                        "botId": "bot-1",
                        "turnKey": turn["sk"],
                    },
                )

        self.assertEqual(admit.call_count, 2)
        self.assertEqual(
            [call.args for call in admit.call_args_list],
            [("user-1", "direct:turn-1"), ("user-1", "direct:turn-1")],
        )

    def test_group_denial_finalizes_round_once_without_queuing_each_reply(self) -> None:
        replies = [
            {"botId": "chief", "replyKey": "MESSAGE#1"},
            {"botId": "research", "replyKey": "MESSAGE#2"},
            {"botId": "chief", "replyKey": "MESSAGE#3"},
        ]
        denial = self.group_job._AdmissionDeniedText("Usage limit reached")

        with (
            patch.object(self.group_job, "_activate_group_reply"),
            patch.object(
                self.group_job,
                "_process_group_agent_reply",
                return_value=denial,
            ) as process,
            patch.object(
                self.group_job, "_finalize_remaining_group_denials"
            ) as finalize,
        ):
            self.group_job._process_group_agent_round(
                {"messageId": "queue-1"},
                {
                    "groupId": "work",
                    "messageId": "message-1",
                    "replies": replies,
                },
            )

        process.assert_called_once()
        finalize.assert_called_once_with("work", replies, 1, "Usage limit reached")
        self.sqs.send_message.assert_not_called()

    def test_scheduled_group_denial_ends_schedule_as_error(self) -> None:
        replies = [{"botId": "chief", "replyKey": "MESSAGE#1"}]
        self.table.items[("GROUP#work", "META")] = {"ownerId": "billing-user"}
        self.table.items[("GROUP#work", "USER#billing-user")] = {
            "userId": "billing-user"
        }
        self.table.items[("GROUP#work", "BOT#chief")] = {"botId": "chief"}
        denial = self.group_job._AdmissionDeniedText("Usage limit reached")

        with (
            patch.object(self.group_job, "_account_is_active", return_value=True),
            patch.object(self.group_job, "_activate_group_reply"),
            patch.object(
                self.group_job,
                "_process_group_agent_reply",
                return_value=denial,
            ),
            patch.object(self.group_job, "_finalize_remaining_group_denials"),
            patch.object(self.group_job, "_update_schedule_result") as update,
        ):
            self.group_job._process_group_agent_round(
                {"messageId": "queue-1"},
                {
                    "groupId": "work",
                    "messageId": "message-1",
                    "requestedBy": "billing-user",
                    "scheduleId": "schedule-1",
                    "replies": replies,
                },
            )

        self.assertEqual(update.call_args.args[1], "error")
        self.sqs.send_message.assert_not_called()


if __name__ == "__main__":
    import unittest

    unittest.main()
