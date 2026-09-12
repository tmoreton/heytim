from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import test_api_safety

GOOGLE_ENV = {
    "GOOGLE_OAUTH_SECRET_ARN": (
        "arn:aws:secretsmanager:us-east-1:123:secret:"
        "frogbot/oauth/google-ABC123"
    ),
    "GOOGLE_OAUTH_REDIRECT_URI": (
        "https://api.example.com/public/oauth/google/callback"
    ),
}


class GoogleOAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = test_api_safety.ApiSafetyTests
        if not hasattr(base, "google_oauth"):
            base.setUpClass()
        cls.data_table = base.data_table
        cls.google_oauth = base.google_oauth
        cls.catalog = base.support.catalog
        cls.bots = base.bots

    def setUp(self) -> None:
        self.data_table.items.clear()
        self.data_table.deleted.clear()
        self.data_table.put.clear()

    def test_authorization_uses_one_time_state_and_pkce(self) -> None:
        state = "state-token-with-enough-entropy"
        verifier = "verifier-token-with-enough-entropy"
        with (
            patch.dict(os.environ, GOOGLE_ENV),
            patch.object(
                self.google_oauth,
                "_oauth_client",
                return_value=("client-id", "client-secret"),
            ),
            patch.object(
                self.google_oauth.secrets,
                "token_urlsafe",
                side_effect=[state, verifier],
            ),
            patch.object(self.google_oauth.time, "time", return_value=1_000),
        ):
            result = self.google_oauth._begin_gmail_authorization(
                "user-1", {"returnUrl": "frogbot://app?oauth=gmail"}
            )

        query = result["authorizationUrl"].split("?", 1)[1]
        parameters = dict(self.google_oauth.urllib.parse.parse_qsl(query))
        self.assertEqual(parameters["access_type"], "offline")
        self.assertEqual(parameters["code_challenge_method"], "S256")
        item = self.data_table.items[
            (self.google_oauth._state_key(state)["pk"], "STATE")
        ]
        self.assertEqual(item["userId"], "user-1")
        self.assertEqual(item["expiresAt"], 1_600)

    def test_callback_consumes_state_and_creates_connection(self) -> None:
        state = "state-token-with-enough-entropy"
        state_item = {
            **self.google_oauth._state_key(state),
            "userId": "user-1",
            "verifier": "verifier",
            "returnUrl": "frogbot://app?oauth=gmail",
            "clientSecretArn": GOOGLE_ENV["GOOGLE_OAUTH_SECRET_ARN"],
            "expiresAt": 2_000,
        }
        self.data_table.put_item(Item=state_item)
        with (
            patch.dict(os.environ, GOOGLE_ENV),
            patch.object(self.google_oauth.time, "time", return_value=1_000),
            patch.object(
                self.google_oauth,
                "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "scope": " ".join(self.google_oauth.GMAIL_SCOPES),
                },
            ),
            patch.object(
                self.google_oauth,
                "_gmail_profile",
                return_value="owner@example.com",
            ),
            patch.object(
                self.catalog,
                "save_gmail_connection",
                return_value={"id": "connection_123"},
            ) as save,
            patch.object(self.google_oauth, "_ensure_gmail_bot") as ensure_bot,
        ):
            response = self.google_oauth._gmail_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertEqual(response["statusCode"], 302)
        self.assertIn("status=connected", response["headers"]["location"])
        self.assertNotIn((state_item["pk"], "STATE"), self.data_table.items)
        save.assert_called_once_with(
            "user-1",
            "owner@example.com",
            "refresh-token",
            GOOGLE_ENV["GOOGLE_OAUTH_SECRET_ARN"],
        )
        ensure_bot.assert_called_once_with("user-1", "connection_123")

    def test_callback_http_budget_fails_before_lambda_timeout(self) -> None:
        with (
            patch.object(self.google_oauth.time, "monotonic", return_value=20.0),
            self.assertRaisesRegex(self.google_oauth.ApiError, "took too long"),
        ):
            self.google_oauth._remaining_timeout(20.1)

    def test_callback_revokes_token_when_profile_validation_fails(self) -> None:
        state = "state-token-with-enough-entropy"
        self.data_table.put_item(
            Item={
                **self.google_oauth._state_key(state),
                "userId": "user-1",
                "verifier": "verifier",
                "returnUrl": "frogbot://app?oauth=gmail",
                "clientSecretArn": GOOGLE_ENV["GOOGLE_OAUTH_SECRET_ARN"],
                "expiresAt": 2_000,
            }
        )
        with (
            patch.dict(os.environ, GOOGLE_ENV),
            patch.object(self.google_oauth.time, "time", return_value=1_000),
            patch.object(
                self.google_oauth,
                "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "unused-refresh-token",
                    "scope": " ".join(self.google_oauth.GMAIL_SCOPES),
                },
            ),
            patch.object(
                self.google_oauth,
                "_gmail_profile",
                side_effect=self.google_oauth.ApiError(
                    400, "Google could not verify the Gmail account"
                ),
            ),
            patch.object(self.catalog, "revoke_unused_gmail_token") as revoke,
            patch.object(self.catalog, "save_gmail_connection") as save,
        ):
            response = self.google_oauth._gmail_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertIn("status=error", response["headers"]["location"])
        revoke.assert_called_once_with("unused-refresh-token")
        save.assert_not_called()

    def test_gmail_bot_creation_is_idempotent_across_concurrent_callbacks(
        self,
    ) -> None:
        with (
            patch.object(self.google_oauth, "_list_bots", return_value=[]),
            patch.object(self.google_oauth, "_create_bot") as create_bot,
        ):
            self.google_oauth._ensure_gmail_bot("user-1", "connection_123")
            self.google_oauth._ensure_gmail_bot("user-1", "connection_123")

        first = create_bot.call_args_list[0]
        second = create_bot.call_args_list[1]
        self.assertEqual(first.kwargs["bot_id"], second.kwargs["bot_id"])
        self.assertTrue(first.kwargs["require_active_account"])
        self.assertTrue(first.kwargs["create_only"])

    def test_callback_fails_closed_after_account_deletion_starts(self) -> None:
        state = "state-token-with-enough-entropy"
        state_item = {
            **self.google_oauth._state_key(state),
            "userId": "user-1",
            "verifier": "verifier",
            "returnUrl": "frogbot://app?oauth=gmail",
            "clientSecretArn": GOOGLE_ENV["GOOGLE_OAUTH_SECRET_ARN"],
            "expiresAt": 2_000,
        }
        self.data_table.put_item(Item=state_item)
        self.data_table.put_item(
            Item={
                "pk": "USER#user-1",
                "sk": "STATE",
                "entity": "USER_STATE",
                "accountStatus": "DELETING",
            }
        )
        with (
            patch.dict(os.environ, GOOGLE_ENV),
            patch.object(self.google_oauth.time, "time", return_value=1_000),
            patch.object(self.google_oauth, "_exchange_code") as exchange,
            patch.object(self.catalog, "save_gmail_connection") as save,
            patch.object(self.google_oauth, "_ensure_gmail_bot") as ensure_bot,
        ):
            response = self.google_oauth._gmail_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertEqual(response["statusCode"], 302)
        self.assertIn("status=error", response["headers"]["location"])
        self.assertNotIn((state_item["pk"], "STATE"), self.data_table.items)
        exchange.assert_not_called()
        save.assert_not_called()
        ensure_bot.assert_not_called()

    def test_callback_cannot_create_gmail_bot_after_deletion_snapshot(self) -> None:
        state = "state-token-with-enough-entropy"
        self.data_table.put_item(
            Item={
                **self.google_oauth._state_key(state),
                "userId": "user-1",
                "verifier": "verifier",
                "returnUrl": "frogbot://app?oauth=gmail",
                "clientSecretArn": GOOGLE_ENV["GOOGLE_OAUTH_SECRET_ARN"],
                "expiresAt": 2_000,
            }
        )
        self.data_table.put_item(
            Item={"pk": "USER#user-1", "sk": "STATE", "entity": "USER_STATE"}
        )

        def save_then_begin_deletion(*_args) -> dict:
            self.data_table.items[("USER#user-1", "STATE")][
                "accountStatus"
            ] = "DELETING"
            return {"id": "connection_123"}

        bot_values = {
            "name": "Gmail Assistant",
            "tagline": "Gmail help",
            "prompt": "Use Gmail safely.",
            "color": "#3984F6",
            "toolIds": ["connection_123"],
            "extraToolIds": ["connection_123"],
            "alwaysAllowedToolIds": [],
            "skillIds": [],
            "skillVersions": {},
        }
        with (
            patch.dict(os.environ, GOOGLE_ENV),
            patch.object(self.google_oauth.time, "time", return_value=1_000),
            patch.object(
                self.google_oauth,
                "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "scope": " ".join(self.google_oauth.GMAIL_SCOPES),
                },
            ),
            patch.object(
                self.google_oauth,
                "_gmail_profile",
                return_value="owner@example.com",
            ),
            patch.object(
                self.catalog,
                "save_gmail_connection",
                side_effect=save_then_begin_deletion,
            ),
            patch.object(self.google_oauth, "_list_bots", return_value=[]),
            patch.object(self.bots, "_bot_values", return_value=bot_values),
        ):
            response = self.google_oauth._gmail_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertEqual(response["statusCode"], 302)
        self.assertIn("status=error", response["headers"]["location"])
        self.assertFalse(
            any(
                pk == "USER#user-1" and sk.startswith("BOT#")
                for pk, sk in self.data_table.items
            )
        )


if __name__ == "__main__":
    unittest.main()
