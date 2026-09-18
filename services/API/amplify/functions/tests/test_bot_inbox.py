from __future__ import annotations

import base64
import importlib
import io
import os
import sys
import uuid
from unittest.mock import patch

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
        self.assertIsNone(resolve_mail_address(Lookup(), address.replace("bots.froggybot.com", "example.com")))

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

    def test_address_creation_waits_for_mail_activation(self) -> None:
        with (
            patch.object(self.inbox, "INBOX_AVAILABLE", False),
            self.assertRaises(self.support.ApiError) as raised,
        ):
            self.inbox.enable_bot_inbox("user-1", "bot-1")
        self.assertEqual(raised.exception.status_code, 503)

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
