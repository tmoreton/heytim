from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from worker_test_case import WorkerTestCase


class BillingEntitlementTests(WorkerTestCase):
    def test_active_plus_plan_uses_subscription_period_credit_counter(self) -> None:
        now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
        later = datetime(2026, 9, 11, 12, 2, tzinfo=UTC)
        period_start = int(now.timestamp()) - 60
        self.table.items[("USER#user-1", "BILLING")] = {
            "pk": "USER#user-1",
            "sk": "BILLING",
            "subscriptionStatus": "active",
            "currentPeriodStart": period_start,
            "currentPeriodEnd": int(now.timestamp()) + 86_400,
            "stripeCustomerId": "cus_test",
            "stripeSubscriptionId": "sub_test",
        }
        with patch.dict(
            self.usage_controls.os.environ,
            {
                "HEYTIM_STRIPE_AVAILABLE": "true",
                "HEYTIM_PLUS_MONTHLY_CREDITS": "2",
            },
        ):
            self.assertTrue(
                self.usage_controls.admit_run(
                    "user-1", "direct:turn-1", now=now
                ).allowed
            )
            self.assertTrue(
                self.usage_controls.admit_run(
                    "user-1", "direct:turn-2", now=later
                ).allowed
            )
            denied = self.usage_controls.admit_run(
                "user-1", "direct:turn-3", now=later
            )

        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "monthly_limit")
        counter = self.table.items[
            ("USER#user-1", f"USAGE_LIMIT#SUBSCRIPTION#{period_start}")
        ]
        self.assertEqual(counter["runUnits"], 2)
