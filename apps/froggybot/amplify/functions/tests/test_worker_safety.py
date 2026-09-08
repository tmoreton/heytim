from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call, patch


class ConditionalCheckFailedException(Exception):
    pass


class FakeAttr:
    def __init__(self, _name: str):
        pass

    def exists(self):
        return self

    def not_exists(self):
        return self


class FakeConfig:
    def __init__(self, **_kwargs):
        pass


class FakeTable:
    def __init__(self) -> None:
        self.fail_condition = False
        self.items: dict[tuple[str, str], dict] = {}
        self.updates: list[dict] = []
        self.meta = SimpleNamespace(
            client=SimpleNamespace(
                exceptions=SimpleNamespace(
                    ConditionalCheckFailedException=ConditionalCheckFailedException
                )
            )
        )

    def update_item(self, **kwargs) -> None:
        self.updates.append(kwargs)
        if self.fail_condition:
            raise ConditionalCheckFailedException

    def put_item(self, *, Item: dict, **_kwargs) -> None:
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def delete_item(self, *, Key: dict) -> None:
        self.items.pop((Key["pk"], Key["sk"]), None)

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, *, ExpressionAttributeValues: dict, **_kwargs) -> dict:
        pk = ExpressionAttributeValues[":pk"]
        prefix = ExpressionAttributeValues.get(":prefix", "")
        return {
            "Items": [
                dict(item)
                for (item_pk, sk), item in self.items.items()
                if item_pk == pk and sk.startswith(prefix)
            ]
        }


class WorkerSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = FakeTable()
        cls.agentcore = MagicMock()
        cls.sqs = MagicMock()
        cls.s3 = MagicMock()

        def resource(_service: str):
            return SimpleNamespace(Table=lambda _name: cls.table)

        def client(service: str, **_kwargs):
            return {
                "bedrock-agentcore": cls.agentcore,
                "sqs": cls.sqs,
                "s3": cls.s3,
            }[service]

        environment = {
            "TABLE_NAME": "data",
            "AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-east-1:123:runtime/test",
            "QUEUE_URL": "https://sqs.example/jobs",
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

        sys.modules.pop("worker.handler", None)
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
            cls.handler = importlib.import_module("worker.handler")
            cls.agent = importlib.import_module("worker.agent")
            cls.work = importlib.import_module("worker.work")
            cls.artifacts = importlib.import_module("worker.artifacts")
            cls.direct_job = importlib.import_module("worker.direct_job")
            cls.group_job = importlib.import_module("worker.group_job")
            cls.background_work = importlib.import_module("worker.background_work")

    def setUp(self) -> None:
        self.table.fail_condition = False
        self.table.items.clear()
        self.table.updates.clear()
        self.s3.reset_mock()
        self.agentcore.reset_mock()
        self.sqs.reset_mock()
        self.s3.list_objects_v2.return_value = {"Contents": []}

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
                "startedAt": "2026-09-06T12:00:00Z",
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

    def test_completed_background_work_resumes_the_original_job(self) -> None:
        item_key = {"pk": "CHAT#1", "sk": "TURN#1"}
        pending = [
            {
                "provider": "agentcore_code_interpreter",
                "resourceId": "aws.codeinterpreter.v1",
                "sessionId": "session-1",
                "taskId": "task-1",
                "label": "Run tests",
                "startedAt": "2026-09-06T12:00:00Z",
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
        self.sqs.send_message.assert_called_once_with(
            QueueUrl="https://sqs.example/jobs", MessageBody=json.dumps(resume)
        )

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
                    VisibilityTimeout=16 * 60,
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
            VisibilityTimeout=16 * 60,
        )

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
        account = ModuleType("api.account")
        account._delete_account = cleanup
        record = {
            "body": json.dumps(
                {
                    "type": "DELETE_ACCOUNT",
                    "userId": "user-1",
                    "username": "username-1",
                }
            )
        }

        with patch.dict(sys.modules, {"api.account": account}):
            self.handler._process(record)

        cleanup.assert_called_once_with("user-1", "username-1")

    def test_legacy_schedule_cannot_bypass_interactive_tool_approval(self) -> None:
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
        finish = MagicMock(return_value="later")
        with (
            patch.object(
                self.direct_job.catalog,
                "approval_tool_names",
                return_value=["Interactive browser"],
            ),
            patch.object(
                self.direct_job.catalog,
                "unapproved_tools",
                return_value=[],
            ),
            patch.object(self.direct_job, "_claim_work", return_value="lease-1"),
            patch.object(self.direct_job, "_finish_work", finish),
            patch.object(self.direct_job, "_update_schedule_result") as update_schedule,
            patch.object(self.direct_job, "_queue_reply_notification") as notify,
            patch.object(self.direct_job, "_invoke") as invoke,
        ):
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {"userId": "user-1", "botId": "bot-1", "turnKey": turn["sk"]},
            )

        invoke.assert_not_called()
        self.assertEqual(finish.call_args.args[2:4], ("ERROR", "assistantText"))
        update_schedule.assert_called_once()
        notify.assert_called_once()

    def test_unapproved_direct_work_is_returned_to_the_approval_state(self) -> None:
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
            patch.object(
                self.direct_job.catalog,
                "unapproved_tools",
                return_value=[{"id": "browser", "name": "Interactive browser"}],
            ),
            patch.object(self.direct_job, "_invoke") as invoke,
        ):
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {"userId": "user-1", "botId": "bot-1", "turnKey": turn["sk"]},
            )

        invoke.assert_not_called()
        approval_update = self.table.updates[-1]
        self.assertEqual(
            approval_update["ExpressionAttributeValues"][":awaiting"],
            "AWAITING_APPROVAL",
        )
        self.assertEqual(
            approval_update["ExpressionAttributeValues"][":approvalToolIds"],
            ["browser"],
        )

    def test_generated_artifacts_become_owned_downloadable_file_records(self) -> None:
        file_id = "12345678-1234-1234-1234-123456789012"
        self.s3.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": f"users/actor/bots/bot-1/artifacts/turn-1/{file_id}--results.csv",
                    "Size": 42,
                    "LastModified": datetime(2026, 9, 4, tzinfo=UTC),
                }
            ]
        }
        with patch.object(self.artifacts, "memory_actor_id", return_value="actor"):
            artifacts = self.artifacts._collect_generated_artifacts(
                "user-1", "bot-1", "turn-1"
            )

        self.assertEqual(artifacts[0]["name"], "results.csv")
        self.assertEqual(artifacts[0]["contentType"], "text/csv")
        self.assertEqual(artifacts[0]["botId"], "bot-1")
        self.assertIn(("USER#user-1", f"FILE#{file_id}"), self.table.items)

    def test_group_artifacts_become_shared_group_file_records(self) -> None:
        file_id = "12345678-1234-1234-1234-123456789012"
        self.s3.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": f"groups/group-1/artifacts/reply-1/{file_id}--trip.pdf",
                    "Size": 2048,
                    "LastModified": datetime(2026, 9, 5, tzinfo=UTC),
                }
            ]
        }

        generated = self.artifacts._collect_group_generated_artifacts(
            "group-1", "reply-1"
        )

        self.assertEqual(generated[0]["name"], "trip.pdf")
        self.assertIn(("GROUP#group-1", f"FILE#{file_id}"), self.table.items)

    def test_native_generated_artifacts_preserve_document_or_image_kind(self) -> None:
        document_id = "12345678-1234-1234-1234-123456789012"
        image_id = "22345678-1234-1234-1234-123456789012"
        self.s3.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": f"users/actor/bots/bot-1/artifacts/turn-1/{document_id}--brief.pptx",
                    "Size": 2048,
                    "LastModified": datetime(2026, 9, 4, tzinfo=UTC),
                },
                {
                    "Key": f"users/actor/bots/bot-1/artifacts/turn-1/{image_id}--concept.png",
                    "Size": 4096,
                    "LastModified": datetime(2026, 9, 4, tzinfo=UTC),
                },
            ]
        }

        with patch.object(self.artifacts, "memory_actor_id", return_value="actor"):
            generated = self.artifacts._collect_generated_artifacts(
                "user-1", "bot-1", "turn-1"
            )

        self.assertEqual(generated[0]["kind"], "document")
        self.assertEqual(generated[0]["format"], "pptx")
        self.assertEqual(generated[1]["kind"], "image")
        self.assertEqual(generated[1]["format"], "png")

    def test_attachment_blocks_are_bound_to_the_current_user(self) -> None:
        with patch.object(self.artifacts, "memory_actor_id", return_value="actor-1"):
            blocks = self.artifacts._attachment_blocks(
                {
                    "attachments": [
                        {
                            "kind": "document",
                            "format": "pdf",
                            "objectKey": "users/actor-1/uploads/report.pdf",
                        }
                    ]
                },
                "user-1",
            )
            with self.assertRaisesRegex(ValueError, "metadata"):
                self.artifacts._attachment_blocks(
                    {
                        "attachments": [
                            {
                                "kind": "document",
                                "format": "pdf",
                                "objectKey": "users/actor-2/uploads/report.pdf",
                            }
                        ]
                    },
                    "user-1",
                )

        self.assertEqual(blocks[0]["document"]["name"], "Attachment 1")

    def test_partial_generated_artifacts_are_removed_before_retry(self) -> None:
        file_id = "12345678-1234-1234-1234-123456789012"
        object_key = f"users/actor/bots/bot-1/artifacts/turn-1/{file_id}--partial.csv"
        self.s3.list_objects_v2.return_value = {
            "Contents": [{"Key": object_key}],
            "IsTruncated": False,
        }
        self.s3.delete_objects.return_value = {}
        self.table.items[("USER#user-1", f"FILE#{file_id}")] = {
            "pk": "USER#user-1",
            "sk": f"FILE#{file_id}",
        }

        with patch.object(self.artifacts, "memory_actor_id", return_value="actor"):
            deleted = self.artifacts._delete_generated_artifacts(
                "user-1", "bot-1", "turn-1"
            )

        self.assertEqual(deleted, 1)
        self.s3.delete_objects.assert_called_once_with(
            Bucket="frogbot-user-files-123-us-east-1",
            Delete={"Objects": [{"Key": object_key}], "Quiet": True},
        )
        self.assertNotIn(("USER#user-1", f"FILE#{file_id}"), self.table.items)
