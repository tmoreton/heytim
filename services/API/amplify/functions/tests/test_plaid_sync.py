from __future__ import annotations

import gzip
import io
import json
import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

import test_api_safety


class PlaidSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = test_api_safety.ApiSafetyTests
        if not hasattr(base, "support"):
            base.setUpClass()
        from shared.plaid_ledger import merge_transactions, public_sync_status
        support = ModuleType("worker.support")
        support.FILES_BUCKET_NAME = "test-files"
        support.catalog = MagicMock()
        support.s3 = MagicMock()
        support.table = MagicMock()
        with patch.dict(sys.modules, {"worker.support": support}):
            from worker import plaid_sync
        from shared.plaid_ledger import ledger_prefix
        cls.ledger_prefix = staticmethod(ledger_prefix)
        cls.merge_transactions = staticmethod(merge_transactions)
        cls.public_sync_status = staticmethod(public_sync_status)
        cls.sync = plaid_sync
        cls.connections = base.handler.authenticated_routes

    def test_manual_refresh_requires_an_owned_plaid_connection(self) -> None:
        catalog = self.connections._request_plaid_sync.__globals__["catalog"]
        with (
            patch.object(catalog, "_get_connection", return_value=None),
            self.assertRaises(
                test_api_safety.ApiSafetyTests.support.ApiError
            ) as error,
        ):
            self.connections._request_plaid_sync(
                "user-1", "connection_1234567890abcdef1234"
            )
        self.assertEqual(error.exception.status_code, 404)

    def test_manual_refresh_queues_one_owned_connection(self) -> None:
        connection_id = "connection_1234567890abcdef1234"
        database = MagicMock()
        database.get_item.return_value = {"Item": {
            "revision": 2, "cursor": "saved", "status": "ready",
        }}
        queue = MagicMock()
        globals = self.connections._request_plaid_sync.__globals__
        catalog = globals["catalog"]
        with (
            patch.dict(globals, {"table": database, "sqs": queue}),
            patch.object(catalog, "_get_connection", return_value={
                "provider": "plaid", "providerAccountId": "item_12345678",
                "runtime": {"environment": "sandbox"},
            }),
        ):
            status = self.connections._request_plaid_sync("user-1", connection_id)
        self.assertEqual(status["status"], "queued")
        message = json.loads(queue.send_message.call_args.kwargs["MessageBody"])
        expected = {
            "type": "PLAID_SYNC", "userId": "user-1", "connectionId": connection_id,
        }
        self.assertEqual({key: message[key] for key in expected}, expected)
        self.assertEqual(message["schemaVersion"], 1)

    def test_merge_add_modify_remove_is_idempotent(self) -> None:
        original = [
            {"transaction_id": "tx_old", "account_id": "account_12345678", "amount": 9},
            {"transaction_id": "tx_keep", "account_id": "account_12345678", "amount": 1},
        ]
        added = [{"transaction_id": "tx_new", "account_id": "account_12345678", "amount": 2}]
        modified = [{"transaction_id": "tx_keep", "account_id": "account_12345678", "amount": 3}]
        removed = [{"transaction_id": "tx_old"}]
        merged = self.merge_transactions(original, added, modified, removed)
        self.assertEqual({item["transaction_id"] for item in merged}, {"tx_keep", "tx_new"})
        self.assertEqual(next(item for item in merged if item["transaction_id"] == "tx_keep")["amount"], 3)
        self.assertEqual(self.merge_transactions(merged, added, modified, removed), merged)

    def test_public_status_never_exposes_cursor_or_storage_key(self) -> None:
        status = self.public_sync_status({
            "status": "ready", "cursor": "private-cursor",
            "objectKey": "private-key", "secretArn": "private-secret",
            "transactionCount": 7,
        })
        self.assertEqual(status, {"status": "ready", "transactionCount": 7})

    def test_pagination_mutation_restarts_from_original_cursor(self) -> None:
        pages = [
            {"added": [{"transaction_id": "discard"}], "modified": [], "removed": [],
             "next_cursor": "partial", "has_more": True},
            self.sync.PlaidSyncError("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"),
            {"added": [{"transaction_id": "keep"}], "modified": [], "removed": [],
             "next_cursor": "final", "has_more": False},
        ]
        with patch.object(self.sync, "_plaid_request", side_effect=pages) as request:
            added, _, _, cursor = self.sync._window({"environment": "sandbox"}, "token", "original")
        self.assertEqual(added, [{"transaction_id": "keep"}])
        self.assertEqual(cursor, "final")
        self.assertEqual([call.args[3]["cursor"] for call in request.call_args_list],
                         ["original", "partial", "original"])

    def test_cursor_is_checkpointed_only_after_snapshot_write(self) -> None:
        connection_id = "connection_1234567890abcdef1234"
        connection = {"provider": "plaid", "runtime": {"environment": "sandbox"}}
        state = {"pk": "USER#user-1", "sk": f"PLAID_SYNC#{connection_id}",
                 "cursor": "prior", "revision": 2,
                 "objectKey": self.ledger_prefix("user-1", connection_id)
                 + "snapshots/" + "b" * 32 + ".json.gz",
                 "transactionCount": 1}
        prior = [{"transaction_id": "old", "account_id": "account_12345678"}]
        storage = MagicMock()
        storage.get_object.return_value = {"Body": io.BytesIO(gzip.compress(json.dumps(prior).encode()))}
        database = MagicMock()
        database.get_item.return_value = {"Item": state}
        catalog = MagicMock()
        catalog._get_connection.return_value = connection
        with (
            patch.object(self.sync, "table", database),
            patch.object(self.sync, "s3", storage),
            patch.object(self.sync, "catalog", catalog),
            patch.object(self.sync, "_credential", return_value=({"environment": "sandbox"}, "token")),
            patch.object(self.sync, "_window", return_value=(
                [{"transaction_id": "new", "account_id": "account_12345678"}],
                [], [{"transaction_id": "old"}], "next",
            )),
        ):
            self.sync.process_plaid_sync({"userId": "user-1", "connectionId": connection_id})
        self.assertTrue(storage.put_object.called)
        self.assertTrue(database.put_item.called)
        self.assertEqual(database.put_item.call_args.kwargs["Item"]["cursor"], "next")
        saved = json.loads(gzip.decompress(storage.put_object.call_args.kwargs["Body"]))
        self.assertEqual([item["transaction_id"] for item in saved], ["new"])

    def test_no_change_refresh_reuses_the_existing_snapshot(self) -> None:
        connection_id = "connection_1234567890abcdef1234"
        object_key = self.ledger_prefix("user-1", connection_id) \
            + "snapshots/" + "a" * 32 + ".json.gz"
        database = MagicMock()
        database.get_item.return_value = {"Item": {
            "revision": 3, "cursor": "prior", "objectKey": object_key,
            "status": "ready", "transactionCount": 2,
            "webhookConfigured": True,
        }}
        storage = MagicMock()
        catalog = MagicMock()
        catalog._get_connection.return_value = {"provider": "plaid"}
        with (
            patch.object(self.sync, "table", database),
            patch.object(self.sync, "s3", storage),
            patch.object(self.sync, "catalog", catalog),
            patch.object(self.sync, "_credential", return_value=({"environment": "sandbox"}, "token")),
            patch.object(self.sync, "_window", return_value=([], [], [], "next")),
        ):
            self.sync.process_plaid_sync({"userId": "user-1", "connectionId": connection_id})
        storage.put_object.assert_not_called()
        storage.get_paginator.assert_not_called()
        checkpoint = database.put_item.call_args.kwargs["Item"]
        self.assertEqual(checkpoint["objectKey"], object_key)
        self.assertEqual(checkpoint["cursor"], "next")

    def test_disconnect_cleanup_only_deletes_unlinked_ledger(self) -> None:
        connection_id = "connection_1234567890abcdef1234"
        request = {"userId": "user-1", "connectionId": connection_id}
        catalog = MagicMock()
        storage = MagicMock()
        with (
            patch.object(self.sync, "catalog", catalog),
            patch.object(self.sync, "s3", storage),
            patch.object(self.sync, "delete_object_versions") as delete,
        ):
            catalog._get_connection.return_value = {"provider": "plaid"}
            self.sync.delete_plaid_ledger(request)
            delete.assert_not_called()
            catalog._get_connection.return_value = None
            self.sync.delete_plaid_ledger(request)
            delete.assert_called_once()
        self.assertEqual(delete.call_args.args[2], self.ledger_prefix("user-1", connection_id))
