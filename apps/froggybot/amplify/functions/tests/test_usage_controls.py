from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import boto3
from worker_test_case import BotoCoreError, WorkerTestCase


class UsageControlTests(WorkerTestCase):
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

    def _limits(
        self,
        *,
        monthly: int = 100,
        user_window: int = 100,
        global_window: int = 100,
    ):
        return self.usage_controls.UsageLimits(
            monthly_run_units=monthly,
            user_window_run_units=user_window,
            global_window_run_units=global_window,
            window_seconds=60,
        )

    def test_admission_is_idempotent_and_only_increments_once(self) -> None:
        limits = self._limits()

        first = self.usage_controls.admit_run(
            "user-1", "direct:turn-1", now=self.now, limits=limits
        )
        retry = self.usage_controls.admit_run(
            "user-1", "direct:turn-1", now=self.now, limits=limits
        )

        self.assertTrue(first.allowed)
        self.assertFalse(first.duplicate)
        self.assertTrue(retry.allowed)
        self.assertTrue(retry.duplicate)
        self.assertEqual(len(self.table.client.transactions), 1)
        transaction = self.table.client.transactions[0]["TransactItems"]
        self.assertEqual(
            transaction[0]["ConditionCheck"]["Key"]["pk"],
            "USER#user-1",
        )
        self.assertEqual(
            transaction[2]["Put"]["Item"]["runUnits"], 1
        )
        month = self.table.items[("USER#user-1", "USAGE_LIMIT#MONTH#2026-09")]
        self.assertEqual(month["runUnits"], 1)

    def test_youtube_capacity_reservation_is_global_and_idempotent(self) -> None:
        first = self.youtube_quota.reserve_youtube_search_calls(
            "user-1", "runtime:session-1", now=self.now, daily_limit=6
        )
        retry = self.youtube_quota.reserve_youtube_search_calls(
            "user-1", "runtime:session-1", now=self.now, daily_limit=6
        )

        self.assertTrue(first.allowed)
        self.assertEqual(first.quota_day, "2026-09-11")
        self.assertTrue(retry.allowed)
        self.assertTrue(retry.duplicate)
        counter = self.table.items[
            (
                "SYSTEM#USAGE_CONTROL",
                "USAGE_LIMIT#PROVIDER#YOUTUBE_SEARCH#DAY#2026-09-11",
            )
        ]
        self.assertEqual(counter["runUnits"], 3)

    def test_youtube_capacity_stops_before_shared_daily_limit(self) -> None:
        for user_id, session_id in (
            ("user-1", "runtime:session-1"),
            ("user-2", "runtime:session-2"),
        ):
            self.assertTrue(
                self.youtube_quota.reserve_youtube_search_calls(
                    user_id,
                    session_id,
                    now=self.now,
                    daily_limit=6,
                ).allowed
            )

        denied = self.youtube_quota.reserve_youtube_search_calls(
            "user-3", "runtime:session-3", now=self.now, daily_limit=6
        )

        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "provider_daily_limit")
        self.assertIn("shared daily capacity", denied.user_message)

    def test_youtube_daily_limit_must_cover_one_fixed_lease(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 3 and 1000000"):
            self.youtube_quota.reserve_youtube_search_calls(
                "user-1", "runtime:session-1", now=self.now, daily_limit=2
            )

        self.assertEqual(self.table.client.transactions, [])

    def test_youtube_retry_after_pacific_rollover_gets_a_new_lease(self) -> None:
        before = datetime(2026, 1, 2, 7, 59, tzinfo=UTC)
        after = datetime(2026, 1, 2, 8, 0, tzinfo=UTC)

        first = self.youtube_quota.reserve_youtube_search_calls(
            "user-1", "runtime:session-1", now=before, daily_limit=3
        )
        renewed = self.youtube_quota.reserve_youtube_search_calls(
            "user-1", "runtime:session-1", now=after, daily_limit=3
        )

        self.assertTrue(first.allowed)
        self.assertFalse(first.duplicate)
        self.assertEqual(first.quota_day, "2026-01-01")
        self.assertTrue(renewed.allowed)
        self.assertFalse(renewed.duplicate)
        self.assertEqual(renewed.quota_day, "2026-01-02")
        for quota_day in ("2026-01-01", "2026-01-02"):
            counter = self.table.items[
                (
                    "SYSTEM#USAGE_CONTROL",
                    f"USAGE_LIMIT#PROVIDER#YOUTUBE_SEARCH#DAY#{quota_day}",
                )
            ]
            self.assertEqual(counter["runUnits"], 3)

    def test_youtube_quota_day_resets_at_midnight_pacific(self) -> None:
        before = datetime(2026, 1, 2, 7, 59, tzinfo=UTC)
        after = datetime(2026, 1, 2, 8, 0, tzinfo=UTC)

        self.assertEqual(
            self.youtube_quota.youtube_quota_day(before), "2026-01-01"
        )
        self.assertEqual(
            self.youtube_quota.youtube_quota_day(after), "2026-01-02"
        )

    def test_table_resource_serializes_native_transaction_values_once(self) -> None:
        class RequestCaptured(Exception):
            pass

        resource = boto3.resource(
            "dynamodb",
            region_name="us-east-1",
            endpoint_url="http://127.0.0.1:9",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        table = resource.Table("data")
        captured: dict = {}

        def capture_wire_request(*, params: dict, **_kwargs) -> None:
            captured.update(json.loads(params["body"]))
            raise RequestCaptured

        table.meta.client.meta.events.register(
            "before-call.dynamodb.TransactWriteItems",
            capture_wire_request,
        )
        with self.assertRaises(RequestCaptured):
            table.meta.client.transact_write_items(
                TransactItems=[
                    {
                        "ConditionCheck": {
                            "TableName": table.name,
                            "Key": {"pk": "USER#user-1", "sk": "STATE"},
                            "ConditionExpression": "attribute_not_exists(#status)",
                            "ExpressionAttributeNames": {"#status": "accountStatus"},
                        }
                    }
                ]
            )

        key = captured["TransactItems"][0]["ConditionCheck"]["Key"]
        self.assertEqual(key["pk"], {"S": "USER#user-1"})
        self.assertEqual(key["sk"], {"S": "STATE"})

    def test_settlement_retry_keeps_resource_transaction_native(self) -> None:
        class RequestCaptured(Exception):
            pass

        resource = boto3.resource(
            "dynamodb",
            region_name="us-east-1",
            endpoint_url="http://127.0.0.1:9",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        table = resource.Table("data")
        captured: list[dict] = []
        transaction = [
            {
                "ConditionCheck": {
                    "TableName": table.name,
                    "Key": {"pk": "USER#user-1", "sk": "STATE"},
                    "ConditionExpression": "attribute_not_exists(#status)",
                    "ExpressionAttributeNames": {"#status": "accountStatus"},
                }
            }
        ]

        def capture_wire_request(*, params: dict, **_kwargs) -> None:
            captured.append(json.loads(params["body"]))
            if len(captured) == 1:
                raise BotoCoreError("response lost")
            raise RequestCaptured

        table.meta.client.meta.events.register(
            "before-call.dynamodb.TransactWriteItems",
            capture_wire_request,
        )
        with (
            patch.object(self.usage_controls.time, "sleep"),
            self.assertRaises(RequestCaptured),
        ):
            self.usage_controls._transact_write_with_settlement(
                table.meta.client,
                transaction,
                "stable-client-token",
            )

        self.assertEqual(captured[0], captured[1])
        self.assertEqual(
            transaction[0]["ConditionCheck"]["Key"],
            {"pk": "USER#user-1", "sk": "STATE"},
        )

    def test_user_window_boundary_is_atomic(self) -> None:
        limits = self._limits(user_window=3)

        accepted = self.usage_controls.admit_run(
            "user-1",
            "group:work:round-1",
            run_units=3,
            now=self.now,
            limits=limits,
        )
        denied = self.usage_controls.admit_run(
            "user-1", "direct:turn-2", now=self.now, limits=limits
        )

        self.assertTrue(accepted.allowed)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "user_rate_limit")
        self.assertNotIn(
            ("USER#user-1", "USAGE_ADMISSION#direct:turn-2"), self.table.items
        )
        month = self.table.items[("USER#user-1", "USAGE_LIMIT#MONTH#2026-09")]
        self.assertEqual(month["runUnits"], 3)

    def test_monthly_boundary_applies_across_short_windows(self) -> None:
        limits = self._limits(monthly=2)
        later = datetime(2026, 9, 11, 12, 2, tzinfo=UTC)

        self.assertTrue(
            self.usage_controls.admit_run(
                "user-1",
                "direct:turn-1",
                run_units=2,
                now=self.now,
                limits=limits,
            ).allowed
        )
        denied = self.usage_controls.admit_run(
            "user-1", "direct:turn-2", now=later, limits=limits
        )

        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "monthly_limit")

    def test_global_window_counts_different_users(self) -> None:
        limits = self._limits(global_window=2)
        for user_id in ("user-1", "user-2"):
            self.assertTrue(
                self.usage_controls.admit_run(
                    user_id,
                    f"direct:{user_id}",
                    now=self.now,
                    limits=limits,
                ).allowed
            )

        denied = self.usage_controls.admit_run(
            "user-3", "direct:user-3", now=self.now, limits=limits
        )

        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "global_rate_limit")

    def test_manual_circuit_is_read_consistently_and_stops_admission(self) -> None:
        key = self.usage_controls.USAGE_CIRCUIT_KEY
        self.table.items[(key["pk"], key["sk"])] = {
            **key,
            "entity": "USAGE_CIRCUIT",
            "open": True,
        }

        decision = self.usage_controls.admit_run(
            "user-1", "direct:turn-1", now=self.now, limits=self._limits()
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "circuit_open")
        self.assertEqual(len(self.table.client.transactions), 0)

    def test_manual_circuit_stops_reused_admission_before_continuation(self) -> None:
        limits = self._limits()
        self.assertTrue(
            self.usage_controls.admit_run(
                "user-1", "direct:turn-1", now=self.now, limits=limits
            ).allowed
        )
        key = self.usage_controls.USAGE_CIRCUIT_KEY
        self.table.items[(key["pk"], key["sk"])] = {
            **key,
            "entity": "USAGE_CIRCUIT",
            "open": True,
        }

        decision = self.usage_controls.admit_run(
            "user-1", "direct:turn-1", now=self.now, limits=limits
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "circuit_open")

    def test_uncertain_idempotent_start_can_reconcile_after_circuit_closes(self) -> None:
        limits = self._limits()
        self.assertTrue(
            self.usage_controls.admit_run(
                "user-1", "browser:bot-1:start-1", now=self.now, limits=limits
            ).allowed
        )
        key = self.usage_controls.USAGE_CIRCUIT_KEY
        self.table.items[(key["pk"], key["sk"])] = {
            **key,
            "entity": "USAGE_CIRCUIT",
            "open": True,
        }

        decision = self.usage_controls.admit_run(
            "user-1",
            "browser:bot-1:start-1",
            now=self.now,
            limits=limits,
            allow_duplicate_during_circuit=True,
        )

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.duplicate)

    def test_storage_errors_fail_closed(self) -> None:
        with (
            patch.object(self.table, "get_item", side_effect=RuntimeError("down")),
            self.assertRaises(self.usage_controls.UsageControlUnavailable),
        ):
            self.usage_controls.admit_run(
                "user-1",
                "direct:turn-1",
                now=self.now,
                limits=self._limits(),
            )

    def test_malformed_manual_circuit_fails_closed(self) -> None:
        key = self.usage_controls.USAGE_CIRCUIT_KEY
        self.table.items[(key["pk"], key["sk"])] = {
            **key,
            "entity": "USAGE_CIRCUIT",
            "open": "false",
        }

        with self.assertRaises(self.usage_controls.UsageControlUnavailable):
            self.usage_controls.admit_run(
                "user-1", "direct:turn-1", now=self.now, limits=self._limits()
            )

    def test_deleting_billing_account_cannot_admit_or_resume_a_run(self) -> None:
        self.table.items[("USER#user-1", "STATE")] = {
            "pk": "USER#user-1",
            "sk": "STATE",
            "entity": "USER_STATE",
            "accountStatus": "DELETING",
        }

        decision = self.usage_controls.admit_run(
            "user-1", "direct:turn-1", now=self.now, limits=self._limits()
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "account_inactive")
        self.assertEqual(self.table.client.transactions, [])

    def test_account_deletion_race_is_closed_inside_the_transaction(self) -> None:
        original = self.table.client.transact_write_items

        def delete_before_commit(**kwargs):
            self.table.items[("USER#user-1", "STATE")] = {
                "pk": "USER#user-1",
                "sk": "STATE",
                "entity": "USER_STATE",
                "accountStatus": "DELETING",
            }
            return original(**kwargs)

        with patch.object(
            self.table.client,
            "transact_write_items",
            side_effect=delete_before_commit,
        ):
            decision = self.usage_controls.admit_run(
                "user-1", "direct:turn-1", now=self.now, limits=self._limits()
            )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "account_inactive")
        self.assertNotIn(
            ("USER#user-1", "USAGE_ADMISSION#direct:turn-1"), self.table.items
        )

    def test_youtube_account_deletion_race_cannot_create_a_lease(self) -> None:
        original = self.table.client.transact_write_items

        def delete_before_commit(**kwargs):
            self.table.items[("USER#user-1", "STATE")] = {
                "pk": "USER#user-1",
                "sk": "STATE",
                "entity": "USER_STATE",
                "accountStatus": "DELETING",
            }
            return original(**kwargs)

        with patch.object(
            self.table.client,
            "transact_write_items",
            side_effect=delete_before_commit,
        ):
            decision = self.youtube_quota.reserve_youtube_search_calls(
                "user-1", "runtime:session-1", now=self.now
            )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "account_inactive")
        self.assertFalse(
            any(
                item.get("entity") == "USAGE_PROVIDER_ADMISSION"
                for item in self.table.items.values()
            )
        )

    def test_ambiguous_success_is_reconciled_from_the_durable_marker(self) -> None:
        original = self.table.client.transact_write_items

        def commit_then_disconnect(**kwargs):
            original(**kwargs)
            raise BotoCoreError("response lost")

        with (
            patch.object(
                self.table.client,
                "transact_write_items",
                side_effect=commit_then_disconnect,
            ),
            patch.object(self.usage_controls.time, "sleep"),
        ):
            decision = self.usage_controls.admit_run(
                "user-1", "direct:turn-1", now=self.now, limits=self._limits()
            )

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.duplicate)
        month = self.table.items[("USER#user-1", "USAGE_LIMIT#MONTH#2026-09")]
        self.assertEqual(month["runUnits"], 1)

    def test_in_progress_admission_retries_same_transaction_until_commit(self) -> None:
        original = self.table.client.transact_write_items
        calls = []
        in_progress = self.usage_controls.ClientError("transaction in progress")
        in_progress.response = {
            "Error": {"Code": "TransactionInProgressException"}
        }

        def settle_on_retry(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise in_progress
            return original(**kwargs)

        with (
            patch.object(
                self.table.client,
                "transact_write_items",
                side_effect=settle_on_retry,
            ),
            patch.object(self.usage_controls.time, "sleep") as sleep,
        ):
            decision = self.usage_controls.admit_run(
                "user-1", "direct:turn-1", now=self.now, limits=self._limits()
            )

        self.assertTrue(decision.allowed)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        sleep.assert_called_once_with(0.5)
        month = self.table.items[("USER#user-1", "USAGE_LIMIT#MONTH#2026-09")]
        self.assertEqual(month["runUnits"], 1)

    def test_timeout_youtube_reservation_retries_same_transaction_once(self) -> None:
        original = self.table.client.transact_write_items
        calls = []

        def commit_on_retry(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise BotoCoreError("response timed out")
            return original(**kwargs)

        with (
            patch.object(
                self.table.client,
                "transact_write_items",
                side_effect=commit_on_retry,
            ),
            patch.object(self.usage_controls.time, "sleep") as sleep,
        ):
            decision = self.youtube_quota.reserve_youtube_search_calls(
                "user-1", "runtime:session-1", now=self.now, daily_limit=6
            )

        self.assertTrue(decision.allowed)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], calls[1])
        sleep.assert_called_once_with(0.5)
        counter = self.table.items[
            (
                "SYSTEM#USAGE_CONTROL",
                "USAGE_LIMIT#PROVIDER#YOUTUBE_SEARCH#DAY#2026-09-11",
            )
        ]
        self.assertEqual(counter["runUnits"], 3)

    def test_youtube_ambiguous_success_reconciles_the_durable_lease(self) -> None:
        original = self.table.client.transact_write_items

        def commit_then_disconnect(**kwargs):
            original(**kwargs)
            raise BotoCoreError("response lost")

        with (
            patch.object(
                self.table.client,
                "transact_write_items",
                side_effect=commit_then_disconnect,
            ),
            patch.object(self.usage_controls.time, "sleep"),
        ):
            decision = self.youtube_quota.reserve_youtube_search_calls(
                "user-1", "runtime:session-1", now=self.now
            )

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.duplicate)
        counter = self.table.items[
            (
                "SYSTEM#USAGE_CONTROL",
                "USAGE_LIMIT#PROVIDER#YOUTUBE_SEARCH#DAY#2026-09-11",
            )
        ]
        self.assertEqual(counter["runUnits"], 3)

    def test_negative_or_wrong_entity_counter_fails_closed(self) -> None:
        month_key = ("USER#user-1", "USAGE_LIMIT#MONTH#2026-09")
        for counter in (
            {"runUnits": -1, "entity": "USAGE_MONTH_COUNTER"},
            {"runUnits": 0, "entity": "SOMETHING_ELSE"},
        ):
            with self.subTest(counter=counter):
                self.table.items.clear()
                self.table.client.transactions.clear()
                self.table.items[month_key] = {
                    "pk": month_key[0],
                    "sk": month_key[1],
                    **counter,
                }
                with self.assertRaises(
                    self.usage_controls.UsageControlUnavailable
                ):
                    self.usage_controls.admit_run(
                        "user-1",
                        "direct:turn-1",
                        now=self.now,
                        limits=self._limits(),
                    )
                self.assertNotIn(
                    ("USER#user-1", "USAGE_ADMISSION#direct:turn-1"),
                    self.table.items,
                )
