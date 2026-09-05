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
            result = self.memories._delete_user_memory_record(
                "user-1", "mem-owned"
            )

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
        self.assertEqual(uploaded["Key"], "users/actor/exports/froggybot-memory.json")
        self.assertEqual(json.loads(uploaded["Body"])["memories"], [])
        self.assertEqual(result["url"], "https://download.example/memory")


if __name__ == "__main__":
    unittest.main()
