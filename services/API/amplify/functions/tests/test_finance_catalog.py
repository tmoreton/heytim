from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch

import shared.catalog_sync as sync_module
import shared.connection_revocation as revocation_module
import shared.connections as connections_module
from catalog_test_fakes import FakeSecrets, FakeTable
from shared.catalog import CatalogService


class FinanceCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        sync_module._last_sync_at = time.monotonic()
        sync_module._local_sync_delay = sync_module.SYNC_SECONDS
        self.table = FakeTable()
        self.secrets = FakeSecrets()
        self.catalog = CatalogService(self.table, self.secrets)

    @staticmethod
    def _platform_arn(provider: str) -> str:
        return (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            f"heytim/oauth/{provider}-production-ABC123"
        )

    def test_quickbooks_connection_keeps_tokens_private_and_revokes_on_delete(
        self,
    ) -> None:
        app_arn = self._platform_arn("quickbooks")
        self.secrets.values[app_arn] = json.dumps(
            {"clientId": "quickbooks-client", "clientSecret": "app-secret"}
        )
        saved = self.catalog.save_quickbooks_connection(
            "owner",
            "Acme Books",
            "12345",
            {
                "accessToken": "access-token",
                "refreshToken": "refresh-token",
                "expiresAt": 2_000_000_000,
            },
            app_arn,
            "production",
        )
        item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]
        credential_arn = item["secretArn"]

        self.assertNotIn("accessToken", saved)
        self.assertEqual(item["runtime"]["realmId"], "12345")
        self.assertEqual(
            json.loads(self.secrets.values[credential_arn])["refreshToken"],
            "refresh-token",
        )

        with patch.object(connections_module.urllib.request, "urlopen") as urlopen:
            self.catalog.delete_connection("owner", saved["id"])

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url, revocation_module.QUICKBOOKS_TOKEN_REVOKE_URL
        )
        self.assertEqual(json.loads(request.data), {"token": "refresh-token"})
        self.assertIn(credential_arn, self.secrets.deleted)
        self.assertIn(app_arn, self.secrets.values)

    def test_plaid_connection_keeps_access_private_and_removes_item_on_delete(
        self,
    ) -> None:
        app_arn = self._platform_arn("plaid")
        self.secrets.values[app_arn] = json.dumps(
            {"clientId": "plaid-client", "secret": "plaid-secret"}
        )
        saved = self.catalog.save_plaid_connection(
            "owner",
            "Plaid Bank",
            "item_12345678",
            "access-token",
            app_arn,
            "sandbox",
        )
        item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]
        credential_arn = item["secretArn"]

        self.assertNotIn("accessToken", saved)
        self.assertEqual(item["runtime"]["environment"], "sandbox")

        with patch.object(connections_module.urllib.request, "urlopen") as urlopen:
            self.catalog.delete_connection("owner", saved["id"])

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://sandbox.plaid.com/item/remove")
        self.assertEqual(
            json.loads(request.data),
            {
                "client_id": "plaid-client",
                "secret": "plaid-secret",
                "access_token": "access-token",
            },
        )
        self.assertIn(credential_arn, self.secrets.deleted)
        self.assertIn(app_arn, self.secrets.values)


if __name__ == "__main__":
    unittest.main()
