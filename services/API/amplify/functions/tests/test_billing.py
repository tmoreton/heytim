from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import patch

from api_test_case import ApiTestCase


class BillingTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()

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
