from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import test_api_safety


class FinanceConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = test_api_safety.ApiSafetyTests
        if not hasattr(base, "finance"):
            base.setUpClass()
        cls.data_table = base.data_table
        cls.finance = base.finance

    def setUp(self) -> None:
        self.data_table.items.clear()
        self.data_table.deleted.clear()
        self.data_table.put.clear()

    @staticmethod
    def _arn(provider: str) -> str:
        return (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            f"heytim/oauth/{provider}-production-ABC123"
        )

    def test_quickbooks_authorization_stores_only_configuration_reference(self) -> None:
        state = "quickbooks-state-with-enough-entropy"
        arn = self._arn("quickbooks")
        config = {
            "clientId": "quickbooks-client",
            "clientSecret": "quickbooks-secret",
            "environment": "production",
        }
        with (
            patch.object(self.finance, "_configuration", return_value=(config, arn)),
            patch.object(self.finance.secrets, "token_urlsafe", return_value=state),
            patch.dict(
                os.environ,
                {
                    "QUICKBOOKS_OAUTH_REDIRECT_URI": (
                        "https://api.example.com/public/oauth/quickbooks/callback"
                    )
                },
            ),
        ):
            response = self.finance._begin_quickbooks_authorization(
                "user-1", {"returnUrl": "heytim://app?connection=quickbooks"}
            )

        self.assertTrue(response["authorizationUrl"].startswith(self.finance.QUICKBOOKS_AUTH_URL))
        saved = self.data_table.items[(self.finance._state_key(state)["pk"], "STATE")]
        self.assertEqual(saved["clientSecretArn"], arn)
        self.assertNotIn("clientSecret", saved)
        self.assertNotIn("quickbooks-secret", repr(saved))

    def test_quickbooks_callback_saves_company_grant(self) -> None:
        state = "quickbooks-callback-state-with-enough-entropy"
        arn = self._arn("quickbooks")
        self.data_table.put_item(
            Item={
                **self.finance._state_key(state),
                "userId": "user-1",
                "provider": "quickbooks",
                "returnUrl": "heytim://app?connection=quickbooks",
                "clientSecretArn": arn,
                "environment": "production",
                "expiresAt": 2_000,
            }
        )
        config = {
            "clientId": "quickbooks-client",
            "clientSecret": "quickbooks-secret",
            "environment": "production",
        }
        token = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3_600,
            "x_refresh_token_expires_in": 8_640_000,
        }
        with (
            patch.object(self.finance.time, "time", return_value=1_000),
            patch.object(self.finance, "_ensure_account_active"),
            patch.object(self.finance, "_configuration", return_value=(config, arn)),
            patch.object(self.finance, "_quickbooks_token", return_value=token),
            patch.object(
                self.finance, "_quickbooks_company", return_value="Acme Books"
            ),
            patch.object(
                self.finance.catalog, "save_quickbooks_connection"
            ) as save,
        ):
            response = self.finance._quickbooks_callback(
                {"state": state, "code": "authorization-code", "realmId": "12345"}
            )

        self.assertIn("status=connected", response["headers"]["location"])
        save.assert_called_once()
        args = save.call_args.args
        self.assertEqual(args[:3], ("user-1", "Acme Books", "12345"))
        self.assertEqual(args[3]["refreshToken"], "refresh-token")
        self.assertEqual(args[4:], (arn, "production"))

    def test_quickbooks_callback_revokes_grant_when_save_fails(self) -> None:
        state = "quickbooks-failed-save-state-with-enough-entropy"
        arn = self._arn("quickbooks")
        self.data_table.put_item(
            Item={
                **self.finance._state_key(state),
                "userId": "user-1",
                "provider": "quickbooks",
                "returnUrl": "heytim://app?connection=quickbooks",
                "clientSecretArn": arn,
                "environment": "production",
                "expiresAt": 2_000,
            }
        )
        config = {
            "clientId": "quickbooks-client",
            "clientSecret": "quickbooks-secret",
            "environment": "production",
        }
        token = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3_600,
        }
        with (
            patch.object(self.finance.time, "time", return_value=1_000),
            patch.object(self.finance, "_ensure_account_active"),
            patch.object(self.finance, "_configuration", return_value=(config, arn)),
            patch.object(self.finance, "_quickbooks_token", return_value=token),
            patch.object(self.finance, "_quickbooks_company", return_value="Acme"),
            patch.object(
                self.finance.catalog,
                "save_quickbooks_connection",
                side_effect=self.finance.CatalogError("save failed"),
            ),
            patch.object(
                self.finance.catalog, "revoke_unused_quickbooks_token"
            ) as revoke,
        ):
            response = self.finance._quickbooks_callback(
                {"state": state, "code": "authorization-code", "realmId": "12345"}
            )

        self.assertIn("status=error", response["headers"]["location"])
        revoke.assert_called_once_with(
            {
                "accessToken": "access-token",
                "refreshToken": "refresh-token",
                "expiresAt": 4_600,
            },
            arn,
        )

    def test_plaid_authorization_uses_hosted_link_without_storing_app_keys(self) -> None:
        state = "plaid-state-with-enough-entropy"
        arn = self._arn("plaid")
        config = {
            "clientId": "plaid-client-id",
            "clientSecret": "plaid-secret",
            "environment": "sandbox",
        }
        with (
            patch.object(self.finance, "_configuration", return_value=(config, arn)),
            patch.object(self.finance.secrets, "token_urlsafe", return_value=state),
            patch.object(
                self.finance,
                "_plaid_json",
                return_value={
                    "link_token": "link-sandbox-token",
                    "hosted_link_url": "https://secure.plaid.com/hl/session",
                },
            ) as plaid,
            patch.dict(
                os.environ,
                {
                    "PLAID_COMPLETION_REDIRECT_URI": (
                        "https://api.example.com/public/plaid/callback"
                    ),
                    "PLAID_OAUTH_REDIRECT_URI": "https://heytim.ai/plaid-oauth",
                },
            ),
        ):
            response = self.finance._begin_plaid_authorization(
                "user-1", {"returnUrl": "heytim://app?connection=plaid"}
            )

        self.assertEqual(response["authorizationUrl"], "https://secure.plaid.com/hl/session")
        payload = plaid.call_args.args[2]
        self.assertEqual(payload["products"], ["transactions"])
        self.assertEqual(payload["optional_products"], ["liabilities"])
        self.assertIn("state=plaid-state-with-enough-entropy", payload["hosted_link"]["completion_redirect_uri"])
        saved = self.data_table.items[(self.finance._state_key(state)["pk"], "STATE")]
        self.assertEqual(saved["appSecretArn"], arn)
        self.assertNotIn("clientSecret", saved)
        self.assertNotIn("plaid-secret", repr(saved))

    def test_plaid_callback_exchanges_public_token_and_saves_item(self) -> None:
        state = "plaid-callback-state-with-enough-entropy"
        arn = self._arn("plaid")
        self.data_table.put_item(
            Item={
                **self.finance._state_key(state),
                "userId": "user-1",
                "provider": "plaid",
                "returnUrl": "heytim://app?connection=plaid",
                "appSecretArn": arn,
                "environment": "sandbox",
                "linkToken": "link-sandbox-token",
                "expiresAt": 2_000,
            }
        )
        config = {
            "clientId": "plaid-client-id",
            "clientSecret": "plaid-secret",
            "environment": "sandbox",
        }
        link_result = {
            "link_sessions": [
                {
                    "results": {
                        "item_add_results": [
                            {
                                "public_token": "public-sandbox-token",
                                "institution": {"name": "Plaid Bank"},
                                "accounts": [
                                    {
                                        "id": "account_checking_123",
                                        "name": "Checking",
                                        "mask": "1111",
                                        "type": "depository",
                                        "subtype": "checking",
                                    },
                                    {
                                        "id": "account_card_456",
                                        "name": "Business Card",
                                        "mask": "4242",
                                        "type": "credit",
                                        "subtype": "credit card",
                                    },
                                ],
                            }
                        ]
                    }
                }
            ]
        }
        with (
            patch.object(self.finance.time, "time", return_value=1_000),
            patch.object(self.finance, "_ensure_account_active"),
            patch.object(self.finance, "_configuration", return_value=(config, arn)),
            patch.object(
                self.finance,
                "_plaid_json",
                side_effect=[
                    link_result,
                    {"access_token": "access-sandbox-token", "item_id": "item_12345678"},
                ],
            ),
            patch.object(self.finance.catalog, "save_plaid_connection") as save,
        ):
            response = self.finance._plaid_callback({"state": state})

        self.assertIn("status=connected", response["headers"]["location"])
        save.assert_called_once_with(
            "user-1",
            "Plaid Bank · 2 accounts",
            "item_12345678",
            "access-sandbox-token",
            arn,
            "sandbox",
            [
                {
                    "id": "account_checking_123",
                    "name": "Checking",
                    "mask": "1111",
                    "type": "depository",
                    "subtype": "checking",
                },
                {
                    "id": "account_card_456",
                    "name": "Business Card",
                    "mask": "4242",
                    "type": "credit",
                    "subtype": "credit card",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
