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
        self.assertIn(
            "actions: ['sns:DeleteEndpoint', 'sns:SetEndpointAttributes']",
            self.source,
        )
        endpoint_policy = self.source.split(
            "actions: ['sns:DeleteEndpoint', 'sns:SetEndpointAttributes']", 1
        )[1].split("}));", 1)[0]
        self.assertIn("resources: ['*']", endpoint_policy)

    def test_publish_remains_limited_to_device_endpoints(self) -> None:
        publish_policy = self.source.split("actions: ['sns:Publish']", 1)[1]
        self.assertIn("resources: endpoints", publish_policy)
        self.assertNotIn("resources: endpointManagementResources", publish_policy)


if __name__ == "__main__":
    unittest.main()
