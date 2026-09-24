from __future__ import annotations

import importlib
import os
import sys
import uuid
from email import policy
from email.parser import BytesParser
from unittest.mock import MagicMock, patch

from api_test_case import ApiTestCase
from shared.bot_inbox import mail_address


class BotMailSenderTests(ApiTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        import boto3

        cls.ses = MagicMock()
        with (
            patch.dict(
                os.environ,
                {
                    "TABLE_NAME": "data",
                    "MAIL_QUEUE_ARN": "arn:aws:sqs:us-east-1:123:mail",
                },
            ),
            patch.object(
                boto3,
                "resource",
                return_value=type(
                    "Resource", (), {"Table": lambda _self, _name: cls.data_table}
                )(),
            ),
            patch.object(boto3, "client", return_value=cls.ses),
        ):
            sys.modules.pop("email_send.handler", None)
            cls.sender = importlib.import_module("email_send.handler")

    def test_sender_uses_a_clean_from_address_and_private_reply_route(self) -> None:
        user_id = str(uuid.uuid4())
        bot = {
            "pk": f"USER#{user_id}",
            "sk": "BOT#bot-1",
            "id": "bot-1",
            "name": "Scout",
            "emailToken": "abcdefghijklmnop",
            "emailOwnerAddress": "owner@example.com",
            "emailDeliveryMode": "emailReplies",
        }
        turn = {
            "pk": f"CHAT#{user_id}#bot-1",
            "sk": "TURN#2026-09-18T01:00:00Z#turn-1",
            "id": "turn-1",
            "status": "COMPLETE",
            "source": "email",
            "emailSubject": "Question",
            "emailMessageIdHeader": "<owner-1@example.com>",
            "assistantText": "Here is the answer.",
        }
        self.data_table.put_item(Item=bot)
        self.data_table.put_item(Item=turn)
        self.ses.send_email.return_value = {"MessageId": "ses-outbound-1"}

        self.sender._process(
            {
                "userId": user_id,
                "botId": "bot-1",
                "turnId": "turn-1",
                "turnKey": turn["sk"],
                "event": "reply",
            }
        )

        request = self.ses.send_email.call_args.kwargs
        address = mail_address(user_id, "bot-1", bot["emailToken"])
        self.assertEqual(request["FromEmailAddress"], "scout@bots.heytim.ai")
        self.assertEqual(request["Destination"], {"ToAddresses": ["owner@example.com"]})
        raw_bytes = request["Content"]["Raw"]["Data"]
        raw = raw_bytes.decode("utf-8")
        parsed = BytesParser(policy=policy.default).parsebytes(raw_bytes)
        self.assertIn("From: Scout via Hey Tim <scout@bots.heytim.ai>", raw)
        self.assertEqual(parsed["Reply-To"].addresses[0].display_name, "Scout")
        self.assertEqual(parsed["Reply-To"].addresses[0].addr_spec, address)
        self.assertIn("Subject: Re: Question", raw)
        self.assertIn("In-Reply-To: <owner-1@example.com>", raw)
        self.assertIn("Here is the answer.", raw)

    def test_app_response_does_not_pretend_to_be_an_email_reply(self) -> None:
        route = "private-route@bots.heytim.ai"
        message = self.sender._message(
            {"name": "Résumé Helper", "emailOwnerAddress": "owner@example.com"},
            {
                "source": "app",
                "emailSubject": "Weekly summary",
                "assistantText": "Here is your summary.",
            },
            route,
            "reply",
        )

        self.assertEqual(
            message["From"],
            "Résumé Helper via Hey Tim <resume-helper@bots.heytim.ai>",
        )
        self.assertEqual(message["Reply-To"].addresses[0].display_name, "Résumé Helper")
        self.assertEqual(message["Reply-To"].addresses[0].addr_spec, route)
        self.assertEqual(message["Subject"], "Weekly summary")
        self.assertNotIn("Re:", message["Subject"])

    def test_scheduled_email_uses_local_date_and_safe_rich_text(self) -> None:
        message = self.sender._message(
            {"name": "News Scout", "emailOwnerAddress": "owner@example.com"},
            {
                "source": "schedule",
                "scheduleName": "Daily AI Brief",
                "scheduleTimezone": "America/New_York",
                "createdAt": "2026-09-24T12:00:00+00:00",
                "assistantText": (
                    "1. **Important update** Read https://example.com/news\n"
                    "2. <script>alert('no')</script>"
                ),
            },
            "private-route@bots.heytim.ai",
            "reply",
        )

        self.assertEqual(message["Subject"], "Daily AI Brief — Thu, Sep 24")
        rich = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("<ol", rich)
        self.assertIn("<strong>Important update</strong>", rich)
        self.assertIn('href="https://example.com/news"', rich)
        self.assertNotIn("<script>", rich)
        self.assertIn("&lt;script&gt;", rich)
