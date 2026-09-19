from __future__ import annotations

import json
import uuid
from unittest.mock import patch

from shared.bot_inbox import mail_address
from worker_test_case import WorkerTestCase


class BotEmailConversationTests(WorkerTestCase):
    def test_email_inbound_creates_a_normal_direct_turn(self) -> None:
        user_id = str(uuid.uuid4())
        address = mail_address(user_id, "bot-1", "abcdefghijklmnop")
        bot = {
            "pk": f"USER#{user_id}",
            "sk": "BOT#bot-1",
            "entity": "BOT",
            "id": "bot-1",
            "emailToken": "abcdefghijklmnop",
            "emailInboundMode": "automatic",
            "emailOwnerAddress": "owner@example.com",
        }
        inbox = {
            "pk": f"USER#{user_id}",
            "sk": "INBOX#bot-1#2026-09-18T01:00:00Z#mail-1",
            "entity": "BOT_EMAIL",
            "botId": "bot-1",
            "receivedAt": "2026-09-18T01:00:00Z",
            "recipient": address,
            "from": "owner@example.com",
            "subject": "Status",
            "body": "What changed?",
            "conversationBody": "What changed?",
            "attachmentNames": [],
            "authentication": "verified",
            "disposition": "automatic",
            "linkedTurnId": "turn-email-1",
            "sesMessageId": "ses-in-1",
            "messageIdHeader": "<owner-1@example.com>",
        }
        self.table.items[(bot["pk"], bot["sk"])] = bot
        self.table.items[(inbox["pk"], inbox["sk"])] = inbox

        def save_turn(_table, _user_id, item, **_kwargs):
            self.table.items[(item["pk"], item["sk"])] = dict(item)

        with patch.object(
            self.email_inbound,
            "put_user_item_while_account_active",
            side_effect=save_turn,
        ):
            self.email_inbound._process_email_inbound(
                {"messageId": "queue-email-1"},
                {
                    "type": "EMAIL_INBOUND",
                    "userId": user_id,
                    "botId": "bot-1",
                    "inboxKey": inbox["sk"],
                    "turnId": "turn-email-1",
                },
            )

        turn = next(
            item
            for (pk, _sk), item in self.table.items.items()
            if pk == f"CHAT#{user_id}#bot-1"
        )
        self.assertEqual(turn["source"], "email")
        self.assertEqual(turn["userText"], "Email subject: Status\n\nWhat changed?")
        queued = [
            json.loads(call.kwargs["MessageBody"])
            for call in self.sqs.send_message.call_args_list
        ]
        self.assertIn(
            {
                "type": "AGENT_REPLY",
                "userId": user_id,
                "botId": "bot-1",
                "turnKey": turn["sk"],
            },
            queued,
        )
