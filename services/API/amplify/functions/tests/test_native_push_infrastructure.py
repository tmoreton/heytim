from __future__ import annotations

import unittest
from pathlib import Path


class NativePushInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            Path(__file__).parents[2] / "infrastructure" / "native-push.ts"
        ).read_text(encoding="utf-8")

    def test_endpoint_management_uses_aws_required_unscoped_resource(self) -> None:
        endpoint_policy = self.source.split(
            "apiFunction.addToRolePolicy", 1
        )[1].split("workerFunction.addToRolePolicy", 1)[0]
        for action in (
            "sns:CreatePlatformEndpoint",
            "sns:DeleteEndpoint",
            "sns:SetEndpointAttributes",
        ):
            self.assertIn(action, endpoint_policy)
        self.assertIn("resources: ['*']", endpoint_policy)

    def test_publish_uses_aws_required_unscoped_resource(self) -> None:
        publish_policy = self.source.split("actions: ['sns:Publish']", 1)[1]
        self.assertIn("resources: ['*']", publish_policy)
        self.assertNotIn("resources: endpoints", publish_policy)

    def test_delivery_feedback_role_is_source_scoped(self) -> None:
        feedback = self.source.split("export function addNativePushFeedbackRole", 1)[1]
        self.assertIn("'aws:SourceAccount': stack.account", feedback)
        self.assertIn("'aws:SourceArn': applications", feedback)
        self.assertIn("logs:PutLogEvents", feedback)
        self.assertIn("encryptionKey: logsKey", feedback)
        self.assertIn("retention: RetentionDays.ONE_MONTH", feedback)


if __name__ == "__main__":
    unittest.main()
