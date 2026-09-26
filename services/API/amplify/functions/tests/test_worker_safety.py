from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from worker_test_case import WorkerTestCase


class WorkerSafetyTests(WorkerTestCase):
    def test_shared_job_lifecycle_retries_before_terminal_failure(self) -> None:
        cleanup = MagicMock()
        attempt = self.job_lifecycle.begin_attempt(
            {"attributes": {"ApproximateReceiveCount": "2"}}, cleanup
        )

        with patch.object(self.job_lifecycle, "_release_work") as release:
            outcome = self.job_lifecycle.finish_failed_attempt(
                attempt,
                {"pk": "CHAT#1", "sk": "TURN#1"},
                "lease-1",
                "assistantText",
                "failed",
                cleanup,
            )

        cleanup.assert_called_once_with()
        release.assert_called_once()
        self.assertEqual(
            outcome.disposition, self.job_lifecycle.FailureDisposition.RETRY
        )

    def test_claim_uses_queue_message_as_lease_owner_and_allows_expired_retry(self):
        owner = self.work._claim_work(
            {"pk": "CHAT#1", "sk": "TURN#1"}, {"messageId": "queue-message-1"}
        )

        self.assertEqual(owner, "queue-message-1")
        update = self.table.updates[-1]
        self.assertIn("leaseExpiresAt < :now", update["ConditionExpression"])
        self.assertEqual(update["ExpressionAttributeValues"][":owner"], "queue-message-1")

    def test_failed_conditional_claim_is_treated_as_already_owned(self) -> None:
        self.table.fail_condition = True

        owner = self.work._claim_work(
            {"pk": "CHAT#1", "sk": "TURN#1"}, {"messageId": "queue-message-2"}
        )

        self.assertIsNone(owner)

    def test_finish_requires_the_same_active_lease(self) -> None:
        completed_at = self.work._finish_work(
            {"pk": "CHAT#1", "sk": "TURN#1"},
            "queue-message-1",
            "COMPLETE",
            "assistantText",
            "Done",
        )

        self.assertIsNotNone(completed_at)
        update = self.table.updates[-1]
        self.assertEqual(
            update["ConditionExpression"],
            "#status = :running AND leaseOwner = :owner",
        )
        self.assertEqual(update["ExpressionAttributeValues"][":owner"], "queue-message-1")

    def test_failed_attempt_releases_only_its_own_lease(self) -> None:
        released = self.work._release_work(
            {"pk": "CHAT#1", "sk": "TURN#1"}, "queue-message-1"
        )

        self.assertTrue(released)
        update = self.table.updates[-1]
        self.assertIn("REMOVE leaseOwner, leaseExpiresAt", update["UpdateExpression"])
        self.assertEqual(
            update["ConditionExpression"],
            "#status = :running AND leaseOwner = :owner",
        )

    def test_background_work_releases_the_model_lease(self) -> None:
        pending = [
            {
                "provider": "agentcore_code_interpreter",
                "resourceId": "aws.codeinterpreter.v1",
                "sessionId": "session-1",
                "taskId": "task-1",
                "label": "Run tests",
                "startedAt": datetime.now(UTC).isoformat(),
            }
        ]

        paused = self.work._pause_work(
            {"pk": "CHAT#1", "sk": "TURN#1"}, "queue-message-1", pending
        )

        self.assertTrue(paused)
        update = self.table.updates[-1]
        self.assertIn("pendingWork = :work", update["UpdateExpression"])
        self.assertIn("REMOVE leaseOwner", update["UpdateExpression"])
        self.assertEqual(update["ExpressionAttributeValues"][":work"], pending)

    def test_failed_runtime_dispatch_restores_the_active_lease(self) -> None:
        pending = [{"provider": "agentcore_runtime"}]

        restored = self.work._restore_paused_work(
            {"pk": "CHAT#1", "sk": "TURN#1"},
            "queue-message-1",
            pending,
        )

        self.assertTrue(restored)
        update = self.table.updates[-1]
        self.assertIn("REMOVE pendingWork", update["UpdateExpression"])
        self.assertEqual(
            update["ConditionExpression"],
            "#status = :pending AND pendingWork = :work",
        )
        self.assertEqual(
            update["ExpressionAttributeValues"][":owner"], "queue-message-1"
        )

    def test_completed_background_work_resumes_the_original_job(self) -> None:
        item_key = {"pk": "CHAT#1", "sk": "TURN#1"}
        pending = [
            {
                "provider": "agentcore_code_interpreter",
                "resourceId": "aws.codeinterpreter.v1",
                "sessionId": "session-1",
                "taskId": "task-1",
                "label": "Run tests",
                "startedAt": datetime.now(UTC).isoformat(),
            }
        ]
        self.table.items[(item_key["pk"], item_key["sk"])] = {
            **item_key,
            "status": "PENDING",
            "pendingWork": pending,
        }
        self.agentcore.invoke_code_interpreter.return_value = {
            "stream": iter(
                [
                    {
                        "result": {
                            "structuredContent": {
                                "taskStatus": "completed",
                                "stdout": "43 tests passed",
                                "stderr": "",
                                "exitCode": 0,
                            }
                        }
                    }
                ]
            )
        }
        resume = {"type": "AGENT_REPLY", "turnKey": "TURN#1"}

        self.background_work._process_background_work(
            {"messageId": "poll-1"},
            {
                "type": "BACKGROUND_WORK_POLL",
                "itemKey": item_key,
                "resumeRequest": resume,
            },
        )

        update = self.table.updates[-1]
        results = update["ExpressionAttributeValues"][":results"]
        self.assertEqual(results[0]["status"], "completed")
        self.assertEqual(results[0]["exitCode"], 0)
        self.sqs.send_message.assert_called_once()
        queued = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual({key: queued[key] for key in resume}, resume)
        self.assertEqual(queued["schemaVersion"], 1)

    def test_background_work_stops_polling_after_the_attempt_limit(self) -> None:
        item_key = {"pk": "CHAT#1", "sk": "TURN#1"}
        pending = [
            {
                "provider": "agentcore_code_interpreter",
                "resourceId": "aws.codeinterpreter.v1",
                "sessionId": "session-1",
                "taskId": "task-1",
                "label": "Run tests",
                "startedAt": datetime.now(UTC).isoformat(),
            }
        ]
        self.table.items[(item_key["pk"], item_key["sk"])] = {
            **item_key,
            "status": "PENDING",
            "pendingWork": pending,
        }

        self.background_work._process_background_work(
            {"messageId": "poll-final"},
            {
                "type": "BACKGROUND_WORK_POLL",
                "itemKey": item_key,
                "resumeRequest": {"type": "AGENT_REPLY", "turnKey": "TURN#1"},
                "pollCount": self.background_work.MAX_POLL_ATTEMPTS,
            },
        )

        self.agentcore.invoke_code_interpreter.assert_not_called()
        results = self.table.updates[-1]["ExpressionAttributeValues"][":results"]
        self.assertEqual(results[0]["status"], "expired")
        self.sqs.send_message.assert_called_once()

    def test_push_notification_claim_prevents_duplicate_delivery(self) -> None:
        self.table.items[("USER#user-1", "PUSH#token-1")] = {
            "pk": "USER#user-1",
            "sk": "PUSH#token-1",
            "tokenId": "token-1",
            "expoPushToken": "ExpoPushToken[value]",
            "expiresAt": int(datetime.now(UTC).timestamp()) + 60,
        }
        self.table.items[("PUSH_TOKEN#token-1", "OWNER")] = {
            "pk": "PUSH_TOKEN#token-1",
            "sk": "OWNER",
            "userId": "user-1",
        }
        request = {
            "type": "PUSH_NOTIFICATION",
            "notificationId": "direct:user-1:bot-1:turn-1",
            "userId": "user-1",
            "botId": "bot-1",
            "botName": "Helper",
            "messageId": "turn-1",
            "answer": "Done",
        }
        with patch.object(
            self.notifications,
            "_post_json",
            return_value={"data": []},
        ) as post:
            self.notifications._send_push_notification(request)
            self.notifications._send_push_notification(request)

        post.assert_called_once()

    def test_dynamodb_exit_code_is_json_safe_when_resuming(self) -> None:
        result = self.agent._continuation_payload(
            [{"status": "completed", "exitCode": Decimal(0)}]
        )

        self.assertEqual(result, [{"status": "completed", "exitCode": 0}])
        self.assertEqual(json.dumps(result), '[{"status": "completed", "exitCode": 0}]')

    def test_team_roster_uses_exact_saved_bot_names_and_roles(self) -> None:
        self.table.items[("USER#user-1", "BOT#chief")] = {
            "id": "chief",
            "name": "Chief",
            "tagline": "Coordinates the team.",
        }
        self.table.items[("USER#user-1", "BOT#research")] = {
            "id": "research",
            "name": "Research & Reports",
            "tagline": "Checks data and writes reports.",
        }

        roster = self.agent._team_roster("user-1", "chief")

        self.assertEqual(
            roster,
            [
                {
                    "name": "Chief",
                    "tagline": "Coordinates the team.",
                    "isCurrent": True,
                },
                {
                    "name": "Research & Reports",
                    "tagline": "Checks data and writes reports.",
                    "isCurrent": False,
                },
            ],
        )

    def test_failed_job_is_made_visible_for_a_fast_retry(self) -> None:
        record = {
            "messageId": "queue-message-1",
            "receiptHandle": "receipt-1",
            "body": "{}",
        }
        with (
            self.assertLogs(self.handler.logger, level="ERROR") as logs,
            patch.object(self.handler, "_process", side_effect=RuntimeError("nope")),
        ):
            response = self.handler.handler({"Records": [record]}, None)

        self.assertEqual(
            response, {"batchItemFailures": [{"itemIdentifier": "queue-message-1"}]}
        )
        self.assertIn("Job failed for message queue-message-1", logs.output[0])
        self.assertEqual(
            self.sqs.change_message_visibility.call_args_list,
            [
                call(
                    QueueUrl="https://sqs.example/jobs",
                    ReceiptHandle="receipt-1",
                    VisibilityTimeout=85 * 60,
                ),
                call(
                    QueueUrl="https://sqs.example/jobs",
                    ReceiptHandle="receipt-1",
                    VisibilityTimeout=10,
                ),
            ],
        )

    def test_active_job_visibility_covers_the_worker_deadline(self) -> None:
        record = {
            "messageId": "queue-message-1",
            "receiptHandle": "receipt-1",
            "body": "{}",
        }
        with patch.object(self.handler, "_process"):
            response = self.handler.handler({"Records": [record]}, None)

        self.assertEqual(response, {"batchItemFailures": []})
        self.sqs.change_message_visibility.assert_called_once_with(
            QueueUrl="https://sqs.example/jobs",
            ReceiptHandle="receipt-1",
            VisibilityTimeout=85 * 60,
        )

    def test_catalog_refresh_job_runs_outside_the_api_request_path(self) -> None:
        record = {"body": json.dumps({"type": "CATALOG_REFRESH"})}
        with patch.object(self.handler.catalog, "sync_official") as refresh:
            self.handler._process(record)

        refresh.assert_called_once_with(force=True)

    def test_group_round_does_not_advance_without_a_completed_reply(self) -> None:
        request = {
            "groupId": "group-1",
            "replies": [
                {"botId": "chief", "replyKey": "MESSAGE#1"},
                {"botId": "research", "replyKey": "MESSAGE#2"},
            ],
        }
        with (
            patch.object(self.group_job, "_activate_group_reply"),
            patch.object(
                self.group_job, "_process_group_agent_reply", return_value=None
            ),
        ):
            self.group_job._process_group_agent_round(
                {"messageId": "queue-message-1"}, request
            )

        self.sqs.send_message.assert_not_called()

    def test_account_cleanup_job_dispatches_to_idempotent_cleanup(self) -> None:
        cleanup = MagicMock()
        record = {
            "body": json.dumps(
                {
                    "type": "DELETE_ACCOUNT",
                    "userId": "user-1",
                    "username": "username-1",
                }
            )
        }

        with patch.object(self.handler, "_delete_account", cleanup):
            self.handler._process(record)

        cleanup.assert_called_once_with("user-1", "username-1")

    def test_scheduled_work_pauses_after_specific_tool_call(self) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "userId": "user-1",
            "botId": "bot-1",
            "status": "PENDING",
            "source": "schedule",
            "scheduleId": "schedule-1",
            "createdAt": "now",
        }
        self.table.items[(turn["pk"], turn["sk"])] = turn
        self.table.items[("USER#user-1", "BOT#bot-1")] = {
            "id": "bot-1",
            "name": "Browser bot",
            "toolIds": ["browser"],
        }
        with (
            patch.object(self.direct_job, "_update_schedule_result") as update_schedule,
            patch.object(self.direct_job, "_invoke", return_value=self.direct_job._invoke.__globals__["AgentInvocationResult"](
                text="Approval required.", pending_approval={
                    "id": "approval-1", "digest": "a" * 64, "toolUseId": "tool-1",
                    "toolName": "browser", "input": {"url": "https://example.com"},
                    "expiresAt": "2099-09-18T12:00:00+00:00",
                }
            )) as invoke,
        ):
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {
                    "type": "AGENT_REPLY",
                    "userId": "user-1",
                    "botId": "bot-1",
                    "turnKey": turn["sk"],
                },
            )

        invoke.assert_called_once()
        update_schedule.assert_called_once_with(turn, "awaiting_approval", "now")
        approval_update = self.table.updates[-1]
        self.assertEqual(
            approval_update["ExpressionAttributeValues"][":awaiting"],
            "AWAITING_APPROVAL",
        )

    def test_direct_work_pauses_with_specific_proposal(self) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "userId": "user-1",
            "botId": "bot-1",
            "status": "PENDING",
            "createdAt": "now",
        }
        self.table.items[(turn["pk"], turn["sk"])] = turn
        self.table.items[("USER#user-1", "BOT#bot-1")] = {
            "id": "bot-1",
            "name": "Browser bot",
            "toolIds": ["browser"],
        }
        with (
            patch.object(
                self.direct_job.catalog,
                "approval_tool_names",
                return_value=["Interactive browser"],
            ),
            patch.object(self.direct_job, "_invoke", return_value=self.direct_job._invoke.__globals__["AgentInvocationResult"](
                text="Approval required.", pending_approval={
                    "id": "approval-1", "digest": "a" * 64, "toolUseId": "tool-1",
                    "toolName": "browser", "input": {"url": "https://example.com"},
                    "expiresAt": "2099-09-18T12:00:00+00:00",
                }
            )) as invoke,
        ):
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {
                    "type": "AGENT_REPLY",
                    "userId": "user-1",
                    "botId": "bot-1",
                    "turnKey": turn["sk"],
                },
            )

        invoke.assert_called_once()
        approval_update = self.table.updates[-1]
        self.assertEqual(
            approval_update["ExpressionAttributeValues"][":awaiting"],
            "AWAITING_APPROVAL",
        )
        self.assertEqual(
            approval_update["ExpressionAttributeValues"][":proposal"]["toolName"],
            "browser",
        )
