from __future__ import annotations

import json
import time
import unittest

import shared.catalog_sync as sync_module
import test_catalog


class GmailConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        sync_module._last_sync_at = time.monotonic()
        sync_module._local_sync_delay = sync_module.SYNC_SECONDS
        self.table = test_catalog.FakeTable()
        self.secrets = test_catalog.FakeSecrets()
        self.catalog = test_catalog.CatalogService(self.table, self.secrets)
        self.catalog._store_official(
            test_catalog.TEST_TOOLS,
            test_catalog.TEST_SKILLS,
            [],
        )

    def test_oauth_connection_is_private_and_tool_filtered(self) -> None:
        client_secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "frogbot/oauth/google-ABC123"
        )
        saved = self.catalog.save_gmail_connection(
            "owner",
            "owner@example.com",
            "refresh-token",
            client_secret_arn,
        )

        self.assertEqual(saved["provider"], "gmail")
        self.assertEqual(saved["connectedAccount"], "owner@example.com")
        self.assertNotIn("secretArn", saved)
        item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]
        self.assertEqual(
            json.loads(self.secrets.values[item["secretArn"]]),
            {"refreshToken": "refresh-token"},
        )
        runtime = self.catalog.resolve_tools_for_runtime("owner", [saved["id"]])[0][
            "runtime"
        ]
        self.assertEqual(runtime["authType"], "oauth")
        self.assertIn("create_draft", runtime["allowedTools"])
        self.assertNotIn("trash_thread", runtime["allowedTools"])


if __name__ == "__main__":
    unittest.main()
