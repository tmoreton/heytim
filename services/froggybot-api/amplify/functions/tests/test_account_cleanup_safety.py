from __future__ import annotations

from unittest.mock import MagicMock, patch

from api_test_case import ApiTestCase


class AccountCleanupSafetyTests(ApiTestCase):
    def test_account_deletion_is_queued_after_access_is_blocked(self) -> None:
        result = self.account._begin_account_deletion("user-1", "username-1")

        self.assertTrue(result["deletionStarted"])
        self.assertEqual(
            self.data_table.updated[-1]["ExpressionAttributeValues"][":status"],
            "DELETING",
        )
        message = self.sqs.send_message.call_args.kwargs["MessageBody"]
        self.assertIn('"type": "DELETE_ACCOUNT"', message)

    def test_account_memory_cleanup_removes_events_and_extracted_records(self) -> None:
        self.agentcore.list_sessions.return_value = {
            "sessionSummaries": [{"sessionId": "session-1"}]
        }
        self.agentcore.list_events.return_value = {
            "events": [{"sessionId": "session-1", "eventId": "event-1"}]
        }
        self.agentcore.list_memory_records.side_effect = [
            {"memoryRecordSummaries": [{"memoryRecordId": "fact-1"}]},
            {"memoryRecordSummaries": [{"memoryRecordId": "preference-1"}]},
            {"memoryRecordSummaries": [{"memoryRecordId": "summary-1"}]},
        ]
        self.agentcore.batch_delete_memory_records.return_value = {
            "successfulRecords": [],
            "failedRecords": [],
        }

        with patch.object(
            self.memories, "FROGBOT_MEMORY_ID", "FrogBotMemory-abcdefghij"
        ):
            result = self.account._delete_user_memory("user-1")

        self.assertEqual(result, {"events": 1, "records": 3})
        self.agentcore.delete_event.assert_called_once()
        deleted = self.agentcore.batch_delete_memory_records.call_args.kwargs["records"]
        self.assertEqual(
            {item["memoryRecordId"] for item in deleted},
            {"fact-1", "preference-1", "summary-1"},
        )

    def test_account_memory_cleanup_accepts_an_actor_without_memory(self) -> None:
        with (
            patch.object(
                self.agentcore,
                "list_sessions",
                side_effect=self.agentcore.exceptions.ResourceNotFoundException(),
            ),
            patch.object(
                self.memories, "FROGBOT_MEMORY_ID", "FrogBotMemory-abcdefghij"
            ),
        ):
            result = self.account._delete_user_memory("user-without-memory")

        self.assertEqual(result, {"events": 0, "records": 0})

    def test_account_identity_is_deleted_after_application_cleanup(self) -> None:
        user_items = [
            {
                "pk": "USER#user-1",
                "sk": "BOT#bot-1",
                "entity": "BOT",
                "id": "bot-1",
            },
            {
                "pk": "USER#user-1",
                "sk": "SCHEDULE#schedule-1",
                "entity": "SCHEDULE",
                "schedulerName": "schedule-1",
            },
            {
                "pk": "USER#user-1",
                "sk": "PUSH#push-1",
                "entity": "PUSH_TOKEN",
                "tokenId": "push-1",
            },
            {
                "pk": "USER#user-1",
                "sk": "USAGE_ADMISSION#direct:turn-1",
                "entity": "USAGE_ADMISSION",
            },
            {
                "pk": "USER#user-1",
                "sk": "USAGE_LIMIT#MONTH#2026-09",
                "entity": "USAGE_MONTH_COUNTER",
            },
            {"pk": "USER#user-1", "sk": "STATE", "entity": "USER_STATE"},
        ]

        def partitions(pk: str, _prefix=None):
            return user_items if pk == "USER#user-1" else []

        service = self.account._cleanup_service()
        delete_schedule = MagicMock()
        with (
            patch.object(service, "partition_items", side_effect=partitions),
            patch.object(
                service,
                "scan_items",
                return_value=[{"pk": "CHAT#user-1#bot-1", "sk": "TURN#1"}],
            ),
            patch.object(service, "owned_share_records", return_value=[]),
            patch.object(service, "remove_invite_access_for_user"),
            patch.object(service, "remove_owned_skills", return_value=0),
            patch.object(service, "delete_user_files", return_value=0),
            patch.dict(
                service.delete_account.__func__.__globals__,
                {
                    "delete_user_memory": MagicMock(
                        return_value={"events": 0, "records": 0}
                    ),
                    "delete_remote_schedule": delete_schedule,
                },
            ),
        ):
            result = service.delete_account("user-1", "username-1")

        delete_schedule.assert_called_once()
        self.cognito.admin_user_global_sign_out.assert_called_once_with(
            UserPoolId="us-east-1_pool", Username="username-1"
        )
        self.cognito.admin_delete_user.assert_called_once_with(
            UserPoolId="us-east-1_pool", Username="username-1"
        )
        self.assertIn(
            {"pk": "CHAT#user-1#bot-1", "sk": "TURN#1"}, self.data_table.deleted
        )
        self.assertIn(
            {"pk": "PUSH_TOKEN#push-1", "sk": "OWNER"}, self.data_table.deleted
        )
        self.assertIn(
            {"pk": "USER#user-1", "sk": "USAGE_ADMISSION#direct:turn-1"},
            self.data_table.deleted,
        )
        self.assertIn(
            {"pk": "USER#user-1", "sk": "USAGE_LIMIT#MONTH#2026-09"},
            self.data_table.deleted,
        )
        self.assertEqual(self.data_table.put[-1]["accountStatus"], "DELETED")
        self.assertTrue(result["deleted"])

    def test_account_cleanup_deletes_group_replies_billed_to_member(self) -> None:
        service = self.account._cleanup_service()
        group_items = [
            {
                "pk": "GROUP#work",
                "sk": "MESSAGE#1#reply",
                "entity": "GROUP_MESSAGE",
                "authorType": "bot",
                "botOwnerId": "another-user",
                "billingUserId": "user-1",
            },
            {
                "pk": "GROUP#work",
                "sk": "MESSAGE#2#other",
                "entity": "GROUP_MESSAGE",
                "authorType": "bot",
                "botOwnerId": "another-user",
                "billingUserId": "another-user",
            },
        ]
        for item in group_items:
            self.data_table.items[(item["pk"], item["sk"])] = dict(item)

        service._delete_groups("user-1", {"work"}, {"work": group_items})

        self.assertIn(
            {"pk": "GROUP#work", "sk": "MESSAGE#1#reply"},
            self.data_table.deleted,
        )
        self.assertIn(
            ("GROUP#work", "MESSAGE#2#other"), self.data_table.items
        )

    def test_account_cleanup_fences_billed_group_reply_before_session_scan(self) -> None:
        service = self.account._cleanup_service()
        billed = {
            "pk": "GROUP#work",
            "sk": "MESSAGE#1#reply",
            "entity": "GROUP_MESSAGE",
            "authorType": "bot",
            "billingUserId": "user-1",
            "status": "RUNNING",
        }

        service.cancel_billed_group_replies("user-1", {"work": [billed]})

        update = self.data_table.updated[-1]
        self.assertEqual(update["Key"], {"pk": billed["pk"], "sk": billed["sk"]})
        self.assertEqual(
            update["ExpressionAttributeValues"][":cancelled"], "CANCELLED"
        )
        self.assertIn("billingUserId = :user", update["ConditionExpression"])

    def test_account_cleanup_fences_billed_direct_turn_before_session_scan(self) -> None:
        service = self.account._cleanup_service()
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#1",
            "entity": "TURN",
            "userId": "user-1",
            "status": "RUNNING",
        }

        service.cancel_billed_direct_turns("user-1", [turn])

        update = self.data_table.updated[-1]
        self.assertEqual(update["Key"], {"pk": turn["pk"], "sk": turn["sk"]})
        self.assertEqual(
            update["ExpressionAttributeValues"][":cancelled"], "CANCELLED"
        )
        self.assertIn("userId = :user", update["ConditionExpression"])
        self.assertIn("#status IN", update["ConditionExpression"])
        self.assertEqual(
            {
                value
                for key, value in update["ExpressionAttributeValues"].items()
                if key.startswith(":status")
            },
            {"PENDING", "RUNNING", "WAITING", "NEEDS_INPUT", "AWAITING_APPROVAL"},
        )

    def test_account_cleanup_refreshes_direct_work_after_cancellation_fence(self) -> None:
        service = self.account._cleanup_service()
        before = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#1",
            "entity": "TURN",
            "userId": "user-1",
            "status": "RUNNING",
        }
        after = {
            **before,
            "status": "CANCELLED",
            "pendingWork": [
                {
                    "provider": "agentcore_runtime",
                    "sessionId": "late-runtime-session",
                }
            ],
        }

        with (
            patch.object(
                service,
                "scan_items",
                side_effect=[[before], [after]],
            ) as scan,
            patch.object(service, "cancel_billed_direct_turns") as cancel,
        ):
            refreshed = service.fence_billed_direct_turns("user-1")

        cancel.assert_called_once_with("user-1", [before])
        self.assertEqual(refreshed, [after])
        self.assertEqual(scan.call_count, 2)
        self.assertTrue(all(call.kwargs["consistent_read"] for call in scan.call_args_list))
