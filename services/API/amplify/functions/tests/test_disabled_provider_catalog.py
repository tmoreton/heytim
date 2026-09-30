from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import shared.catalog_sync as sync_module
from catalog_test_fakes import FakeSecrets, FakeTable
from shared.catalog import CatalogError, CatalogService
from shared.connection_providers import connection_specs
from test_catalog import TEST_SKILLS, TEST_TOOLS


class DisabledProviderCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        sync_module._last_sync_at = time.monotonic()
        sync_module._local_sync_delay = sync_module.SYNC_SECONDS
        self.catalog = CatalogService(FakeTable(), FakeSecrets())
        self.catalog._store_official(TEST_TOOLS, TEST_SKILLS, [])

    def test_google_connection_tools_disappear_from_selection_and_execution(self) -> None:
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/google-ABC123"
        )
        specs = connection_specs()
        gmail = self.catalog.save_gmail_connection(
            "owner", "owner@example.com", "refresh-gmail", secret_arn
        )
        youtube = self.catalog.save_oauth_api_connection(
            "owner", "youtube", "owner@example.com", "channel-1",
            "refresh-youtube", secret_arn, list(specs["youtube"]["scopes"]),
        )
        workspace = self.catalog.save_google_workspace_connection(
            "owner", "owner@example.com", "permission-1",
            "refresh-workspace", secret_arn,
            list(specs["google_workspace"]["scopes"]),
        )
        google_ids = {gmail["id"], youtube["id"], workspace["id"]}

        self.assertTrue(google_ids <= {tool["id"] for tool in self.catalog.list_tools("owner")})
        with patch.dict(
            "os.environ",
            {"DISABLED_CONNECTION_PROVIDER_IDS": "gmail,youtube,google_workspace"},
        ):
            visible = {tool["id"] for tool in self.catalog.list_tools("owner")}
            with patch.object(
                self.catalog, "_google_connection_health",
                side_effect=AssertionError("disabled Google grant was checked"),
            ):
                visible_connections = {
                    item["id"] for item in self.catalog.list_connections("owner")
                }
            available = self.catalog.available_tool_ids("owner", list(google_ids))
            resolved = self.catalog.resolve_tools_for_runtime("owner", list(google_ids))
            with self.assertRaisesRegex(CatalogError, "Unknown tools"):
                self.catalog.validate_tools("owner", list(google_ids))

        self.assertTrue(google_ids.isdisjoint(visible))
        self.assertTrue(google_ids.isdisjoint(visible_connections))
        self.assertEqual(available, [])
        self.assertEqual(resolved, [])
        self.assertIn("web_search", visible)


if __name__ == "__main__":
    unittest.main()
