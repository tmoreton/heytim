from __future__ import annotations

import importlib
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch


class ConditionalCheckFailedException(Exception):
    pass


class UserNotFoundException(Exception):
    pass


class FakeCondition:
    def __and__(self, _other):
        return self

    def __or__(self, _other):
        return self


class FakeAttr(FakeCondition):
    def __init__(self, _name: str):
        pass

    def eq(self, _value):
        return self

    def is_in(self, _value):
        return self

    def begins_with(self, _value):
        return self

    def exists(self):
        return self

    def not_exists(self):
        return self


class FakeConfig:
    def __init__(self, **_kwargs):
        pass


class FakeBatch:
    def __init__(self, table: FakeTable):
        self.table = table

    def put_item(self, Item: dict) -> None:
        self.table.put_item(Item=Item)

    def delete_item(self, Key: dict) -> None:
        self.table.deleted.append(dict(Key))
        if "pk" in Key:
            self.table.items.pop((Key["pk"], Key["sk"]), None)


class FakeTable:
    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}
        self.deleted: list[dict] = []
        self.put: list[dict] = []
        self.updated: list[dict] = []
        self.meta = SimpleNamespace(
            client=SimpleNamespace(
                exceptions=SimpleNamespace(
                    ConditionalCheckFailedException=ConditionalCheckFailedException
                )
            )
        )

    @contextmanager
    def batch_writer(self):
        yield FakeBatch(self)

    def put_item(self, *, Item: dict, **_kwargs) -> None:
        self.put.append(dict(Item))
        if "pk" in Item:
            self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def delete_item(self, *, Key: dict) -> None:
        self.deleted.append(dict(Key))
        if "pk" in Key:
            self.items.pop((Key["pk"], Key["sk"]), None)

    def update_item(self, **kwargs) -> None:
        self.updated.append(kwargs)

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def scan(self, **_kwargs) -> dict:
        return {"Items": []}


class ApiSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data_table = FakeTable()
        cls.invite_table = FakeTable()
        cls.sqs = MagicMock()
        cls.scheduler = MagicMock()
        cls.scheduler.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        cls.cognito = MagicMock()
        cls.cognito.exceptions.UserNotFoundException = UserNotFoundException
        cls.agentcore = MagicMock()
        cls.agentcore.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        cls.s3 = MagicMock()

        def resource(_service: str):
            return SimpleNamespace(
                Table=lambda name: (
                    cls.invite_table if name == "invites" else cls.data_table
                )
            )

        def client(service: str, **_kwargs):
            return {
                "sqs": cls.sqs,
                "scheduler": cls.scheduler,
                "cognito-idp": cls.cognito,
                "bedrock-agentcore": cls.agentcore,
                "s3": cls.s3,
            }[service]

        environment = {
            "TABLE_NAME": "data",
            "INVITE_TABLE_NAME": "invites",
            "QUEUE_URL": "https://sqs.example/jobs",
            "QUEUE_ARN": "arn:aws:sqs:us-east-1:123:jobs",
            "SCHEDULE_DLQ_ARN": "arn:aws:sqs:us-east-1:123:dlq",
            "SCHEDULE_GROUP_NAME": "schedules",
            "SCHEDULE_ROLE_ARN": "arn:aws:iam::123:role/scheduler",
            "USER_POOL_ID": "us-east-1_pool",
            "FILES_BUCKET_NAME": "frogbot-user-files-123-us-east-1",
        }
        boto3 = ModuleType("boto3")
        boto3.resource = resource
        boto3.client = client
        dynamodb = ModuleType("boto3.dynamodb")
        conditions = ModuleType("boto3.dynamodb.conditions")
        conditions.Attr = FakeAttr
        botocore = ModuleType("botocore")
        botocore_config = ModuleType("botocore.config")
        botocore_config.Config = FakeConfig

        sys.modules.pop("api.handler", None)
        with (
            patch.dict(os.environ, environment),
            patch.dict(
                sys.modules,
                {
                    "boto3": boto3,
                    "boto3.dynamodb": dynamodb,
                    "boto3.dynamodb.conditions": conditions,
                    "botocore": botocore,
                    "botocore.config": botocore_config,
                },
            ),
        ):
            cls.handler = importlib.import_module("api.handler")
            cls.support = importlib.import_module("api.support")
            cls.attachments = importlib.import_module("api.attachments")
            cls.bots = importlib.import_module("api.bots")
            cls.direct_chat = importlib.import_module("api.direct_chat")
            cls.groups = importlib.import_module("api.groups")
            cls.schedules = importlib.import_module("api.schedules")
            cls.account = importlib.import_module("api.account")

    def setUp(self) -> None:
        self.data_table.items.clear()
        self.data_table.deleted.clear()
        self.data_table.put.clear()
        self.data_table.updated.clear()
        self.invite_table.deleted.clear()
        self.cognito.reset_mock()
        self.agentcore.reset_mock()
        self.sqs.reset_mock()
        self.s3.reset_mock()
        self.s3.list_object_versions.return_value = {}

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
            patch.object(self.bots, "_revoke_bot_shares", return_value=2) as revoke,
        ):
            result = self.bots._clear_bot_chat("user-1", "bot-1")

        revoke.assert_called_once_with("user-1", "bot-1", scopes={"chat"})
        self.assertEqual(result["revokedShares"], 2)

    def test_second_message_is_rejected_while_a_turn_is_in_flight(self) -> None:
        turns = [{"status": "RUNNING"}]
        with (
            patch.object(self.direct_chat, "_get_bot"),
            patch.object(self.direct_chat, "_partition_items", return_value=turns),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.direct_chat._send_message("user-1", "bot-1", {"text": "Hello"})

        self.assertEqual(error.exception.status_code, 409)

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
                "approval_tool_names",
                return_value=["Interactive browser"],
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
        self.sqs.send_message.assert_not_called()

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

        self.assertEqual(result, {"turnId": "turn-1", "status": "pending"})
        approval_update = self.data_table.updated[-1]
        self.assertEqual(approval_update["ConditionExpression"], "#status = :awaiting")
        message = self.sqs.send_message.call_args.kwargs["MessageBody"]
        self.assertIn('"turnKey": "TURN#now#turn-1"', message)

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
            self.account, "FROGBOT_MEMORY_ID", "FrogBotMemory-abcdefghij"
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
            patch.object(self.account, "FROGBOT_MEMORY_ID", "FrogBotMemory-abcdefghij"),
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
