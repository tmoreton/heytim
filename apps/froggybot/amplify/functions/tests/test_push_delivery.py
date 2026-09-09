from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from shared.push_delivery import receipt_key, receipt_status, ticket_status
from worker_test_case import FakeTable, WorkerTestCase


class DeliveryStatusTests(unittest.TestCase):
    def test_ticket_acceptance_is_not_device_delivery(self):
        self.assertEqual(ticket_status(2, 2, 0), "ACCEPTED")
        self.assertEqual(ticket_status(2, 1, 1), "PARTIALLY_ACCEPTED")
        self.assertEqual(ticket_status(2, 0, 2), "REJECTED")
        self.assertEqual(ticket_status(2, 0, 0), "UNKNOWN")
        self.assertEqual(ticket_status(0, 0, 0), "UNKNOWN")

    def test_receipts_preserve_failures_and_unknown_outcomes(self):
        states = {"a": {"status": "PROVIDER_ACCEPTED"}}
        self.assertEqual(receipt_status(states, 0, 0), "PROVIDER_ACCEPTED")
        self.assertEqual(receipt_status(states, 1, 0), "PARTIAL")
        self.assertEqual(receipt_status(states, 0, 1), "UNKNOWN")
        states["b"] = {"status": "PENDING"}
        self.assertEqual(receipt_status(states, 0, 0), "PENDING_RECEIPTS")
        states["b"] = {"status": "UNKNOWN"}
        self.assertEqual(receipt_status(states, 0, 0), "UNKNOWN")
        self.assertEqual(receipt_status({"a": {"status": "FAILED"}}, 0, 0), "FAILED")


class DeliveryTable(FakeTable):
    """Apply delivery updates so tests exercise persisted-state recovery."""

    def update_item(self, **kwargs):
        super().update_item(**kwargs)
        key = kwargs["Key"]
        item = self.items[(key["pk"], key["sk"])]
        values = kwargs["ExpressionAttributeValues"]
        expression = kwargs["UpdateExpression"]
        if expression.startswith("SET receiptStates ="):
            item.update(
                receiptStates=values[":states"],
                rejectedTickets=values[":rejected"],
                unknownTickets=values[":unknown"],
                receiptStatus=values[":status"],
            )
        elif expression.startswith("SET receiptStates."):
            digest = kwargs["ExpressionAttributeNames"]["#receipt"]
            item["receiptStates"][digest]["status"] = values[":status"]
        elif expression.startswith("SET receiptStatus"):
            item["receiptStatus"] = values[":status"]
        elif expression.startswith("SET receiptCheckQueued"):
            item["receiptCheckQueued"] = values[":queued"]
        else:
            item["status"] = values[":status"]


