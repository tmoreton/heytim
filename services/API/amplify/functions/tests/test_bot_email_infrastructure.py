from __future__ import annotations

import unittest
from pathlib import Path


class BotEmailInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        amplify = Path(__file__).parents[2]
        cls.infrastructure = (amplify / "infrastructure" / "bot-email.ts").read_text(
            encoding="utf-8"
        )
        cls.backend = (amplify / "backend.ts").read_text(encoding="utf-8")

    def test_outbound_mail_is_queued_with_partial_batch_failures(self) -> None:
        self.assertIn("new Queue(stack, 'BotEmailOutbox'", self.infrastructure)
        self.assertIn("new Queue(stack, 'BotEmailOutboxFailures'", self.infrastructure)
        self.assertIn("reportBatchItemFailures: true", self.infrastructure)
        self.assertIn("handler: 'email_send.handler.handler'", self.infrastructure)

    def test_sender_permission_is_scoped_to_the_bot_domain_identity(self) -> None:
        self.assertIn("actions: ['ses:SendEmail']", self.infrastructure)
        self.assertIn("resource: 'identity', resourceName: domain", self.infrastructure)
        self.assertNotIn("actions: ['ses:*']", self.infrastructure)

    def test_receiver_and_worker_have_only_the_queue_paths_they_need(self) -> None:
        self.assertIn("jobs.grantSendMessages(receiver)", self.infrastructure)
        self.assertIn("EMAIL_QUEUE_URL: botEmail?.outboundQueue.queueUrl", self.backend)
        self.assertIn(
            "botEmail?.outboundQueue.grantSendMessages(workerFunction)", self.backend
        )
