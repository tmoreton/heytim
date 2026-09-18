from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import test_api_safety


class MemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = test_api_safety.ApiSafetyTests
        if not hasattr(base, "memories"):
            base.setUpClass()
        cls.agentcore = base.agentcore
        cls.memories = base.memories
        cls.s3 = base.s3
        cls.support = base.support

    def setUp(self) -> None:
        self.agentcore.reset_mock()
        self.s3.reset_mock()

    def test_memory_list_is_readable_and_scoped_to_the_user(self) -> None:
        pages = [
            [
                {
                    "memoryRecordId": "mem-fact",
                    "content": {"text": "The user prefers tea."},
                    "namespaces": ["/facts/actor/"],
                    "createdAt": datetime(2026, 9, 5, tzinfo=UTC),
                }
            ],
            [
                {
                    "memoryRecordId": "mem-preference",
                    "content": {
                        "text": json.dumps(
                            {
                                "preference": "Keep answers concise",
                                "context": "The user asked for a short answer.",
                            }
                        )
                    },
                    "namespaces": ["/preferences/actor/"],
                    "createdAt": datetime(2026, 9, 4, tzinfo=UTC),
                }
            ],
            [
                {
                    "memoryRecordId": "mem-summary",
                    "content": {
                        "text": '<topic name="Trip plan">Booked the train.</topic>'
                    },
                    "namespaces": ["/summaries/actor/session-1/"],
                    "createdAt": datetime(2026, 9, 3, tzinfo=UTC),
                    "metadata": {"frogbotScope": {"stringValue": "bot"}},
                }
            ],
        ]
        with (
            patch.object(self.memories, "FROGBOT_MEMORY_ID", "memory-1"),
            patch.object(self.memories, "memory_actor_id", return_value="actor"),
            patch.object(
                self.memories,
                "_bot_sessions",
                return_value={"session-1": {"botId": "bot-1", "botName": "Chief"}},
            ),
            patch.object(self.memories, "_memory_pages", side_effect=pages),
        ):
            result = self.memories._list_user_memories("user-1")

        self.assertEqual(
            [record["kind"] for record in result["records"]],
            ["fact", "preference", "summary"],
        )
        self.assertIn("Why this was learned", result["records"][1]["content"])
        self.assertEqual(result["records"][2]["botName"], "Chief")
        self.assertEqual(result["records"][2]["scope"], "bot")
        self.assertEqual(
            result["records"][2]["content"], "Trip plan\n\nBooked the train."
        )

    def test_memory_record_from_another_user_is_not_accessible(self) -> None:
        self.agentcore.get_memory_record.return_value = {
            "memoryRecord": {
                "memoryRecordId": "mem-secret",
                "namespaces": ["/facts/another-actor/"],
            }
        }
        with (
            patch.object(self.memories, "FROGBOT_MEMORY_ID", "memory-1"),
            patch.object(self.memories, "memory_actor_id", return_value="actor"),
            self.assertRaises(self.support.ApiError) as raised,
        ):
            self.memories._owned_memory_record("user-1", "mem-secret")

        self.assertEqual(raised.exception.status_code, 404)

    def test_bot_memory_list_only_includes_its_own_session(self) -> None:
        own = {
            "memoryRecordId": "mem-own",
            "content": {"text": "Remember the newsletter format"},
            "namespaces": ["/summaries/actor/session-own/"],
            "createdAt": datetime(2026, 9, 6, tzinfo=UTC),
        }
        other = {
            "memoryRecordId": "mem-other",
            "content": {"text": "Other bot's note"},
            "namespaces": ["/summaries/actor/session-other/"],
            "createdAt": datetime(2026, 9, 7, tzinfo=UTC),
        }
        with (
            patch.object(self.memories, "FROGBOT_MEMORY_ID", "memory-1"),
            patch.object(
                self.memories, "_require_bot_memory_access", return_value={"name": "JOPbot"}
            ),
            patch.object(
                self.memories,
                "_bot_memory_namespace",
                return_value="/summaries/actor/session-own/",
            ),
            patch.object(self.memories, "_memory_pages", return_value=[own, other]) as pages,
        ):
            result = self.memories._list_bot_memories("user-1", "bot-1")

        self.assertEqual([item["id"] for item in result["records"]], ["mem-own"])
        self.assertEqual(result["records"][0]["botId"], "bot-1")
        pages.assert_called_once_with(
            "list_memory_records",
            "memoryRecordSummaries",
            namespacePath="/summaries/actor/session-own/",
        )

    def test_bot_note_is_created_in_its_session_only(self) -> None:
        self.agentcore.batch_create_memory_records.return_value = {
            "successfulRecords": [{"memoryRecordId": "mem-bot"}],
            "failedRecords": [],
        }
        with (
            patch.object(self.memories, "FROGBOT_MEMORY_ID", "memory-1"),
            patch.object(
                self.memories, "_require_bot_memory_access", return_value={"name": "JOPbot"}
            ),
            patch.object(
                self.memories,
                "_bot_memory_namespace",
                return_value="/summaries/actor/session-own/",
            ),
        ):
            result = self.memories._create_bot_memory(
                "user-1", "bot-1", {"content": "Use the JOP voice."}
            )

        created = self.agentcore.batch_create_memory_records.call_args.kwargs["records"][0]
        self.assertEqual(created["namespaces"], ["/summaries/actor/session-own/"])
        self.assertEqual(created["metadata"]["frogbotScope"]["stringValue"], "bot")
        self.assertEqual(result["botId"], "bot-1")

    def test_bot_memory_cannot_edit_or_forget_another_bots_record(self) -> None:
        record = {"memoryRecordId": "mem-other"}
        with (
            patch.object(
                self.memories, "_require_bot_memory_access", return_value={"name": "JOPbot"}
            ),
            patch.object(
                self.memories,
                "_owned_memory_record",
                return_value=(record, "/summaries/actor/session-other/", "summary"),
            ),
            patch.object(
                self.memories,
                "_bot_memory_namespace",
                return_value="/summaries/actor/session-own/",
            ),
        ):
            with self.assertRaises(self.support.ApiError) as edit_error:
                self.memories._update_bot_memory(
                    "user-1", "bot-1", "mem-other", {"content": "Not mine"}
                )
            with self.assertRaises(self.support.ApiError) as delete_error:
                self.memories._delete_bot_memory_record("user-1", "bot-1", "mem-other")

        self.assertEqual(edit_error.exception.status_code, 404)
        self.assertEqual(delete_error.exception.status_code, 404)
        self.agentcore.batch_update_memory_records.assert_not_called()
        self.agentcore.batch_delete_memory_records.assert_not_called()

    def test_manual_memory_is_created_in_the_private_actor_namespace(self) -> None:
        self.agentcore.batch_create_memory_records.return_value = {
            "successfulRecords": [{"memoryRecordId": "mem-created"}],
            "failedRecords": [],
        }
        with (
            patch.object(self.memories, "FROGBOT_MEMORY_ID", "memory-1"),
            patch.object(self.memories, "memory_actor_id", return_value="actor"),
        ):
            result = self.memories._create_user_memory(
                "user-1",
                {"kind": "fact", "content": "I live in Boston."},
                request_identifier="12345678-1234-1234-1234-123456789012",
            )

        request = self.agentcore.batch_create_memory_records.call_args.kwargs
        record = request["records"][0]
        self.assertEqual(
            record["requestIdentifier"], "12345678-1234-1234-1234-123456789012"
        )
        self.assertEqual(record["namespaces"], ["/facts/actor/"])
        self.assertEqual(record["metadata"]["frogbotSource"]["stringValue"], "manual")
        self.assertEqual(result["scope"], "personal")

    def test_group_memory_requires_owner_and_uses_group_namespace(self) -> None:
        self.agentcore.batch_create_memory_records.return_value = {
            "successfulRecords": [{"memoryRecordId": "mem-group"}],
            "failedRecords": [],
        }
        with (
            patch.object(self.memories, "FROGBOT_MEMORY_ID", "memory-1"),
            patch.object(
                self.memories, "group_memory_actor_id", return_value="group-actor"
            ),
            patch.object(self.memories, "_require_group_memory_access") as require,
        ):
            result = self.memories._create_group_memory(
                "user-1", "group-1", {"content": "Ship on Friday."}
            )

        require.assert_called_once_with("user-1", "group-1", owner=True)
        record = self.agentcore.batch_create_memory_records.call_args.kwargs["records"][
            0
        ]
        self.assertEqual(record["namespaces"], ["/facts/group-actor/"])
        self.assertEqual(result["scope"], "group")

    def test_group_memory_list_includes_group_owned_preferences(self) -> None:
        preference = {
            "memoryRecordId": "mem-group-preference",
            "content": {"text": json.dumps({"preference": "Prefer short updates"})},
            "createdAt": datetime(2026, 9, 6, tzinfo=UTC),
        }
        with (
            patch.object(self.memories, "FROGBOT_MEMORY_ID", "memory-1"),
            patch.object(
                self.memories, "group_memory_actor_id", return_value="group-actor"
            ),
            patch.object(self.memories, "_require_group_memory_access") as require,
            patch.object(
                self.memories, "_memory_pages", side_effect=[[], [preference], []]
            ),
        ):
            result = self.memories._list_group_memories("user-1", "group-1")

        require.assert_called_once_with("user-1", "group-1")
        self.assertEqual(result["records"][0]["kind"], "preference")
        self.assertEqual(result["records"][0]["content"], "Prefer short updates")
        self.assertEqual(result["records"][0]["scope"], "group")

    def test_memory_update_preserves_its_private_namespace(self) -> None:
        record = {
            "memoryRecordId": "mem-owned",
            "namespaces": ["/facts/actor/"],
            "memoryStrategyId": "facts-strategy",
            "createdAt": datetime(2026, 9, 5, tzinfo=UTC),
        }
        self.agentcore.batch_update_memory_records.return_value = {
            "successfulRecords": [{"memoryRecordId": "mem-owned"}],
            "failedRecords": [],
        }
        with (
            patch.object(self.memories, "FROGBOT_MEMORY_ID", "memory-1"),
            patch.object(
                self.memories,
                "_owned_memory_record",
                return_value=(record, "/facts/actor/", "fact"),
            ),
        ):
            result = self.memories._update_user_memory(
                "user-1", "mem-owned", {"content": "I prefer coffee."}
            )

        update = self.agentcore.batch_update_memory_records.call_args.kwargs
        self.assertEqual(
            set(update["records"][0]),
            {
                "memoryRecordId",
                "timestamp",
                "content",
                "namespaces",
                "memoryStrategyId",
            },
        )
        self.assertEqual(update["records"][0]["namespaces"], ["/facts/actor/"])
        self.assertEqual(result["content"], "I prefer coffee.")

    def test_memory_delete_verifies_ownership_before_batch_delete(self) -> None:
        self.agentcore.batch_delete_memory_records.return_value = {
            "successfulRecords": [{"memoryRecordId": "mem-owned"}],
            "failedRecords": [],
        }
        with (
            patch.object(self.memories, "FROGBOT_MEMORY_ID", "memory-1"),
            patch.object(self.memories, "_owned_memory_record") as owned,
        ):
            result = self.memories._delete_user_memory_record("user-1", "mem-owned")

        owned.assert_called_once_with("user-1", "mem-owned")
        self.agentcore.batch_delete_memory_records.assert_called_once_with(
            memoryId="memory-1", records=[{"memoryRecordId": "mem-owned"}]
        )
        self.assertEqual(result, {"deleted": True})

    def test_memory_export_is_a_portable_private_download(self) -> None:
        self.s3.generate_presigned_url.return_value = "https://download.example/memory"
        snapshot = {"records": [], "rawConversationRetentionDays": 30}
        with (
            patch.object(self.memories, "FILES_BUCKET_NAME", "user-files"),
            patch.object(self.memories, "memory_actor_id", return_value="actor"),
            patch.object(self.memories, "_list_user_memories", return_value=snapshot),
        ):
            result = self.memories._export_user_memories("user-1")

        uploaded = self.s3.put_object.call_args.kwargs
        self.assertEqual(uploaded["Key"], "users/actor/exports/heytim-memory.json")
        self.assertEqual(json.loads(uploaded["Body"])["memories"], [])
        self.assertEqual(result["url"], "https://download.example/memory")


if __name__ == "__main__":
    unittest.main()