class PushDeliveryTests(WorkerTestCase):
    def setUp(self):
        super().setUp()
        self.delivery_table = DeliveryTable()
        for name, value in (("table", self.delivery_table), ("sqs", self.sqs)):
            self.enterContext(patch.object(self.notifications, name, value))
        self.enterContext(
            patch.object(
                self.notifications,
                "_push_tokens",
                return_value=[{"tokenId": "token-1", "token": "ExpoPushToken[test]"}],
            )
        )
        self.remove = self.enterContext(
            patch.object(self.notifications, "_remove_push_token")
        )
        self.request = {
            "notificationId": "one",
            "userId": "user-1",
            "botId": "bot-1",
            "botName": "Chief",
            "messageId": "message-1",
            "answer": "Draft ready",
        }
        self.key = self.notifications._notification_key(self.request)

    def saved(self):
        return self.delivery_table.get_item(Key=self.key)["Item"]

    def send(self, response):
        with patch.object(self.notifications, "_post_json", return_value=response):
            self.notifications._send_push_notification(self.request)

    def test_all_rejected_is_not_sent(self):
        self.send(
            {"data": [{"status": "error", "details": {"error": "DeviceNotRegistered"}}]}
        )
        self.assertEqual(self.saved()["status"], "REJECTED")
        self.sqs.send_message.assert_not_called()
        self.remove.assert_called_once_with("user-1", "token-1")

    def test_missing_tickets_remain_unknown(self):
        self.send({"data": []})
        self.assertEqual(self.saved()["status"], "UNKNOWN")

    def test_extra_tickets_do_not_claim_complete_acceptance(self):
        self.send(
            {
                "data": [
                    {"status": "ok", "id": "receipt-1"},
                    {"status": "ok", "id": "extra"},
                ]
            }
        )
        self.assertEqual(self.saved()["status"], "UNKNOWN")
        self.assertEqual(self.saved()["unknownTickets"], 1)

    def test_uncertain_submission_is_not_blindly_resent(self):
        with patch.object(
            self.notifications, "_post_json", side_effect=TimeoutError
        ) as post:
            with self.assertRaises(TimeoutError):
                self.notifications._send_push_notification(self.request)
            self.notifications._send_push_notification(self.request)
            post.assert_called_once()
        self.assertEqual(self.saved()["status"], "UNKNOWN")

    def test_malformed_ticket_response_is_unknown(self):
        with self.assertRaises(TypeError):
            self.send({"data": "invalid"})
        self.assertEqual(self.saved()["status"], "UNKNOWN")

    def test_accepted_ticket_and_successful_receipt_are_distinct(self):
        self.send({"data": [{"status": "ok", "id": "receipt-1"}]})
        self.assertEqual(self.saved()["status"], "ACCEPTED")
        request = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        with patch.object(
            self.notifications,
            "_post_json",
            return_value={"data": {"receipt-1": {"status": "ok"}}},
        ):
            self.notifications._check_push_receipts(request)
        self.assertEqual(self.saved()["receiptStatus"], "PROVIDER_ACCEPTED")
        self.assertEqual(self.saved()["status"], "ACCEPTED")

    def test_receipt_failure_is_persisted_and_replays_do_not_replace_it(self):
        self.send({"data": [{"status": "ok", "id": "receipt-1"}]})
        request = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.notifications._record_receipts(
            request, {"receipt-1": {"status": "error"}}, False
        )
        self.assertEqual(self.saved()["receiptStatus"], "FAILED")
        self.notifications._record_receipts(
            request, {"receipt-1": {"status": "ok"}}, False
        )
        self.assertEqual(self.saved()["receiptStatus"], "FAILED")

    def test_queue_failure_recovers_without_resending_push(self):
        self.sqs.send_message.side_effect = [RuntimeError("queue unavailable"), {}]
        with patch.object(
            self.notifications,
            "_post_json",
            return_value={"data": [{"status": "ok", "id": "receipt-1"}]},
        ) as post:
            with self.assertRaises(RuntimeError):
                self.notifications._send_push_notification(self.request)
            self.notifications._send_push_notification(self.request)
            post.assert_called_once()
        self.assertTrue(self.saved()["receiptCheckQueued"])
        self.sqs.send_message.side_effect = None

    def test_exhausted_receipt_is_unknown_and_keeps_identity_on_retry(self):
        self.send({"data": [{"status": "ok", "id": "receipt-1"}]})
        request = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        with patch.object(self.notifications, "_post_json", return_value={"data": {}}):
            self.notifications._check_push_receipts(request)
            retried = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
            self.assertEqual(retried["deliveryKey"], self.key)
            self.notifications._check_push_receipts({**retried, "attempt": 3})
        self.assertEqual(self.saved()["receiptStatus"], "UNKNOWN")
        self.assertEqual(
            self.saved()["receiptStates"][receipt_key("receipt-1")]["status"], "UNKNOWN"
        )

    def test_receipt_cannot_update_another_users_record(self):
        self.send({"data": [{"status": "ok", "id": "receipt-1"}]})
        request = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.notifications._record_receipts(
            {**request, "userId": "different"}, {"receipt-1": {"status": "ok"}}, True
        )
        self.assertEqual(self.saved()["receiptStatus"], "PENDING_RECEIPTS")
