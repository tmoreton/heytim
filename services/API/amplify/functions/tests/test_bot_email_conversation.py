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

    def test_existing_email_thread_runs_while_new_mail_is_reviewed(self) -> None:
        user_id = str(uuid.uuid4())
        address = mail_address(user_id, "bot-1", "abcdefghijklmnop")
        bot = {
            "pk": f"USER#{user_id}",
            "sk": "BOT#bot-1",
            "entity": "BOT",
            "id": "bot-1",
            "emailToken": "abcdefghijklmnop",
            "emailInboundMode": "review",
            "emailOwnerAddress": "owner@example.com",
        }
        inbox = {
            "pk": f"USER#{user_id}",
            "sk": "INBOX#bot-1#2026-09-24T14:30:11Z#mail-2",
            "entity": "BOT_EMAIL",
            "botId": "bot-1",
            "receivedAt": "2026-09-24T14:30:11Z",
            "recipient": address,
            "from": "owner@example.com",
            "subject": "Re: Status",
            "body": "What is next?",
            "conversationBody": "What is next?",
            "attachmentNames": [],
            "authentication": "verified",
            "disposition": "automatic",
            "threadReply": True,
            "linkedTurnId": "turn-email-2",
            "sesMessageId": "ses-in-2",
            "messageIdHeader": "<owner-2@example.com>",
            "inReplyTo": "<ses-outbound@email.amazonses.com>",
        }
        self.table.items[(bot["pk"], bot["sk"])] = bot
        self.table.items[(inbox["pk"], inbox["sk"])] = inbox
        saved: dict = {}

        def save_turn(_table, _user_id, item, **kwargs):
            saved.update(kwargs)
            self.table.items[(item["pk"], item["sk"])] = dict(item)

        with patch.object(
            self.email_inbound,
            "put_user_item_while_account_active",
            side_effect=save_turn,
        ):
            self.email_inbound._process_email_inbound(
                {"messageId": "queue-email-2"},
                {
                    "type": "EMAIL_INBOUND",
                    "userId": user_id,
                    "botId": "bot-1",
                    "inboxKey": inbox["sk"],
                    "turnId": "turn-email-2",
                },
            )

        turn = next(
            item
            for (pk, _sk), item in self.table.items.items()
            if pk == f"CHAT#{user_id}#bot-1"
        )
        self.assertEqual(turn["source"], "email")
        guard = saved["required_item_condition"]
        self.assertNotIn("emailInboundMode", guard["ConditionExpression"])
        self.assertNotIn(":automatic", guard["ExpressionAttributeValues"])

    def test_schedule_email_delivery_overrides_app_only_bot_responses(self) -> None:
        turn = {
            "id": "turn-daily",
            "sk": "TURN#2026-09-24T12:00:00Z#turn-daily",
            "source": "schedule",
            "scheduleDeliveryMode": "email",
        }
        bot = {
            "emailDeliveryMode": "appOnly",
            "emailToken": "abcdefghijklmnop",
            "emailOwnerAddress": "owner@example.com",
        }
        with patch.object(
            self.notifications, "EMAIL_QUEUE_URL", "https://sqs.example/email"
        ):
            self.notifications._queue_email_delivery(
                "owner", "brief", turn, bot, event="reply"
            )

        request = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(request["turnId"], "turn-daily")
        self.assertEqual(request["event"], "reply")

    def test_scheduled_turn_carries_delivery_and_timezone(self) -> None:
        self.table.put_item(
            Item={
                "pk": "USER#owner",
                "sk": "SCHEDULE#daily",
                "id": "daily",
                "botId": "brief",
                "name": "Daily AI brief",
                "prompt": "Summarize today's news.",
                "enabled": True,
                "deliveryMode": "email",
                "timezone": "America/New_York",
            }
        )
        with patch.object(self.scheduled_job, "_process_agent_reply"):
            self.scheduled_job._process_scheduled_agent_reply(
                {"messageId": "queue-1"},
                {
                    "userId": "owner",
                    "botId": "brief",
                    "scheduleId": "daily",
                    "executionId": "execution-1",
                    "scheduledTime": "2026-09-24T12:00:00Z",
                },
            )

        turn = next(
            item
            for (pk, _sk), item in self.table.items.items()
            if pk == "CHAT#owner#brief"
        )
        self.assertEqual(turn["scheduleDeliveryMode"], "email")
        self.assertEqual(turn["scheduleTimezone"], "America/New_York")
