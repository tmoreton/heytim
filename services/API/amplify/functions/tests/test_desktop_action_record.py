from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from api_test_case import ApiTestCase


class DesktopActionRecordTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.table = MagicMock()
        self.bot = patch.object(self.direct_chat, "_get_bot", return_value={"id": "bot-1"})
        self.storage = patch.object(self.direct_chat, "table", self.table)
        self.bot.start()
        self.storage.start()
        self.addCleanup(self.bot.stop)
        self.addCleanup(self.storage.stop)
        self.payload = {
            "actionId": str(uuid.uuid4()),
            "intent": "Create a note called Hello",
            "result": "Created the note Hello.",
            "outcome": "complete",
            "occurredAt": datetime.now(UTC).isoformat(timespec="seconds"),
        }

    def test_records_complete_local_turn_without_queuing_model(self) -> None:
        with patch.object(self.direct_chat, "sqs") as queue:
            self.assertTrue(self.direct_chat._record_desktop_action(
                "user-1", "bot-1", self.payload
            )["recorded"])
        item = self.table.put_item.call_args.kwargs["Item"]
        self.assertEqual(item["source"], "desktop_action")
        self.assertEqual(item["status"], "COMPLETE")
        self.assertEqual(item["userText"], self.payload["intent"])
        self.assertEqual(item["assistantText"], self.payload["result"])
        queue.send_message.assert_not_called()

    def test_rejects_unbounded_or_invalid_client_observation(self) -> None:
        for changed in (
            {"actionId": "invalid"},
            {"outcome": "approved"},
            {"occurredAt": "2020-01-01T00:00:00Z"},
            {"result": "x" * 8_001},
        ):
            with self.subTest(changed=next(iter(changed))), self.assertRaises(
                self.support.ApiError
            ):
                self.direct_chat._record_desktop_action(
                    "user-1", "bot-1", {**self.payload, **changed}
                )
        self.table.put_item.assert_not_called()

    def test_runtime_history_marks_mac_result_as_device_report(self) -> None:
        from worker import agent

        turn = {
            "id": self.payload["actionId"], "source": "desktop_action",
            "userText": self.payload["intent"],
            "assistantText": self.payload["result"],
            "status": "COMPLETE",
        }
        with patch.object(agent.table, "query", return_value={"Items": [turn]}):
            history = agent._get_history("user-1", "bot-1")
        self.assertEqual(history[0]["role"], "user")
        self.assertIn("not independently verify", history[1]["content"][0]["text"])
        self.assertIn(self.payload["result"], history[1]["content"][0]["text"])
