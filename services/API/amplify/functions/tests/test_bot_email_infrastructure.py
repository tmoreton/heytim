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
        self.assertIn(
            "actions: ['ses:SendEmail', 'ses:SendRawEmail']", self.infrastructure
        )
        self.assertIn("resource: 'identity', resourceName: domain", self.infrastructure)
        self.assertNotIn("actions: ['ses:*']", self.infrastructure)

    def test_receiver_and_worker_have_only_the_queue_paths_they_need(self) -> None:
        self.assertIn("jobs.grantSendMessages(receiver)", self.infrastructure)
        self.assertIn("EMAIL_QUEUE_URL: botEmail?.outboundQueue.queueUrl", self.backend)
        self.assertIn(
            "botEmail?.outboundQueue.grantSendMessages(workerFunction)", self.backend
        )

    def test_bot_subdomain_has_an_isolated_managed_dns_zone(self) -> None:
        self.assertIn("new CfnHostedZone(stack, 'BotEmailDnsZone'", self.infrastructure)
        self.assertIn("new CfnRecordSet(stack, 'BotEmailMxRecord'", self.infrastructure)
        self.assertIn(
            "resourceRecords: [`10 inbound-smtp.${stack.region}.amazonaws.com`]",
            self.infrastructure,
        )
        self.assertIn("`BotEmailDkimRecord${index}`", self.infrastructure)
        self.assertIn("value: Fn.join(',', dnsZone.attrNameServers)", self.infrastructure)

    def test_outbound_mail_has_aligned_spf_dmarc_and_a_custom_return_path(self) -> None:
        self.assertIn("const mailFromDomain = `mail.${domain}`", self.infrastructure)
        self.assertIn("mailFromDomain,", self.infrastructure)
        self.assertIn("behaviorOnMxFailure: 'USE_DEFAULT_VALUE'", self.infrastructure)
        self.assertIn("new CfnRecordSet(stack, 'BotEmailMailFromMxRecord'", self.infrastructure)
        self.assertIn(
            "resourceRecords: [`10 feedback-smtp.${stack.region}.amazonses.com`]",
            self.infrastructure,
        )
        self.assertIn('"v=spf1 include:amazonses.com ~all"', self.infrastructure)
        self.assertIn('"v=DMARC1; p=none; adkim=s; aspf=r; pct=100"', self.infrastructure)
