from __future__ import annotations

import json
import time
import unittest
import urllib.error
from unittest.mock import patch

import shared.account_state as account_state_module
import shared.catalog_sync as sync_module
import shared.connection_revocation as revocation_module
import shared.connections as connections_module
import test_catalog
from botocore.exceptions import ClientError, EndpointConnectionError


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

    def _save_gmail(self, refresh_token: str = "refresh-token") -> tuple[dict, str]:
        saved = self.catalog.save_gmail_connection(
            "owner",
            "owner@example.com",
            refresh_token,
            (
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                "heytim/oauth/google-ABC123"
            ),
        )
        item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]
        return saved, item["secretArn"]

    def test_oauth_connection_is_private_and_tool_filtered(self) -> None:
        client_secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/google-ABC123"
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

    def test_deleting_gmail_revokes_refresh_token_and_removes_local_access(
        self,
    ) -> None:
        saved, secret_arn = self._save_gmail("refresh token/+value")

        with patch.object(connections_module.urllib.request, "urlopen") as urlopen:
            result = self.catalog.delete_connection("owner", saved["id"])

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, revocation_module.GOOGLE_TOKEN_REVOKE_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.get_header("Content-type"), "application/x-www-form-urlencoded"
        )
        self.assertEqual(
            request.data,
            b"token=refresh+token%2F%2Bvalue",
        )
        self.assertEqual(
            urlopen.call_args.kwargs["timeout"],
            revocation_module.PROVIDER_REVOKE_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            result,
            {"deleted": True, "credentialDeletionWindowDays": 7},
        )
        self.assertIn(secret_arn, self.secrets.deleted)
        self.assertNotIn(("USER#owner", f"CONNECTION#{saved['id']}"), self.table.items)

    def test_invalid_google_token_does_not_block_local_removal(self) -> None:
        saved, secret_arn = self._save_gmail()
        invalid_token = urllib.error.HTTPError(
            revocation_module.GOOGLE_TOKEN_REVOKE_URL,
            400,
            "invalid_token",
            None,
            None,
        )

        with patch.object(
            connections_module.urllib.request,
            "urlopen",
            side_effect=invalid_token,
        ):
            result = self.catalog.delete_connection("owner", saved["id"])
        invalid_token.close()

        self.assertTrue(result["deleted"])
        self.assertIn(secret_arn, self.secrets.deleted)
        self.assertNotIn(("USER#owner", f"CONNECTION#{saved['id']}"), self.table.items)

    def test_unavailable_google_revocation_does_not_block_local_removal(self) -> None:
        saved, secret_arn = self._save_gmail()

        with (
            patch.object(
                connections_module.urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError("temporarily unavailable"),
            ),
            self.assertLogs("shared.connections", level="WARNING"),
        ):
            result = self.catalog.delete_connection("owner", saved["id"])

        self.assertTrue(result["deleted"])
        self.assertIn(secret_arn, self.secrets.deleted)
        self.assertNotIn(("USER#owner", f"CONNECTION#{saved['id']}"), self.table.items)

    def test_missing_gmail_credential_does_not_block_local_removal(self) -> None:
        saved, secret_arn = self._save_gmail()
        self.secrets.values.pop(secret_arn)

        with (
            patch.object(connections_module.urllib.request, "urlopen") as urlopen,
            self.assertLogs("shared.connections", level="WARNING"),
        ):
            result = self.catalog.delete_connection("owner", saved["id"])

        self.assertTrue(result["deleted"])
        urlopen.assert_not_called()
        self.assertNotIn(("USER#owner", f"CONNECTION#{saved['id']}"), self.table.items)

    def test_account_cleanup_revokes_gmail_before_deleting_credential(self) -> None:
        saved, secret_arn = self._save_gmail()
        item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]

        with patch.object(connections_module.urllib.request, "urlopen") as urlopen:
            deleted = self.catalog.delete_connection_secrets([item])

        self.assertEqual(deleted, 1)
        urlopen.assert_called_once()
        self.assertIn(secret_arn, self.secrets.deleted)

    def test_account_deletion_wins_oauth_save_race_and_revokes_new_token(
        self,
    ) -> None:
        self.table.put_item(
            Item={"pk": "USER#owner", "sk": "STATE", "entity": "USER_STATE"}
        )
        original_transaction = self.table.transact_write_items

        def begin_deletion_before_transaction(**kwargs) -> None:
            self.table.items[("USER#owner", "STATE")]["accountStatus"] = "DELETING"
            original_transaction(**kwargs)

        with (
            patch.object(
                self.table,
                "transact_write_items",
                side_effect=begin_deletion_before_transaction,
            ),
            patch.object(connections_module.urllib.request, "urlopen") as urlopen,
            self.assertRaisesRegex(
                test_catalog.CatalogError, "while this account is being deleted"
            ),
        ):
            self.catalog.save_gmail_connection(
                "owner",
                "owner@example.com",
                "new-refresh-token",
                (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                    "heytim/oauth/google-ABC123"
                ),
            )

        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.data, b"token=new-refresh-token")
        self.assertFalse(
            any(
                pk == "USER#owner" and sk.startswith("CONNECTION#")
                for pk, sk in self.table.items
            )
        )
        self.assertEqual(self.secrets.values, {})
        self.assertEqual(len(self.secrets.deleted), 1)

    def test_reconnect_race_preserves_old_secret_and_revokes_new_token(self) -> None:
        saved, old_secret_arn = self._save_gmail("old-refresh-token")
        old_credential = self.secrets.values[old_secret_arn]
        self.table.put_item(
            Item={"pk": "USER#owner", "sk": "STATE", "entity": "USER_STATE"}
        )
        original_transaction = self.table.transact_write_items

        def begin_deletion_before_transaction(**kwargs) -> None:
            self.table.items[("USER#owner", "STATE")]["accountStatus"] = "DELETING"
            original_transaction(**kwargs)

        with (
            patch.object(
                self.table,
                "transact_write_items",
                side_effect=begin_deletion_before_transaction,
            ),
            patch.object(connections_module.urllib.request, "urlopen") as urlopen,
            self.assertRaisesRegex(
                test_catalog.CatalogError, "while this account is being deleted"
            ),
        ):
            self.catalog.save_gmail_connection(
                "owner",
                "owner@example.com",
                "new-refresh-token",
                (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                    "heytim/oauth/google-ABC123"
                ),
            )

        urlopen.assert_called_once()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.data, b"token=new-refresh-token")
        connection_item = self.table.items[
            ("USER#owner", f"CONNECTION#{saved['id']}")
        ]
        self.assertEqual(connection_item["secretArn"], old_secret_arn)
        self.assertEqual(self.secrets.values, {old_secret_arn: old_credential})
        self.assertEqual(len(self.secrets.deleted), 1)
        self.assertNotEqual(self.secrets.deleted[0], old_secret_arn)

    def test_concurrent_first_callbacks_converge_on_one_connection(self) -> None:
        first, first_secret_arn = self._save_gmail("first-refresh-token")
        actual_connection_items = self.catalog._connection_items
        reads = 0

        def stale_then_current(user_id: str) -> list[dict]:
            nonlocal reads
            reads += 1
            if reads == 1:
                return []
            return actual_connection_items(user_id)

        with (
            patch.object(
                self.catalog,
                "_connection_items",
                side_effect=stale_then_current,
            ),
            patch.object(connections_module.urllib.request, "urlopen") as urlopen,
        ):
            second = self.catalog.save_gmail_connection(
                "owner",
                "owner@example.com",
                "second-refresh-token",
                (
                    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                    "heytim/oauth/google-ABC123"
                ),
            )

        self.assertEqual(first["id"], second["id"])
        gmail_connections = [
            value
            for value in self.table.items.values()
            if value.get("provider") == "gmail"
        ]
        self.assertEqual(len(gmail_connections), 1)
        current_secret_arn = gmail_connections[0]["secretArn"]
        self.assertNotEqual(current_secret_arn, first_secret_arn)
        self.assertEqual(
            json.loads(self.secrets.values[current_secret_arn]),
            {"refreshToken": "second-refresh-token"},
        )
        self.assertEqual(set(self.secrets.values), {current_secret_arn})
        self.assertIn(first_secret_arn, self.secrets.deleted)
        urlopen.assert_not_called()

    def test_committed_save_survives_a_lost_transaction_response(self) -> None:
        original_transaction = self.table.transact_write_items
        transaction_tokens = []

        def commit_then_disconnect(**kwargs) -> None:
            transaction_tokens.append(kwargs["ClientRequestToken"])
            original_transaction(**kwargs)
            raise EndpointConnectionError(endpoint_url="https://dynamodb.test")

        with (
            patch.object(
                self.table,
                "transact_write_items",
                side_effect=commit_then_disconnect,
            ),
            patch.object(connections_module.urllib.request, "urlopen") as urlopen,
        ):
            saved, secret_arn = self._save_gmail("committed-refresh-token")

        item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]
        self.assertEqual(item["secretArn"], secret_arn)
        self.assertIn(secret_arn, self.secrets.values)
        self.assertEqual(self.secrets.deleted, [])
        self.assertEqual(len(transaction_tokens), 1)
        urlopen.assert_not_called()

    def test_transaction_in_progress_retries_same_request_until_commit(self) -> None:
        original_transaction = self.table.transact_write_items
        transaction_tokens = []
        sleeps = []

        def in_progress_then_commit(**kwargs) -> None:
            transaction_tokens.append(kwargs["ClientRequestToken"])
            if len(transaction_tokens) == 1:
                raise ClientError(
                    {
                        "Error": {
                            "Code": "TransactionInProgressException",
                            "Message": "transaction is still settling",
                        }
                    },
                    "TransactWriteItems",
                )
            original_transaction(**kwargs)

        with (
            patch.object(
                self.table,
                "transact_write_items",
                side_effect=in_progress_then_commit,
            ),
            patch.object(
                account_state_module.time,
                "sleep",
                side_effect=sleeps.append,
            ),
            patch.object(connections_module.urllib.request, "urlopen") as urlopen,
        ):
            saved, secret_arn = self._save_gmail("settled-refresh-token")

        item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]
        self.assertEqual(item["secretArn"], secret_arn)
        self.assertIn(secret_arn, self.secrets.values)
        self.assertEqual(transaction_tokens[0], transaction_tokens[1])
        self.assertEqual(sleeps, [0.5])
        urlopen.assert_not_called()

if __name__ == "__main__":
    unittest.main()
