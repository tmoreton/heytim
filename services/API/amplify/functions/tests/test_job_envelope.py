from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from shared.job_envelope import decode_job, envelope_job, send_job


class JobEnvelopeTests(unittest.TestCase):
    def test_envelope_is_versioned_and_deterministically_idempotent(self) -> None:
        first = envelope_job({"type": "PLAID_SYNC", "userId": "user-1"})
        second = envelope_job(
            {
                "type": "PLAID_SYNC",
                "userId": "user-1",
                "correlationId": first["correlationId"],
            }
        )

        self.assertEqual(first["schemaVersion"], 1)
        self.assertEqual(first["idempotencyKey"], second["idempotencyKey"])
        self.assertEqual(first["correlationId"], second["correlationId"])
        self.assertTrue(first["occurredAt"].endswith("Z"))

    def test_decoder_accepts_messages_already_in_flight(self) -> None:
        self.assertEqual(decode_job('{"userId":"user-1"}')["type"], "AGENT_REPLY")

    def test_decoder_rejects_unknown_versions_and_types(self) -> None:
        with self.assertRaisesRegex(ValueError, "schema version"):
            decode_job({"schemaVersion": 2})
        with self.assertRaisesRegex(ValueError, "Unknown job type"):
            envelope_job({"type": "DO_ANYTHING"})

    def test_sender_serializes_the_envelope_and_delay(self) -> None:
        client = Mock()
        client.send_message.return_value = {"MessageId": "message-1"}

        response = send_job(
            client,
            "https://queue.example",
            {"type": "APPROVAL_EXPIRY", "proposalId": "proposal-1"},
            delay_seconds=10,
        )

        self.assertEqual(response, {"MessageId": "message-1"})
        request = client.send_message.call_args.kwargs
        self.assertEqual(request["QueueUrl"], "https://queue.example")
        self.assertEqual(request["DelaySeconds"], 10)
        self.assertEqual(json.loads(request["MessageBody"])["schemaVersion"], 1)


if __name__ == "__main__":
    unittest.main()
