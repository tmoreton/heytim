from __future__ import annotations

import json
from unittest.mock import patch

from api_test_case import ApiTestCase


class GroupBillingIdentityTests(ApiTestCase):
    def test_authenticated_sender_is_persisted_on_every_group_reply(self) -> None:
        meta = {"pk": "GROUP#work", "sk": "META", "entity": "GROUP"}
        group_bot = {
            "pk": "GROUP#work",
            "sk": "BOT#chief",
            "entity": "GROUP_BOT",
            "botId": "chief",
            "botOwnerId": "bot-owner",
            "name": "Chief",
            "systemRole": "chief",
        }

        with (
            patch.object(
                self.group_messages,
                "_require_group_member",
                return_value=(meta, [group_bot]),
            ),
            patch.object(
                self.group_messages,
                "_get_bot",
                return_value={"id": "chief", "toolIds": []},
            ),
            patch.object(
                self.group_messages,
                "_resolve_group_attachments",
                return_value=[],
            ),
            patch.object(
                self.group_messages.catalog,
                "approval_tool_names",
                return_value=[],
            ),
            patch.object(
                self.group_messages, "_now", return_value="2026-09-11T12:00:00Z"
            ),
        ):
            result = self.group_messages._send_group_message(
                "billing-user",
                "Taylor",
                "work",
                {"text": "Plan it.", "replyBotId": "chief"},
            )

        stored = list(self.data_table.items.values())
        user_message = next(
            item for item in stored if item.get("id") == result["messageId"]
        )
        reply = next(item for item in stored if item.get("id") == result["replyId"])
        self.assertEqual(user_message["billingUserId"], "billing-user")
        self.assertEqual(reply["billingUserId"], "billing-user")
        request = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(request["requestedBy"], "billing-user")


if __name__ == "__main__":
    import unittest

    unittest.main()
