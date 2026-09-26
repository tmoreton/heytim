from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from worker_test_case import WorkerTestCase


class DeviceAndArtifactSafetyTests(WorkerTestCase):
    def test_direct_work_assigns_device_interrupt_to_a_live_granted_device(
        self,
    ) -> None:
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "userId": "user-1",
            "botId": "bot-1",
            "status": "PENDING",
            "createdAt": "now",
        }
        bot = {
            "pk": "USER#user-1",
            "sk": "BOT#bot-1",
            "id": "bot-1",
            "name": "Mac bot",
            "toolIds": ["mac_computer"],
        }
        device = {
            "pk": "USER#user-1",
            "sk": "DEVICE#11111111-1111-4111-8111-111111111111",
            "entity": "DEVICE_CAPABILITIES",
            "deviceId": "11111111-1111-4111-8111-111111111111",
            "platform": "macos",
            "leaseExpiresAt": int(datetime.now(UTC).timestamp()) + 60,
            "lastSeenAt": datetime.now(UTC).isoformat(),
            "tools": [
                {
                    "id": "mac_computer",
                    "operations": ["mac_computer_observe"],
                }
            ],
            "botGrants": [{"botId": "bot-1", "toolIds": ["mac_computer"]}],
        }
        self.table.items[(turn["pk"], turn["sk"])] = turn
        self.table.items[(bot["pk"], bot["sk"])] = bot
        self.table.items[(device["pk"], device["sk"])] = device
        proposal = {
            "id": "interrupt-1",
            "toolUseId": "tool-use-1",
            "toolName": "mac_computer_observe",
            "input": {},
            "platform": "macos",
            "toolId": "mac_computer",
            "digest": "a" * 64,
            "expiresAt": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        }
        result_type = self.direct_job._invoke.__globals__["AgentInvocationResult"]

        with patch.object(
            self.direct_job,
            "_invoke",
            return_value=result_type(text="", pending_device_call=proposal),
        ) as invoke:
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {
                    "type": "AGENT_REPLY",
                    "userId": "user-1",
                    "botId": "bot-1",
                    "turnKey": turn["sk"],
                },
            )

        self.assertTrue(invoke.call_args.kwargs["allow_device_tools"])
        call_items = [
            item
            for item in self.table.items.values()
            if item.get("entity") == "DEVICE_CALL"
        ]
        self.assertEqual(len(call_items), 1)
        self.assertEqual(call_items[0]["deviceId"], device["deviceId"])
        pause = self.table.updates[-1]
        self.assertEqual(
            pause["ExpressionAttributeValues"][":awaiting"], "AWAITING_DEVICE"
        )
        self.assertEqual(
            pause["ExpressionAttributeValues"][":request"]["digest"], "a" * 64
        )

    def test_missing_device_resumes_with_an_explicit_tool_error(self) -> None:
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
            "name": "Health bot",
            "toolIds": ["apple_health"],
        }
        proposal = {
            "id": "interrupt-1",
            "toolUseId": "tool-use-1",
            "toolName": "apple_health_steps",
            "input": {"days": 7},
            "platform": "ios",
            "toolId": "apple_health",
            "digest": "a" * 64,
            "expiresAt": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        }
        result_type = self.direct_job._invoke.__globals__["AgentInvocationResult"]

        with patch.object(
            self.direct_job,
            "_invoke",
            return_value=result_type(text="", pending_device_call=proposal),
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

        update = self.table.updates[-1]
        self.assertEqual(update["ExpressionAttributeValues"][":pending"], "PENDING")
        self.assertEqual(
            update["ExpressionAttributeValues"][":result"]["status"], "error"
        )
        queued = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(queued["type"], "AGENT_REPLY")

    def test_device_result_accepted_before_expiry_can_resume_after_expiry(
        self,
    ) -> None:
        now = datetime.now(UTC)
        request = {
            "id": "interrupt-1",
            "toolUseId": "tool-use-1",
            "toolName": "apple_health_steps",
            "input": {"days": 7},
            "platform": "ios",
            "toolId": "apple_health",
            "digest": "a" * 64,
            "expiresAt": (now - timedelta(seconds=30)).isoformat(),
        }
        result = {
            "id": request["id"],
            "digest": request["digest"],
            "toolUseId": request["toolUseId"],
            "status": "success",
            "result": {"days": []},
        }
        turn = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#now#turn-1",
            "id": "turn-1",
            "userId": "user-1",
            "botId": "bot-1",
            "status": "PENDING",
            "createdAt": "now",
            "deviceRequest": request,
            "deviceResult": result,
            "deviceResultReceivedAt": (now - timedelta(seconds=31)).isoformat(),
        }
        self.table.items[(turn["pk"], turn["sk"])] = turn
        self.table.items[("USER#user-1", "BOT#bot-1")] = {
            "id": "bot-1",
            "name": "Health bot",
            "toolIds": ["apple_health"],
        }
        result_type = self.direct_job._invoke.__globals__["AgentInvocationResult"]

        with patch.object(
            self.direct_job,
            "_invoke",
            return_value=result_type(text="Your seven-day summary is ready."),
        ) as invoke:
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {
                    "type": "AGENT_REPLY",
                    "userId": "user-1",
                    "botId": "bot-1",
                    "turnKey": turn["sk"],
                },
            )

        self.assertEqual(invoke.call_args.kwargs["device_result"], result)
        consumed = next(
            update
            for update in self.table.updates
            if "deviceResultConsumedAt" in update["UpdateExpression"]
        )
        self.assertEqual(
            consumed["ExpressionAttributeValues"][":result"], result
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
