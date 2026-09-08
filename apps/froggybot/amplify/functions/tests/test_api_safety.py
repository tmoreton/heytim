from __future__ import annotations

import unittest
from unittest.mock import patch

from api_test_case import ApiTestCase


class ApiSafetyTests(ApiTestCase):

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

    def test_second_message_is_rejected_while_a_turn_is_in_flight(self) -> None:
        turns = [{"status": "RUNNING"}]
        with (
            patch.object(self.direct_chat, "_get_bot"),
            patch.object(self.direct_chat, "_partition_items", return_value=turns),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.direct_chat._send_message("user-1", "bot-1", {"text": "Hello"})

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

    def test_schedules_reject_bots_that_need_interactive_approval(self) -> None:
        with (
            patch.object(
                self.schedules,
                "_get_bot",
                return_value={"id": "bot-1", "toolIds": ["browser"]},
            ),
            patch.object(
                self.schedules.catalog,
                "approval_tool_names",
                return_value=["Interactive browser"],
            ),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.schedules._create_schedule("user-1", "bot-1", {})

        self.assertEqual(error.exception.status_code, 409)

    def test_upload_ticket_is_scoped_and_size_limited(self) -> None:
        self.s3.generate_presigned_post.return_value = {
            "url": "https://uploads.example",
            "fields": {"key": "value"},
        }

        result = self.attachments._create_upload(
            "user-1", {"filename": "quarterly report.pdf", "size": 125_000}
        )

        self.assertEqual(result["file"]["contentType"], "application/pdf")
        request = self.s3.generate_presigned_post.call_args.kwargs
        self.assertTrue(request["Key"].startswith("users/"))
        self.assertNotIn("user-1", request["Key"])
        self.assertIn(["content-length-range", 1, 4_500_000], request["Conditions"])

    def test_group_memory_is_owner_editable_and_bounded(self) -> None:
        meta = {
            "pk": "GROUP#group-1",
            "sk": "META",
            "entity": "GROUP",
            "id": "group-1",
            "name": "Trip",
            "ownerId": "user-1",
            "createdAt": "now",
            "updatedAt": "now",
        }
        with (
            patch.object(
                self.groups, "_require_group_member", return_value=(meta, [meta])
            ) as require,
            patch.object(
                self.groups,
                "_public_group",
                return_value={"id": "group-1", "memory": "Budget: $1,200"},
            ),
        ):
            result = self.groups._update_group(
                "user-1",
                "group-1",
                {"memory": "Budget: $1,200", "botIds": []},
            )

        require.assert_called_once_with("user-1", "group-1", owner=True)
        self.assertEqual(result["memory"], "Budget: $1,200")
        self.assertEqual(self.data_table.put[-1]["memory"], "Budget: $1,200")

        with (
            patch.object(
                self.groups, "_require_group_member", return_value=(meta, [meta])
            ),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.groups._update_group(
                "user-1",
                "group-1",
                {"memory": "x" * 4_001, "botIds": []},
            )

        self.assertEqual(error.exception.status_code, 400)

    def test_group_file_download_checks_current_membership(self) -> None:
        file_id = "12345678-1234-1234-1234-123456789012"
        self.data_table.items[("GROUP#group-1", "USER#user-1")] = {
            "pk": "GROUP#group-1",
            "sk": "USER#user-1",
            "entity": "GROUP_USER",
        }
        self.data_table.items[("GROUP#group-1", f"FILE#{file_id}")] = {
            "pk": "GROUP#group-1",
            "sk": f"FILE#{file_id}",
            "entity": "FILE",
            "id": file_id,
            "status": "READY",
            "name": "weekend.pdf",
            "contentType": "application/pdf",
            "objectKey": "groups/group-1/artifacts/reply-1/weekend.pdf",
        }
        self.s3.generate_presigned_url.return_value = "https://download.example"

        result = self.attachments._download_group_file("user-1", "group-1", file_id)

        self.assertEqual(result["url"], "https://download.example")
        with self.assertRaises(self.support.ApiError):
            self.attachments._download_group_file("outsider", "group-1", file_id)

    def test_oversized_image_upload_is_rejected_before_signing(self) -> None:
        with self.assertRaises(self.support.ApiError) as error:
            self.attachments._create_upload(
                "user-1", {"filename": "photo.png", "size": 3_750_001}
            )

        self.assertEqual(error.exception.status_code, 400)
        self.s3.generate_presigned_post.assert_not_called()

    def test_account_file_cleanup_deletes_all_object_versions(self) -> None:
        self.s3.list_object_versions.return_value = {
            "Versions": [{"Key": "users/actor/file.pdf", "VersionId": "one"}],
            "DeleteMarkers": [{"Key": "users/actor/file.pdf", "VersionId": "deleted"}],
            "IsTruncated": False,
        }
        self.s3.delete_objects.return_value = {}
        with patch.object(self.account, "memory_actor_id", return_value="actor"):
            deleted = self.account._delete_user_files("user-1")

        self.assertEqual(deleted, 2)
        objects = self.s3.delete_objects.call_args.kwargs["Delete"]["Objects"]
        self.assertEqual({item["VersionId"] for item in objects}, {"one", "deleted"})

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
            {"pk": "USER#user-1", "sk": "STATE", "entity": "USER_STATE"},
        ]

        def partitions(pk: str, _prefix=None):
            return user_items if pk == "USER#user-1" else []

        with (
            patch.object(self.account, "_partition_items", side_effect=partitions),
            patch.object(
                self.account,
                "_scan_items",
                return_value=[{"pk": "CHAT#user-1#bot-1", "sk": "TURN#1"}],
            ),
            patch.object(self.account, "_owned_share_records", return_value=[]),
            patch.object(self.account, "_remove_invite_access_for_user"),
            patch.object(self.account, "_remove_owned_skills", return_value=0),
            patch.object(self.account, "_delete_remote_schedule") as delete_schedule,
        ):
            result = self.account._delete_account("user-1", "username-1")

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
        self.assertEqual(self.data_table.put[-1]["accountStatus"], "DELETED")
        self.assertTrue(result["deleted"])


if __name__ == "__main__":
    unittest.main()
