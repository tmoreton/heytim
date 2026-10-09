from __future__ import annotations

import ast
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from shared import billing
from shared.memory_identity import memory_actor_id
from worker_test_case import WorkerTestCase


class ReleaseFixtureBillingTests(WorkerTestCase):
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    destination: ClassVar[dict[str, str]] = {
        "HEYTIM_STRIPE_AVAILABLE": "false",
        "HEYTIM_FREE_ONLY_MODE": "true",
        "HEYTIM_FREE_MONTHLY_CREDITS": "30",
        "USER_POOL_ID": "us-east-1_biJejrNQF",
        "FILES_BUCKET_NAME": "heytim-production-user-files-820323452649-us-east-1",
    }

    def test_pinned_identity_matches_the_managed_regression_fixture(self):
        source = (
            Path(__file__).resolve().parents[4]
            / "runtime/scripts/run_managed_regression.py"
        )
        assignments = [
            node.value.value
            for node in ast.parse(source.read_text()).body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "RELEASE_TEST_ACTOR_ID"
                for target in node.targets
            )
        ]
        self.assertEqual(assignments, [billing.RELEASE_TEST_ACTOR_ID])

    def test_allowance_requires_exact_fixture_and_destination(self):
        with (
            patch.dict(os.environ, self.destination),
            patch.object(billing, "RELEASE_TEST_ACTOR_ID", memory_actor_id("user-1")),
        ):
            fixture = billing.entitlement_for_user(self.table, "user-1", now=self.now)
            customer = billing.entitlement_for_user(self.table, "user-2", now=self.now)
            self.assertEqual(fixture.credit_limit, 300)
            self.assertEqual(customer.credit_limit, 30)
            for key in ("USER_POOL_ID", "FILES_BUCKET_NAME", "HEYTIM_FREE_ONLY_MODE"):
                with self.subTest(key=key), patch.dict(os.environ, {key: "other"}):
                    entitlement = billing.entitlement_for_user(
                        self.table, "user-1", now=self.now
                    )
                    # Legacy preview behavior is independent of this allowance.
                    if entitlement.plan == "free":
                        self.assertEqual(entitlement.credit_limit, 30)
                    else:
                        self.assertEqual(entitlement.plan, "preview")

    def test_fixture_retains_metering_and_monthly_boundary(self):
        key = ("USER#user-1", "USAGE_LIMIT#MONTH#2026-10")
        self.table.items[key] = {"pk": key[0], "sk": key[1], "runUnits": 299}
        with (
            patch.dict(os.environ, self.destination),
            patch.object(billing, "RELEASE_TEST_ACTOR_ID", memory_actor_id("user-1")),
        ):
            allowed = self.usage_controls.admit_run(
                "user-1", "direct:allowed", now=self.now
            )
            denied = self.usage_controls.admit_run(
                "user-1", "direct:denied", now=self.now
            )
        self.assertTrue(allowed.allowed)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "monthly_limit")
        self.assertEqual(self.table.items[key]["runUnits"], 300)

    def test_customer_still_stops_at_thirty(self):
        key = ("USER#user-2", "USAGE_LIMIT#MONTH#2026-10")
        self.table.items[key] = {"pk": key[0], "sk": key[1], "runUnits": 30}
        with (
            patch.dict(os.environ, self.destination),
            patch.object(billing, "RELEASE_TEST_ACTOR_ID", memory_actor_id("user-1")),
        ):
            denied = self.usage_controls.admit_run(
                "user-2", "direct:customer", now=self.now
            )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "monthly_limit")

    def test_fixture_cannot_bypass_global_rate_limit(self):
        limits = self.usage_controls.UsageLimits(
            monthly_run_units=1000,
            user_window_run_units=30,
            global_window_run_units=1,
            window_seconds=60,
        )
        with (
            patch.dict(os.environ, self.destination),
            patch.object(billing, "RELEASE_TEST_ACTOR_ID", memory_actor_id("user-1")),
            patch.object(self.usage_controls, "USAGE_LIMITS", limits),
        ):
            first = self.usage_controls.admit_run(
                "user-1", "direct:first", now=self.now
            )
            second = self.usage_controls.admit_run(
                "user-1", "direct:second", now=self.now
            )
        self.assertTrue(first.allowed)
        self.assertFalse(second.allowed)
        self.assertEqual(second.reason, "global_rate_limit")
