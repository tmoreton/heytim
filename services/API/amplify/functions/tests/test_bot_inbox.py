from __future__ import annotations

import base64
import importlib
import io
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

from api_test_case import ApiTestCase
from shared.bot_inbox import mail_address, resolve_mail_address


class BotInboxTests(ApiTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.inbox = cls.bot_inbox

    def test_address_routes_only_to_the_current_bot_token(self) -> None:
        user_id = str(uuid.uuid4())
        bot = {"id": "catalog-chief", "emailToken": "abcdefghijklmnop"}
        address = mail_address(user_id, bot["id"], bot["emailToken"])

        class Lookup:
            def query(self, **_kwargs):
                return {"Items": [bot]}

        self.assertEqual(resolve_mail_address(Lookup(), address), (user_id, bot))
        self.assertIsNone(resolve_mail_address(Lookup(), address.replace("abcdefghijklmnop", "qrstuvwxyzabcdef")))
        self.assertIsNone(resolve_mail_address(Lookup(), address.replace("bots.heytim.ai", "example.com")))

    def test_inbox_list_keeps_one_bot_scoped_and_hides_internal_mail_fields(self) -> None:
        user_id = str(uuid.uuid4())
        bot = {"id": "bot-1", "emailToken": "abcdefghijklmnop"}
        item = {
            "pk": f"USER#{user_id}", "sk": "INBOX#bot-1#2026-09-18T01:00:00Z#id",
            "receivedAt": "2026-09-18T01:00:00Z", "from": "Sender <sender@example.com>",
            "subject": "Hello", "body": "Please review", "authentication": "unverified",
            "rawObjectKey": "received/private", "sesMessageId": "private",
        }
        with (
            patch.object(self.inbox, "_get_bot", return_value=bot),
            patch.object(self.inbox.table, "query", return_value={"Items": [item]}, create=True),
            patch.object(self.inbox, "INBOX_AVAILABLE", True),
        ):
            result = self.inbox.list_bot_inbox(user_id, "bot-1")
        self.assertEqual(result["address"], mail_address(user_id, "bot-1", bot["emailToken"]))
        self.assertEqual(result["messages"][0]["subject"], "Hello")
        self.assertNotIn("rawObjectKey", result["messages"][0])
        self.assertNotIn("sesMessageId", result["messages"][0])

    def test_delete_rejects_another_bots_mail_key(self) -> None:
        identifier = base64.urlsafe_b64encode(b"INBOX#bot-2#now#id").decode().rstrip("=")
        with (
            patch.object(self.inbox, "_get_bot", return_value={"id": "bot-1"}),
            self.assertRaises(self.support.ApiError),
        ):
            self.inbox.delete_inbox_message("user-1", "bot-1", identifier)
        self.assertNotIn({"pk": "USER#user-1", "sk": "INBOX#bot-2#now#id"}, self.data_table.deleted)

    def test_reviewed_email_keeps_its_thread_when_added_to_chat(self) -> None:
        inbox_key = "INBOX#bot-1#2026-09-18T01:00:00Z#ses-1"
        message_id = base64.urlsafe_b64encode(inbox_key.encode()).decode().rstrip("=")
        self.data_table.put_item(Item={
            "pk": "USER#user-1",
            "sk": inbox_key,
            "entity": "BOT_EMAIL",
            "botId": "bot-1",
            "from": "owner@example.com",
            "recipient": "route@bots.heytim.ai",
            "subject": "Status",
            "messageIdHeader": "<owner-1@example.com>",
            "references": "<earlier@example.com>",
        })

        with (
            patch.object(self.direct_chat, "_get_bot", return_value={"id": "bot-1"}),
            patch.object(self.direct_chat, "_partition_items", return_value=[]),
        ):
            result = self.direct_chat._send_message(
                "user-1",
                "bot-1",
                {"text": "Please handle this email.", "inboxMessageId": message_id},
            )

        turn = next(item for item in self.data_table.put if item.get("entity") == "TURN")
        self.assertEqual(turn["source"], "email")
        self.assertEqual(turn["emailMessageIdHeader"], "<owner-1@example.com>")
        self.assertEqual(turn["emailReferences"], "<earlier@example.com>")
        linked = next(
            update
            for update in self.data_table.updated
            if "linkedTurnId" in update.get("UpdateExpression", "")
        )
        self.assertEqual(linked["ExpressionAttributeValues"][":turnId"], result["turnId"])

    def test_address_creation_waits_for_mail_activation(self) -> None:
        with (
            patch.object(self.inbox, "INBOX_AVAILABLE", False),
            self.assertRaises(self.support.ApiError) as raised,
        ):
            self.inbox.enable_bot_inbox("user-1", "bot-1")
        self.assertEqual(raised.exception.status_code, 503)

    def test_preferences_require_supported_modes_and_a_verified_email(self) -> None:
        with (
            patch.object(self.inbox, "INBOX_AVAILABLE", True),
            patch.object(self.inbox, "_get_bot", return_value={"id": "bot-1"}),
            self.assertRaises(self.support.ApiError) as raised,
        ):
            self.inbox.update_bot_email_preferences(
                "user-1",
                "bot-1",
                {"incomingMode": "automatic", "responseMode": "allResponses"},
                None,
            )
        self.assertEqual(raised.exception.status_code, 409)

        with (
            patch.object(self.inbox, "INBOX_AVAILABLE", True),
            self.assertRaises(self.support.ApiError) as invalid,
        ):
            self.inbox.update_bot_email_preferences(
                "user-1",
                "bot-1",
                {"incomingMode": "public", "responseMode": "allResponses"},
                "owner@example.com",
            )
        self.assertEqual(invalid.exception.status_code, 400)

    def test_bot_edit_cannot_restore_an_address_changed_concurrently(self) -> None:
        values = {
            "name": "Mail helper", "tagline": "", "prompt": "Help with mail.",
            "color": "#58BEAA", "toolIds": [], "extraToolIds": [],
            "alwaysAllowedToolIds": [], "githubRepositoryAccess": {},
            "skillIds": [], "skillVersions": {}, "emailToken": "oldtoken",
        }
        with patch.object(self.bots.table, "put_item") as put:
            self.bots._put_bot(
                "user-1", values, bot_id="bot-1",
                expected_email_token="oldtoken", check_email_token=True,
            )
        request = put.call_args.kwargs
        self.assertEqual(request["Item"]["emailToken"], "oldtoken")
        self.assertEqual(
            request["ConditionExpression"],
            "attribute_exists(pk) AND attribute_not_exists(emailInboxClosing) "
            "AND emailToken = :expectedEmailToken",
        )
        self.assertEqual(request["ExpressionAttributeValues"], {
            ":expectedEmailToken": "oldtoken"
        })


class BotMailReceiverTests(ApiTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        import boto3

        with (
            patch.dict(os.environ, {
                "TABLE_NAME": "data", "MAIL_BUCKET_NAME": "mail-bucket",
                "MAIL_TOPIC_ARN": "arn:aws:sns:us-east-1:123:mail",
            }),
            patch.object(boto3, "resource", return_value=type("Resource", (), {
                "Table": lambda _self, _name: cls.data_table
            })()),
            patch.object(boto3, "client", return_value=cls.s3),
        ):
            sys.modules.pop("email_ingest.handler", None)
            cls.receiver = importlib.import_module("email_ingest.handler")

    def test_plain_text_preview_excludes_attachment_content(self) -> None:
        raw = (
            b"From: Alice <alice@example.com>\nSubject: Status\nMIME-Version: 1.0\n"
            b"Content-Type: multipart/mixed; boundary=part\n\n"
            b"--part\nContent-Type: text/plain; charset=utf-8\n\nThe update is ready.\n"
            b"--part\nContent-Type: text/plain; name=secret.txt\n"
            b"Content-Disposition: attachment; filename=secret.txt\n\nsecret value\n--part--\n"
        )
        result = self.receiver._preview(raw, {})
        self.assertIn("The update is ready", result["body"])
        self.assertNotIn("secret value", result["body"])
        self.assertEqual(result["attachmentNames"], ["secret.txt"])

    def test_html_preview_does_not_include_script_content(self) -> None:
        raw = (
            b"From: Alice <alice@example.com>\nSubject: Update\n"
            b"Content-Type: text/html; charset=utf-8\n\n"
            b"<p>Useful update</p><script>hidden instructions</script>"
        )
        result = self.receiver._preview(raw, {})
        self.assertIn("Useful update", result["body"])
        self.assertNotIn("hidden instructions", result["body"])

    def test_receiver_uses_envelope_recipient_and_keeps_email_inert(self) -> None:
        user_id = str(uuid.uuid4())
        bot = {"id": "catalog-chief", "emailToken": "abcdefghijklmnop"}
        address = mail_address(user_id, bot["id"], bot["emailToken"])
        raw = b"From: Sender <sender@example.com>\nTo: other@example.com\nSubject: Hello\n\nPlease help"
        notification = {
            "notificationType": "Received",
            "mail": {"messageId": "ses-id", "timestamp": "2026-09-18T01:00:00Z"},
            "receipt": {
                "spamVerdict": {"status": "PASS"}, "virusVerdict": {"status": "PASS"},
                "dmarcVerdict": {"status": "FAIL"},
                "recipients": [address],
                "action": {"type": "S3", "bucketName": "mail-bucket", "objectKey": "ses-id"},
            },
        }
        self.s3.get_object.return_value = {"Body": io.BytesIO(raw)}
        with (
            patch.object(self.receiver, "resolve_mail_address", return_value=(user_id, bot)) as resolve,
            patch.object(self.receiver, "put_user_item_while_account_active") as save,
        ):
            self.receiver._process_notification(notification)
        resolve.assert_called_once_with(self.receiver.table, address)
        item = save.call_args.args[2]
        self.assertEqual(item["botId"], "catalog-chief")
        self.assertEqual(item["body"], "Please help")
        self.assertEqual(item["authentication"], "unverified")
        self.assertEqual(item["rawObjectKey"], "received/ses-id")
        self.assertEqual(
            save.call_args.kwargs["required_item_condition"]
                ["ExpressionAttributeValues"][":expectedEmailToken"],
            "abcdefghijklmnop",
        )

    def test_receiver_discards_mail_after_address_replacement(self) -> None:
        user_id = str(uuid.uuid4())
        bot = {"id": "bot-1", "emailToken": "oldtoken"}
        self.data_table.put_item(Item={
            "pk": f"USER#{user_id}", "sk": "BOT#bot-1",
            "id": "bot-1", "emailToken": "newtoken",
        })
        notification = {
            "notificationType": "Received",
            "mail": {"messageId": "ses-new", "timestamp": "2026-09-18T01:00:00Z"},
            "receipt": {
                "spamVerdict": {"status": "PASS"},
                "virusVerdict": {"status": "PASS"},
                "recipients": ["old@example.com"],
                "action": {"type": "S3", "bucketName": "mail-bucket", "objectKey": "ses-new"},
            },
        }
        self.s3.get_object.return_value = {"Body": io.BytesIO(b"Subject: Old mail\n\nNo longer routed")}
        with patch.object(self.receiver, "resolve_mail_address", return_value=(user_id, bot)):
            self.receiver._process_notification(notification)
        self.assertFalse(any(
            key[1].startswith("INBOX#bot-1#") for key in self.data_table.items
        ))

    def test_verified_owner_email_is_queued_for_the_bot(self) -> None:
        user_id = str(uuid.uuid4())
        bot = {
            "id": "bot-1",
            "emailToken": "abcdefghijklmnop",
            "emailInboundMode": "automatic",
            "emailOwnerAddress": "owner@example.com",
        }
        address = mail_address(user_id, bot["id"], bot["emailToken"])
        notification = {
            "notificationType": "Received",
            "mail": {
                "messageId": "ses-auto",
                "timestamp": "2026-09-18T01:00:00Z",
                "source": "owner@example.com",
            },
            "receipt": {
                "spamVerdict": {"status": "PASS"},
                "virusVerdict": {"status": "PASS"},
                "dmarcVerdict": {"status": "PASS"},
                "recipients": [address],
                "action": {
                    "type": "S3",
                    "bucketName": "mail-bucket",
                    "objectKey": "ses-auto",
                },
            },
        }
        self.s3.get_object.return_value = {
            "Body": io.BytesIO(
                b"From: Owner <owner@example.com>\nSubject: Continue\n"
                b"Message-ID: <owner-1@example.com>\n\nDo the next step.\n\n"
                b"On yesterday, Someone wrote:\n> old text"
            )
        }
        queue = MagicMock()
        with (
            patch.object(self.receiver, "resolve_mail_address", return_value=(user_id, bot)),
            patch.object(self.receiver, "put_user_item_while_account_active") as save,
            patch.object(self.receiver, "JOB_QUEUE_URL", "https://sqs.example/jobs"),
            patch.object(self.receiver, "sqs", queue),
        ):
            self.receiver._process_notification(notification)

        item = save.call_args.args[2]
        self.assertEqual(item["disposition"], "automatic")
        self.assertEqual(item["conversationBody"], "Do the next step.")
        queued = __import__("json").loads(queue.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(queued["type"], "EMAIL_INBOUND")
        self.assertEqual(queued["turnId"], item["linkedTurnId"])

    def test_authenticated_mail_from_another_sender_stays_review_only(self) -> None:
        user_id = str(uuid.uuid4())
        bot = {
            "id": "bot-1",
            "emailToken": "abcdefghijklmnop",
            "emailInboundMode": "automatic",
            "emailOwnerAddress": "owner@example.com",
        }
        notification = {
            "notificationType": "Received",
            "mail": {
                "messageId": "ses-other",
                "timestamp": "2026-09-18T01:00:00Z",
                "source": "other@example.net",
            },
            "receipt": {
                "spamVerdict": {"status": "PASS"},
                "virusVerdict": {"status": "PASS"},
                "dmarcVerdict": {"status": "PASS"},
                "recipients": ["bot@example.com"],
                "action": {
                    "type": "S3",
                    "bucketName": "mail-bucket",
                    "objectKey": "ses-other",
                },
            },
        }
        self.s3.get_object.return_value = {
            "Body": io.BytesIO(b"From: other@example.net\nSubject: Hello\n\nRun this")
        }
        queue = MagicMock()
        with (
            patch.object(self.receiver, "resolve_mail_address", return_value=(user_id, bot)),
            patch.object(self.receiver, "put_user_item_while_account_active") as save,
            patch.object(self.receiver, "JOB_QUEUE_URL", "https://sqs.example/jobs"),
            patch.object(self.receiver, "sqs", queue),
        ):
            self.receiver._process_notification(notification)

        self.assertEqual(save.call_args.args[2]["disposition"], "review")
        queue.send_message.assert_not_called()


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

    def test_sender_uses_the_bot_route_and_verified_owner(self) -> None:
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
        self.assertEqual(request["FromEmailAddress"], address)
        self.assertEqual(request["Destination"], {"ToAddresses": ["owner@example.com"]})
        raw = request["Content"]["Raw"]["Data"].decode("utf-8")
        self.assertIn("Subject: Re: Question", raw)
        self.assertIn("In-Reply-To: <owner-1@example.com>", raw)
        self.assertIn("Here is the answer.", raw)
