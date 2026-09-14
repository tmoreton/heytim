from __future__ import annotations

import os
import unittest
from unittest.mock import ANY, patch

import test_api_safety
from provider_oauth_test_support import ExternalProviderOAuthCases, ModuleGlobals


class ProviderOAuthTests(ExternalProviderOAuthCases, unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = test_api_safety.ApiSafetyTests
        if not hasattr(base, "google_oauth"):
            base.setUpClass()
        cls.data_table = base.data_table
        cls.catalog = base.support.catalog
        cls.google = base.google_oauth
        cls.github = ModuleGlobals(base.handler._github_callback)
        cls.x = ModuleGlobals(base.handler._x_callback)
        cls.external = ModuleGlobals(base.handler._external_callback)

    def setUp(self) -> None:
        self.data_table.items.clear()
        self.data_table.deleted.clear()
        self.data_table.put.clear()

    def test_github_installation_is_verified_and_saved_without_user_token(self) -> None:
        state = "github-state-token-with-enough-entropy"
        app_secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123:secret:"
            "frogbot/oauth/github-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.github._state_key(state),
                "userId": "user-1",
                "provider": "github",
                "returnUrl": "froggybot://app?connection=github",
                "appSecretArn": app_secret_arn,
                "verifier": "github-pkce-verifier-with-enough-entropy-1234567890",
                "expiresAt": 2_000,
            }
        )
        config = {
            "appId": "77",
            "clientId": "client-id",
            "clientSecret": "client-secret-long-enough",
            "privateKey": "private-key",
            "slug": "froggybot",
        }
        with (
            patch.object(self.github.time, "time", return_value=1_000),
            patch.object(
                self.github, "_app_config", return_value=(config, app_secret_arn)
            ),
            patch.object(self.github, "github_app_jwt", return_value="app-jwt"),
            patch.object(
                self.github,
                "_exchange_user_code",
                return_value={"access_token": "transient-user-token"},
            ) as exchange,
            patch.object(
                self.github,
                "_github_json",
                side_effect=[
                    {"installations": [{"id": 12345, "app_id": 77}]},
                    {
                        "app_id": 77,
                        "suspended_at": None,
                        "account": {"login": "frog-owner"},
                        "permissions": {"metadata": "read", "contents": "write"},
                    },
                ],
            ) as github_api,
            patch.object(
                self.github, "_installation_token", return_value="installation-token"
            ),
            patch.object(
                self.github,
                "_installation_repositories",
                return_value=[{"id": 101, "name": "frog-owner/froggybot"}],
            ),
            patch.object(self.catalog, "save_github_connection") as save,
            patch.object(self.github, "_revoke_user_token") as revoke,
        ):
            response = self.github._github_callback(
                {
                    "state": state,
                    "code": "authorization-code",
                }
            )

        self.assertIn("status=connected", response["headers"]["location"])
        save.assert_called_once_with(
            "user-1",
            "frog-owner",
            "12345",
            [{"id": 101, "name": "frog-owner/froggybot"}],
            {"metadata": "read", "contents": "write"},
            app_secret_arn,
        )
        self.assertNotIn("transient-user-token", repr(save.call_args))
        exchange.assert_called_once_with(
            "authorization-code",
            "github-pkce-verifier-with-enough-entropy-1234567890",
            config,
            ANY,
        )
        self.assertEqual(
            github_api.call_args_list[0].args[0],
            "https://api.github.com/user/installations?per_page=100",
        )
        revoke.assert_called_once_with("transient-user-token", config, ANY)

    def test_github_authorization_checks_for_an_existing_installation_first(
        self,
    ) -> None:
        oauth_state = "github-oauth-state-with-enough-entropy"
        verifier = "github-pkce-verifier-with-enough-entropy-1234567890"
        app_secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123:secret:"
            "frogbot/oauth/github-production-ABC123"
        )
        config = {
            "appId": "77",
            "clientId": "client-id",
            "clientSecret": "client-secret-long-enough",
            "privateKey": "private-key",
            "slug": "froggybot",
        }
        with (
            patch.object(
                self.github, "_app_config", return_value=(config, app_secret_arn)
            ),
            patch.object(
                self.github.secrets, "token_urlsafe", return_value=oauth_state
            ),
            patch.object(
                self.github,
                "_pkce_pair",
                return_value=(verifier, "challenge"),
            ),
        ):
            response = self.github._begin_github_authorization(
                "user-1", {"returnUrl": "froggybot://app?connection=github"}
            )

        location = response["authorizationUrl"]
        self.assertTrue(
            location.startswith("https://github.com/login/oauth/authorize?")
        )
        query = dict(self.github.urllib.parse.parse_qsl(location.split("?", 1)[1]))
        self.assertEqual(query["client_id"], "client-id")
        self.assertEqual(query["state"], oauth_state)
        self.assertEqual(query["code_challenge"], "challenge")
        saved_state = self.data_table.items[
            (self.github._state_key(oauth_state)["pk"], "STATE")
        ]
        self.assertEqual(saved_state["verifier"], verifier)
        self.assertNotIn("installationId", saved_state)

    def test_github_authorization_continues_to_install_when_none_exists(
        self,
    ) -> None:
        state = "github-oauth-state-with-enough-entropy"
        install_state = "github-install-state-with-enough-entropy"
        app_secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123:secret:"
            "frogbot/oauth/github-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.github._state_key(state),
                "userId": "user-1",
                "provider": "github",
                "returnUrl": "froggybot://app?connection=github",
                "appSecretArn": app_secret_arn,
                "verifier": "github-pkce-verifier-with-enough-entropy-1234567890",
                "expiresAt": 2_000,
            }
        )
        config = {
            "appId": "77",
            "clientId": "client-id",
            "clientSecret": "client-secret-long-enough",
            "privateKey": "private-key",
            "slug": "froggybot",
        }
        with (
            patch.object(self.github.time, "time", return_value=1_000),
            patch.object(
                self.github, "_app_config", return_value=(config, app_secret_arn)
            ),
            patch.object(
                self.github,
                "_exchange_user_code",
                return_value={"access_token": "transient-user-token"},
            ),
            patch.object(
                self.github, "_github_json", return_value={"installations": []}
            ),
            patch.object(
                self.github.secrets, "token_urlsafe", return_value=install_state
            ),
            patch.object(self.github, "_revoke_user_token") as revoke,
        ):
            response = self.github._github_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertIn(
            "https://github.com/apps/froggybot/installations/new?",
            response["headers"]["location"],
        )
        saved_state = self.data_table.items[
            (self.github._state_key(install_state)["pk"], "STATE")
        ]
        self.assertEqual(saved_state["userId"], "user-1")
        self.assertNotIn("verifier", saved_state)
        revoke.assert_called_once_with("transient-user-token", config, ANY)

    def test_github_setup_redirect_starts_pkce_ownership_check(self) -> None:
        state = "github-install-state-with-enough-entropy"
        oauth_state = "github-oauth-state-with-enough-entropy"
        verifier = "github-pkce-verifier-with-enough-entropy-1234567890"
        app_secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123:secret:"
            "frogbot/oauth/github-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.github._state_key(state),
                "userId": "user-1",
                "provider": "github",
                "returnUrl": "froggybot://app?connection=github",
                "appSecretArn": app_secret_arn,
                "expiresAt": 2_000,
            }
        )
        config = {
            "appId": "77",
            "clientId": "client-id",
            "clientSecret": "client-secret-long-enough",
            "privateKey": "private-key",
            "slug": "froggybot",
        }
        with (
            patch.object(self.github.time, "time", return_value=1_000),
            patch.object(
                self.github, "_app_config", return_value=(config, app_secret_arn)
            ),
            patch.object(
                self.github.secrets, "token_urlsafe", return_value=oauth_state
            ),
            patch.object(
                self.github,
                "_pkce_pair",
                return_value=(verifier, "challenge"),
            ),
        ):
            response = self.github._github_callback(
                {
                    "state": state,
                    "installation_id": "12345",
                    "setup_action": "install",
                }
            )

        location = response["headers"]["location"]
        self.assertTrue(
            location.startswith("https://github.com/login/oauth/authorize?")
        )
        query = dict(self.github.urllib.parse.parse_qsl(location.split("?", 1)[1]))
        self.assertEqual(query["client_id"], "client-id")
        self.assertEqual(query["state"], oauth_state)
        self.assertEqual(query["code_challenge"], "challenge")
        self.assertEqual(query["code_challenge_method"], "S256")
        saved_state = self.data_table.items[
            (self.github._state_key(oauth_state)["pk"], "STATE")
        ]
        self.assertEqual(saved_state["installationId"], "12345")
        self.assertEqual(saved_state["verifier"], verifier)

    def test_youtube_oauth_uses_only_readonly_scope_and_saves_channel(self) -> None:
        state = "youtube-state-token-with-enough-entropy"
        client_secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123:secret:frogbot/oauth/google-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.google._state_key(state),
                "userId": "user-1",
                "provider": "youtube",
                "verifier": "verifier",
                "returnUrl": "froggybot://app?connection=youtube",
                "clientSecretArn": client_secret_arn,
                "expiresAt": 2_000,
            }
        )
        with (
            patch.object(self.google.time, "time", return_value=1_000),
            patch.object(
                self.google,
                "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "scope": self.google.YOUTUBE_SCOPES[0],
                },
            ),
            patch.object(
                self.google,
                "_youtube_channel",
                return_value=("channel-1", "Froggy Channel"),
            ),
            patch.object(self.catalog, "save_oauth_api_connection") as save,
            patch.object(self.google, "_ensure_gmail_bot") as gmail_bot,
        ):
            response = self.google._google_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertIn("connection=youtube", response["headers"]["location"])
        self.assertIn("status=connected", response["headers"]["location"])
        save.assert_called_once_with(
            "user-1",
            "youtube",
            "Froggy Channel",
            "channel-1",
            "refresh-token",
            client_secret_arn,
            list(self.google.YOUTUBE_SCOPES),
        )
        gmail_bot.assert_not_called()

    def test_google_workspace_oauth_saves_one_read_only_mcp_bundle(self) -> None:
        state = "workspace-state-token-with-enough-entropy"
        client_secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123:secret:frogbot/oauth/google-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.google._state_key(state),
                "userId": "user-1",
                "provider": "google_workspace",
                "verifier": "verifier",
                "returnUrl": "froggybot://app?connection=google_workspace",
                "clientSecretArn": client_secret_arn,
                "expiresAt": 2_000,
            }
        )
        with (
            patch.object(self.google.time, "time", return_value=1_000),
            patch.object(
                self.google,
                "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "scope": " ".join(self.google.GOOGLE_WORKSPACE_SCOPES),
                },
            ),
            patch.object(
                self.google,
                "_google_workspace_account",
                return_value=("permission-1", "owner@example.com"),
            ),
            patch.object(self.catalog, "save_google_workspace_connection") as save,
            patch.object(self.google, "_ensure_gmail_bot") as gmail_bot,
        ):
            response = self.google._google_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertIn("connection=google_workspace", response["headers"]["location"])
        self.assertIn("status=connected", response["headers"]["location"])
        save.assert_called_once_with(
            "user-1",
            "owner@example.com",
            "permission-1",
            "refresh-token",
            client_secret_arn,
            list(self.google.GOOGLE_WORKSPACE_SCOPES),
        )
        gmail_bot.assert_not_called()

    def test_x_oauth_uses_pkce_and_read_scopes(self) -> None:
        state = "x-state-token-with-enough-entropy"
        verifier = "x-verifier-token-with-enough-entropy"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123:secret:"
            "frogbot/oauth/x-production-ABC123"
        )
        environment = {
            "X_OAUTH_REDIRECT_URI": "https://api.example.com/public/oauth/x/callback"
        }
        with (
            patch.dict(os.environ, environment),
            patch.object(
                self.x,
                "_oauth_client",
                return_value=("client-id", "secret", secret_arn),
            ),
            patch.object(
                self.x.secrets, "token_urlsafe", side_effect=[state, verifier]
            ),
            patch.object(self.x.time, "time", return_value=1_000),
        ):
            result = self.x._begin_x_authorization(
                "user-1", {"returnUrl": "froggybot://app?connection=x"}
            )

        query = dict(
            self.x.urllib.parse.parse_qsl(result["authorizationUrl"].split("?", 1)[1])
        )
        self.assertEqual(query["code_challenge_method"], "S256")
        self.assertEqual(set(query["scope"].split()), set(self.x.X_SCOPES))
        self.assertNotIn("tweet.write", query["scope"])
        saved_state = self.data_table.items[(self.x._state_key(state)["pk"], "STATE")]
        self.assertEqual(saved_state["provider"], "x")
        self.assertEqual(saved_state["clientSecretArn"], secret_arn)

    def test_x_callback_saves_only_read_scopes_and_rotatable_tokens(self) -> None:
        state = "x-callback-state-token-with-enough-entropy"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123:secret:"
            "frogbot/oauth/x-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.x._state_key(state),
                "userId": "user-1",
                "provider": "x",
                "verifier": "verifier-token",
                "returnUrl": "froggybot://app?connection=x",
                "clientSecretArn": secret_arn,
                "expiresAt": 2_000,
            }
        )
        token = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": " ".join(self.x.X_SCOPES),
            "expires_in": 7_200,
        }
        with (
            patch.object(self.x.time, "time", return_value=1_000),
            patch.object(self.x, "_exchange_code", return_value=token),
            patch.object(self.x, "_profile", return_value=("12345", "@froggybot")),
            patch.object(self.catalog, "save_oauth_api_connection") as save,
        ):
            response = self.x._x_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertIn("connection=x", response["headers"]["location"])
        self.assertIn("status=connected", response["headers"]["location"])
        save.assert_called_once_with(
            "user-1",
            "x",
            "@froggybot",
            "12345",
            "refresh-token",
            secret_arn,
            list(self.x.X_SCOPES),
            access_token="access-token",
            expires_at=8_200,
        )
        self.assertNotIn("tweet.write", repr(save.call_args))

    def test_x_callback_revokes_an_unused_grant_when_scopes_are_incomplete(
        self,
    ) -> None:
        state = "x-incomplete-scope-state-with-enough-entropy"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123:secret:"
            "frogbot/oauth/x-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.x._state_key(state),
                "userId": "user-1",
                "provider": "x",
                "verifier": "verifier-token",
                "returnUrl": "froggybot://app?connection=x",
                "clientSecretArn": secret_arn,
                "expiresAt": 2_000,
            }
        )
        with (
            patch.object(self.x.time, "time", return_value=1_000),
            patch.object(
                self.x,
                "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "scope": "tweet.read users.read",
                },
            ),
            patch.object(self.catalog, "revoke_unused_x_token") as revoke,
        ):
            response = self.x._x_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertIn("status=error", response["headers"]["location"])
        revoke.assert_called_once_with("refresh-token", secret_arn)

if __name__ == "__main__":
    unittest.main()
