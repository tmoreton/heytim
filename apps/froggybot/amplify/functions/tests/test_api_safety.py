from __future__ import annotations

import unittest
from unittest.mock import patch

from api_test_case import ApiTestCase


class ApiSafetyTests(ApiTestCase):

    def test_request_body_rejects_non_text_json_input(self) -> None:
        with self.assertRaises(self.support.ApiError) as error:
            self.support._body({"body": {"unexpected": "object"}})

        self.assertEqual(error.exception.status_code, 400)

    def test_request_body_is_bounded_before_json_parsing(self) -> None:
        oversized = "x" * (self.support.MAX_REQUEST_BODY_BYTES + 1)
        with self.assertRaises(self.support.ApiError) as error:
            self.support._body({"body": oversized})

        self.assertEqual(error.exception.status_code, 413)

    def test_stop_background_agent_marks_cancel_before_stopping_its_session(self) -> None:
        order = []
        with patch.object(self.direct_chat.s3, "put_object", side_effect=lambda **_k: order.append("marker")) as put, patch.object(self.direct_chat.agentcore, "stop_runtime_session", side_effect=lambda **_k: order.append("stop")) as stop:
            self.direct_chat._stop_background_work({"pendingWork": [{"provider": "agentcore_runtime", "taskId": "users/actor/runs/run/state.json", "sessionId": "specific-session"}]})
        self.assertEqual(order, ["marker", "stop"])
        self.assertIn(b'"cancelled":true', put.call_args.kwargs["Body"])
        self.assertEqual(stop.call_args.kwargs["runtimeSessionId"], "specific-session")

    def test_revoking_a_share_removes_snapshot_pointers_and_signup_access(self) -> None:
        share = {
            "pk": "SHARE#secret-token",
            "sk": "META",
            "entity": "SHARE",
            "ownerId": "user-1",
        }

        self.support._delete_share_record("user-1", share)

        self.assertIn(
            {"pk": "SHARE#secret-token", "sk": "META"}, self.data_table.deleted
        )
        self.assertIn(
            {"pk": "USER#user-1", "sk": "SHARE#secret-token"},
            self.data_table.deleted,
        )
        self.assertEqual(len(self.invite_table.deleted), 1)

    def test_partition_reader_uses_resource_level_pagination(self) -> None:
        with patch.object(
            self.data_table,
            "query",
            side_effect=[
                {
                    "Items": [{"pk": "USER#user-1", "sk": "BOT#1"}],
                    "LastEvaluatedKey": {"pk": "USER#user-1", "sk": "BOT#1"},
                },
                {"Items": [{"pk": "USER#user-1", "sk": "BOT#2"}]},
            ],
            create=True,
        ) as query:
            items = self.support._partition_items("USER#user-1", "BOT#")

        self.assertEqual([item["sk"] for item in items], ["BOT#1", "BOT#2"])
        first = query.call_args_list[0].kwargs
        second = query.call_args_list[1].kwargs
        self.assertNotIn("TableName", first)
        self.assertEqual(first["ExpressionAttributeValues"][":pk"], "USER#user-1")
        self.assertEqual(
            second["ExclusiveStartKey"],
            {"pk": "USER#user-1", "sk": "BOT#1"},
        )

    def test_direct_messages_expose_response_start_and_completion_times(self) -> None:
        messages = self.bots._messages_from_turns(
            [
                {
                    "id": "turn-1",
                    "userText": "Ship it",
                    "assistantText": "Done",
                    "createdAt": "2026-09-09T18:00:00Z",
                    "startedAt": "2026-09-09T18:00:02Z",
                    "activityUpdatedAt": "2026-09-09T18:00:45Z",
                    "completedAt": "2026-09-09T18:01:05Z",
                    "status": "COMPLETE",
                }
            ]
        )

        self.assertEqual(messages[1]["startedAt"], "2026-09-09T18:00:02Z")
        self.assertEqual(messages[1]["activityUpdatedAt"], "2026-09-09T18:00:45Z")
        self.assertEqual(messages[1]["completedAt"], "2026-09-09T18:01:05Z")

    def test_clearing_chat_revokes_only_conversation_shares(self) -> None:
        bot = {"id": "bot-1"}
        with (
            patch.object(self.bots, "_get_bot", return_value=bot),
            patch.object(self.bots, "_partition_items", return_value=[]),
            patch.object(
                self.bots, "_preserve_bot_documents", return_value=3
            ) as preserve,
            patch.object(self.bots, "_revoke_bot_shares", return_value=2) as revoke,
        ):
            result = self.bots._clear_bot_chat("user-1", "bot-1")

        preserve.assert_called_once_with("user-1", "bot-1", [])
        revoke.assert_called_once_with("user-1", "bot-1", scopes={"chat"})
        self.assertEqual(result["preservedDocuments"], 3)
        self.assertEqual(result["revokedShares"], 2)

    def test_clearing_chat_can_queue_conversation_memory_deletion(self) -> None:
        with (
            patch.object(self.bots, "_get_bot", return_value={"id": "bot-1"}),
            patch.object(self.bots, "_partition_items", return_value=[]),
            patch.object(self.bots, "_preserve_bot_documents", return_value=0),
            patch.object(self.bots, "_revoke_bot_shares", return_value=0),
        ):
            result = self.bots._clear_bot_chat("user-1", "bot-1", forget_memory=True)

        body = self.sqs.send_message.call_args.kwargs["MessageBody"]
        self.assertIn('"type": "DELETE_MEMORY_SESSION"', body)
        self.assertEqual(result["forgottenMemory"], {"queued": True})

    def test_chief_is_a_required_public_template_and_remains_protected(self) -> None:
        self.assertFalse(hasattr(self.bots, "DEFAULT_BOTS"))
        with (
            patch.object(
                self.bots,
                "_get_bot",
                return_value={"id": "chief", "systemRole": "chief"},
            ),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.bots._delete_bot("user-1", "chief")

        self.assertEqual(error.exception.status_code, 409)

    def test_bot_updates_cannot_grant_always_allowed_tools(self) -> None:
        previous = {
            "name": "Home Bot",
            "tagline": "Controls the house",
            "prompt": "Help control my Home Assistant devices.",
            "color": "#FFAA34",
            "toolIds": ["home"],
            "extraToolIds": ["home"],
            "alwaysAllowedToolIds": [],
            "skillIds": [],
            "skillVersions": {},
        }
        with (
            patch.object(self.bots.catalog, "sync_official"),
            patch.object(self.bots.catalog, "validate_and_pin", return_value={}),
            patch.object(
                self.bots.catalog,
                "validate_tools",
                side_effect=lambda _user, tool_ids: list(tool_ids),
            ),
            patch.object(
                self.bots.catalog, "approval_tool_ids", return_value=["home"]
            ),
        ):
            values = self.bots._bot_values(
                "user-1", {"alwaysAllowedToolIds": ["home"]}, previous
            )

        self.assertEqual(values["alwaysAllowedToolIds"], [])

    def test_second_message_steers_the_active_turn_before_starting_once(self) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "status": "RUNNING",
        }
        with (
            patch.object(
                self.direct_chat,
                "_get_bot",
                return_value={"id": "bot-1", "toolIds": []},
            ),
            patch.object(self.direct_chat, "_partition_items", return_value=[turn]),
            patch.object(
                self.direct_chat.catalog, "unapproved_tools", return_value=[]
            ),
        ):
            result = self.direct_chat._send_message(
                "user-1", "bot-1", {"text": "Focus on the manifest first"}
            )

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["steeredTurnIds"], ["turn-1"])
        interruption = next(
            update
            for update in self.data_table.updated
            if update.get("ExpressionAttributeValues", {}).get(":message")
            == "Steered by you."
        )
        self.assertEqual(
            interruption["ExpressionAttributeValues"][":cancelled"], "CANCELLED"
        )
        self.agentcore.stop_runtime_session.assert_called_once()
        self.sqs.send_message.assert_called_once()

    def test_send_lease_prevents_two_replacement_turns_from_starting(self) -> None:
        condition_failed = (
            self.data_table.meta.client.exceptions.ConditionalCheckFailedException()
        )
        with (
            patch.object(
                self.data_table, "update_item", side_effect=condition_failed
            ),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.direct_chat._claim_send_lease("user-1", "bot-1")

        self.assertEqual(error.exception.status_code, 409)

    def test_cancelling_a_running_turn_stops_its_runtime_session(self) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "status": "RUNNING",
        }
        with (
            patch.object(self.direct_chat, "_get_bot"),
            patch.object(self.direct_chat, "_get_turn", return_value=turn),
        ):
            result = self.direct_chat._cancel_bot_turn(
                "user-1", "bot-1", "turn-1"
            )

        self.assertEqual(result, {"cancelled": True})
        self.agentcore.stop_runtime_session.assert_called_once_with(
            agentRuntimeArn=(
                "arn:aws:bedrock-agentcore:us-east-1:123:runtime/test"
            ),
            qualifier="DEFAULT",
            runtimeSessionId=self.direct_chat.direct_session_id(
                "user-1", "bot-1"
            ),
        )

    def test_interactive_message_waits_for_one_time_approval(self) -> None:
        with (
            patch.object(
                self.direct_chat,
                "_get_bot",
                return_value={"id": "bot-1", "toolIds": ["browser"]},
            ),
            patch.object(self.direct_chat, "_partition_items", return_value=[]),
            patch.object(
                self.direct_chat.catalog,
                "unapproved_tools",
                return_value=[{"id": "browser", "name": "Interactive browser"}],
            ),
        ):
            result = self.direct_chat._send_message(
                "user-1", "bot-1", {"text": "Book the first option"}
            )

        self.assertEqual(result["status"], "awaiting_approval")
        turn = next(
            item for item in self.data_table.put if item.get("entity") == "TURN"
        )
        self.assertEqual(turn["status"], "AWAITING_APPROVAL")
        self.assertEqual(turn["approvalTools"], ["Interactive browser"])
        self.assertEqual(turn["approvalToolIds"], ["browser"])
        self.sqs.send_message.assert_not_called()

    def test_always_allowed_interactive_message_starts_without_approval(self) -> None:
        with (
            patch.object(
                self.direct_chat,
                "_get_bot",
                return_value={
                    "id": "bot-1",
                    "toolIds": ["home"],
                    "alwaysAllowedToolIds": ["home"],
                },
            ),
            patch.object(self.direct_chat, "_partition_items", return_value=[]),
            patch.object(
                self.direct_chat.catalog,
                "unapproved_tools",
                return_value=[],
            ),
        ):
            result = self.direct_chat._send_message(
                "user-1", "bot-1", {"text": "Turn off the bedroom lights"}
            )

        self.assertEqual(result["status"], "pending")
        self.sqs.send_message.assert_called_once()

    def test_approving_an_interactive_message_queues_exactly_that_turn(self) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "userId": "user-1",
            "botId": "bot-1",
            "status": "AWAITING_APPROVAL",
            "approvalTools": ["Interactive browser"],
        }
        with (
            patch.object(self.direct_chat, "_get_bot"),
            patch.object(self.direct_chat, "_get_turn", return_value=turn),
        ):
            result = self.direct_chat._approve_bot_turn("user-1", "bot-1", "turn-1")

        self.assertEqual(
            result,
            {"turnId": "turn-1", "status": "pending", "alwaysAllowed": False},
        )
        approval_update = self.data_table.updated[-1]
        self.assertEqual(approval_update["ConditionExpression"], "#status = :awaiting")
        message = self.sqs.send_message.call_args.kwargs["MessageBody"]
        self.assertIn('"turnKey": "TURN#now#turn-1"', message)

    def test_always_approving_remembers_only_the_turn_tools(self) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "userId": "user-1",
            "botId": "bot-1",
            "status": "AWAITING_APPROVAL",
            "approvalTools": ["Home Assistant"],
            "approvalToolIds": ["home"],
        }
        bot = {
            "id": "bot-1",
            "toolIds": ["home", "browser"],
            "alwaysAllowedToolIds": ["browser"],
        }
        with (
            patch.object(self.direct_chat, "_get_bot", return_value=bot),
            patch.object(self.direct_chat, "_get_turn", return_value=turn),
            patch.object(
                self.direct_chat.catalog,
                "approval_tools",
                return_value=[
                    {"id": "home", "name": "Home Assistant"},
                    {"id": "browser", "name": "Interactive browser"},
                ],
            ),
        ):
            result = self.direct_chat._approve_bot_turn(
                "user-1", "bot-1", "turn-1", always=True
            )

        self.assertTrue(result["alwaysAllowed"])
        bot_update = self.data_table.updated[-1]
        self.assertEqual(
            bot_update["ExpressionAttributeValues"][":tools"],
            ["home", "browser"],
        )

    def test_imported_bot_never_inherits_always_allowed_tools(self) -> None:
        self.data_table.put_item(
            Item={
                "pk": "SHARE#invite-token",
                "sk": "META",
                "scope": "bot",
                "targetId": "bot-1",
                "expiresAt": 4_102_444_800,
                "snapshot": {
                    "skills": [],
                    "bot": {
                        "name": "Shared bot",
                        "color": "#FFAA34",
                        "toolIds": ["browser"],
                        "extraToolIds": ["browser"],
                        "alwaysAllowedToolIds": ["browser"],
                    },
                },
            }
        )
        self.invite_table.put_item(
            Item={
                "tokenHash": self.support.invite_token_hash("invite-token"),
                "kind": "bot",
                "targetId": "bot-1",
                "expiresAt": 4_102_444_800,
            }
        )
        with (
            patch.object(
                self.sharing,
                "_bot_values",
                side_effect=lambda _user, value: value,
            ) as values,
            patch.object(self.sharing, "_put_bot", return_value={"id": "copy"}),
            patch.object(self.sharing, "_record_invite_join"),
        ):
            self.sharing._import_share("recipient", "invite-token")

        self.assertEqual(values.call_args.args[1]["alwaysAllowedToolIds"], [])

    def test_shared_bot_never_exports_always_allowed_tools(self) -> None:
        bot = {
            "id": "bot-1",
            "name": "Home Bot",
            "color": "#FFAA34",
            "toolIds": ["home"],
            "extraToolIds": ["home"],
            "alwaysAllowedToolIds": ["home"],
            "skillIds": [],
            "skillVersions": {},
        }
        with (
            patch.object(self.sharing, "_get_bot", return_value=bot),
            patch.object(self.sharing.catalog, "list_connections", return_value=[]),
            patch.object(self.sharing, "_register_access_invite"),
        ):
            self.sharing._create_share("user-1", {"botId": "bot-1"})

        share = next(
            item for item in self.data_table.put if item.get("entity") == "SHARE"
        )
        self.assertNotIn("alwaysAllowedToolIds", share["snapshot"]["bot"])

    def test_schedules_allow_bots_that_pause_for_interactive_approval(self) -> None:
        with (
            patch.object(
                self.schedules,
                "_get_bot",
                return_value={"id": "bot-1", "toolIds": ["browser"]},
            ),
            patch.object(self.schedules, "_schedule_items", return_value=[]),
            patch.object(self.schedules, "_create_remote_schedule"),
        ):
            saved = self.schedules._create_schedule(
                "user-1",
                "bot-1",
                {
                    "name": "Browser check",
                    "prompt": "Check the dashboard.",
                    "frequency": "daily",
                    "time": "09:00",
                    "timezone": "UTC",
                    "enabled": True,
                },
            )

        self.assertEqual(saved["name"], "Browser check")

    def test_schedule_run_inbox_includes_output_and_pending_approval(self) -> None:
        turns = [
            {
                "id": "run-1",
                "source": "schedule",
                "scheduleId": "schedule-1",
                "scheduleName": "Morning priorities",
                "userText": "Review today.",
                "status": "AWAITING_APPROVAL",
                "createdAt": "2026-09-08T09:00:00Z",
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
if __name__ == "__main__":
    unittest.main()
