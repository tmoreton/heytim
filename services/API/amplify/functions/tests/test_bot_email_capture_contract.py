"""The store-only receiver switch must never process mail or freeze its spool."""

from pathlib import Path
from unittest import TestCase


class BotEmailCaptureContractTests(TestCase):
    def test_store_only_mode_uses_separate_retained_s3_bucket(self) -> None:
        infrastructure = Path(__file__).parents[2] / "infrastructure"
        receiving = (infrastructure / "bot-email.ts").read_text()
        quarantine = (infrastructure / "bot-email-quarantine.ts").read_text()
        self.assertIn("new Bucket(stack, 'BotEmailQuarantine'", quarantine)
        self.assertIn("addBotEmailQuarantine(stack)", receiving)
        self.assertIn("const receiptBucket = captureOnly ? quarantine : bucket", receiving)
        self.assertIn("bucketName: receiptBucket.bucketName", receiving)
        self.assertIn("receiptBucket.grantPut(receiveRole, 'received/*')", receiving)
        self.assertIn("Bot email cannot process mail while store-only capture", receiving)
        self.assertIn("if (!captureOnly) {\n    topic.addSubscription(", receiving)
