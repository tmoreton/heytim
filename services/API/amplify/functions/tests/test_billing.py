from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from api_test_case import ApiTestCase


class BillingTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        usage_query = patch.object(
            self.data_table, "query", return_value={"Items": []}, create=True)
        usage_query.start()
        self.addCleanup(usage_query.stop)

    def test_free_summary_reports_current_credit_counter(self) -> None:
        with patch.dict(
            self.billing.os.environ,
            {
                "HEYTIM_STRIPE_AVAILABLE": "true",
                "HEYTIM_FREE_MONTHLY_CREDITS": "30",
                "HEYTIM_PLUS_PRICE_CENTS": "2000",
            },
        ):
            entitlement = self.billing.entitlement_for_user(
                self.data_table, "user-1"
            )
            self.data_table.items[("USER#user-1", entitlement.counter_sort_key)] = {
                "pk": "USER#user-1",
                "sk": entitlement.counter_sort_key,
                "runUnits": 7,
            }
            result = self.billing.billing_summary("user-1")

        self.assertEqual(result["plan"], "free")
        self.assertEqual(result["creditsUsed"], 7)
        self.assertEqual(result["creditsRemaining"], 23)
        self.assertTrue(result["checkoutAvailable"])
        self.assertEqual(result["price"]["unitAmount"], 2000)

    def test_fresh_free_account_has_30_credits_without_checkout(self) -> None:
        with patch.dict(
            self.billing.os.environ,
            {
                "HEYTIM_STRIPE_AVAILABLE": "false",
                "HEYTIM_FREE_ONLY_MODE": "true",
                "HEYTIM_FREE_MONTHLY_CREDITS": "30",
                "HEYTIM_MONTHLY_RUN_UNIT_LIMIT": "1000",
            },
        ):
            result = self.billing.billing_summary("user-1")

        self.assertEqual(result["plan"], "free")
        self.assertEqual(result["creditLimit"], 30)
        self.assertEqual(result["creditsRemaining"], 30)
        self.assertFalse(result["billingAvailable"])
        self.assertFalse(result["checkoutAvailable"])
        self.assertFalse(result["managementAvailable"])

    def test_existing_no_stripe_preview_keeps_its_1000_credit_limit(self) -> None:
        with patch.dict(
            self.billing.os.environ,
            {
                "HEYTIM_STRIPE_AVAILABLE": "false",
                "HEYTIM_FREE_ONLY_MODE": "false",
                "HEYTIM_MONTHLY_RUN_UNIT_LIMIT": "1000",
            },
        ):
            result = self.billing.billing_summary("user-1")

        self.assertEqual(result["plan"], "preview")
        self.assertEqual(result["creditLimit"], 1000)

    def test_usage_totals_paginate_all_bots_and_count_cached_input_once(self) -> None:
        now = datetime(2026, 10, 15, tzinfo=UTC)
        pages = [
            {
                "Items": [
                    {
                        "createdAt": "2026-10-02T10:00:00.000Z",
                        "costUsd": Decimal("0.0025"),
                        "costBasis": "provider_reported",
                        "costIncomplete": False,
                        "models": [{
                            "provider": "openrouter", "inputTokens": 100,
                            "outputTokens": 20, "cacheReadInputTokens": 75,
                            "cacheWriteInputTokens": 5, "reasoningTokens": 8,
                            "costBasis": "provider_reported",
                        }],
                    },
                    {
                        "createdAt": "2026-09-30T23:59:59.999Z",
                        "costUsd": Decimal("9"), "models": [],
                    },
                ],
                "LastEvaluatedKey": {"pk": "USER#user-1", "sk": "USAGE#first"},
            },
            {
                "Items": [
                    {
                        "createdAt": "2026-10-14T11:00:00.000Z",
                        "costUsd": Decimal("0.003"),
                        "costBasis": "estimated",
                        "costIncomplete": False,
                        "models": [{
                            "provider": "bedrock", "inputTokens": 50,
                            "outputTokens": 40, "cacheReadInputTokens": 30,
                            "cacheWriteInputTokens": 10, "reasoningTokens": 15,
                            "costBasis": "estimated",
                        }],
                    },
                    {
                        "createdAt": "2026-11-01T00:00:00.000Z",
                        "costUsd": Decimal("9"), "models": [],
                    },
                ]
            },
        ]
        with (
            patch.dict(self.billing.os.environ, {
                "HEYTIM_STRIPE_AVAILABLE": "false", "HEYTIM_FREE_ONLY_MODE": "true",
            }),
            patch.object(self.data_table, "query", side_effect=pages) as query,
        ):
            summary = self.billing.billing_summary("user-1", now=now)

        usage = summary["usage"]
        self.assertEqual(usage["periodStart"], "2026-10-01T00:00:00Z")
        self.assertEqual(usage["periodEnd"], "2026-11-01T00:00:00Z")
        self.assertEqual(usage["totalCostUsd"], "0.0055")
        self.assertEqual(usage["inputTokens"], 190)
        self.assertEqual(usage["outputTokens"], 60)
        self.assertEqual(usage["totalTokens"], 250)
        self.assertEqual(usage["cacheReadInputTokens"], 105)
        self.assertEqual(usage["cacheWriteInputTokens"], 15)
        self.assertEqual(usage["reasoningTokens"], 23)
        self.assertTrue(usage["costEstimated"])
        self.assertFalse(usage["costIncomplete"])
        self.assertEqual(query.call_count, 2)
        self.assertEqual(query.call_args_list[1].kwargs["ExclusiveStartKey"],
                         {"pk": "USER#user-1", "sk": "USAGE#first"})

    def test_plus_usage_uses_subscription_period_and_marks_partial_cost(self) -> None:
        start = datetime(2026, 9, 20, 12, tzinfo=UTC)
        end = datetime(2026, 10, 20, 12, tzinfo=UTC)
        self.data_table.items[("USER#user-1", "BILLING")] = {
            "subscriptionStatus": "active",
            "currentPeriodStart": int(start.timestamp()),
            "currentPeriodEnd": int(end.timestamp()),
        }
        with (
            patch.dict(self.billing.os.environ, {"HEYTIM_STRIPE_AVAILABLE": "true"}),
            patch.object(self.data_table, "query", return_value={"Items": [
                {
                    "createdAt": "2026-09-25T00:00:00Z",
                    "costUsd": Decimal("0.4"),
                    "costBasis": "partial", "costIncomplete": True,
                    "models": [{"provider": "openrouter", "inputTokens": 10,
                                "outputTokens": 5}],
                },
                {
                    "createdAt": "2026-10-20T12:00:00Z",
                    "costUsd": Decimal("10"), "models": [],
                },
            ]}),
        ):
            summary = self.billing.billing_summary(
                "user-1", now=datetime(2026, 10, 1, tzinfo=UTC))

        usage = summary["usage"]
        self.assertEqual(summary["plan"], "plus")
        self.assertEqual(usage["periodStart"], "2026-09-20T12:00:00Z")
        self.assertEqual(usage["periodEnd"], "2026-10-20T12:00:00Z")
        self.assertEqual(usage["totalCostUsd"], "0.4")
        self.assertEqual(usage["totalTokens"], 15)
        self.assertTrue(usage["costIncomplete"])

    def test_stripe_configuration_accepts_live_restricted_key(self) -> None:
        secrets = MagicMock()
        secrets.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "secretKey": "rk_live_restrictedvalue",
                    "webhookSecret": "whsec_value",
                }
            )
        }
        self.billing._secret_cache = None
        with (
            patch.dict(
                self.billing.os.environ,
                {
                    "HEYTIM_STRIPE_AVAILABLE": "true",
                    "STRIPE_LIVE_MODE": "true",
                    "STRIPE_SECRET_ID": "heytim/stripe/production",
                },
            ),
            patch.object(self.billing.boto3, "client", return_value=secrets),
        ):
            result = self.billing._stripe_configuration()
        self.billing._secret_cache = None

        self.assertEqual(result["secretKey"], "rk_live_restrictedvalue")

    def test_stripe_configuration_rejects_non_key_text(self) -> None:
        secrets = MagicMock()
        secrets.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "secretKey": "Copy this key now. It will not be shown again.",
                    "webhookSecret": "whsec_value",
                }
            )
        }
        self.billing._secret_cache = None
        with (
            patch.dict(
                self.billing.os.environ,
                {
                    "HEYTIM_STRIPE_AVAILABLE": "true",
                    "STRIPE_LIVE_MODE": "true",
                    "STRIPE_SECRET_ID": "heytim/stripe/production",
                },
            ),
            patch.object(self.billing.boto3, "client", return_value=secrets),
            self.assertRaisesRegex(self.billing.ApiError, "Subscriptions are not configured"),
        ):
            self.billing._stripe_configuration()
        self.billing._secret_cache = None

    def test_webhook_requires_and_accepts_valid_stripe_signature(self) -> None:
        body = json.dumps(
            {
                "id": "evt_test",
                "type": "invoice.paid",
                "created": int(time.time()),
                "livemode": False,
                "data": {"object": {}},
            },
            separators=(",", ":"),
        )
        timestamp = int(time.time())
        signature = hmac.new(
            b"whsec_test",
            str(timestamp).encode() + b"." + body.encode(),
            hashlib.sha256,
        ).hexdigest()
        event = {
            "body": body,
            "headers": {"stripe-signature": f"t={timestamp},v1={signature}"},
        }
        with patch.object(
            self.billing,
            "_stripe_configuration",
            return_value={"secretKey": "sk_test_value", "webhookSecret": "whsec_test"},
        ):
            response = self.billing.stripe_webhook(event)
            event["headers"]["stripe-signature"] = f"t={timestamp},v1=wrong"
            with self.assertRaisesRegex(self.billing.ApiError, "Invalid Stripe signature"):
                self.billing.stripe_webhook(event)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"]), {"received": True})


if __name__ == "__main__":
    import unittest

    unittest.main()
