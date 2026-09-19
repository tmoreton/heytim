from __future__ import annotations

from unittest.mock import patch


class ExternalProviderOAuthCases:
    def test_zoom_callback_saves_a_single_read_only_account(self) -> None:
        state = "zoom-callback-state-with-enough-entropy"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/zoom-production-ABC123"
        )
        self.data_table.put_item(Item={
            **self.external._state_key(state),
            "userId": "user-1", "provider": "zoom", "verifier": "verifier-token",
            "returnUrl": "heytim://app?connection=zoom",
            "clientSecretArn": secret_arn, "expiresAt": 2_000,
        })
        with (
            patch.object(self.external.time, "time", return_value=1_000),
            patch.object(self.external, "_exchange_code", return_value={
                "access_token": "access-token", "refresh_token": "refresh-token",
                "expires_in": 3600,
                "scope": "user:read:user meeting:read:list_meetings meeting:read:meeting",
            }),
            patch.object(self.external, "_bearer_json", return_value={
                "id": "zoom-user-1", "email": "owner@example.com",
            }) as profile,
            patch.object(self.catalog, "save_external_oauth_connection") as save,
        ):
            response = self.external._external_callback(
                {"state": state, "code": "authorization-code"}
            )
        self.assertIn("status=connected", response["headers"]["location"])
        self.assertEqual(save.call_args.args[1:4], ("zoom", "owner@example.com", "zoom-user-1"))
        self.assertEqual(profile.call_args.args[0], "https://api.zoom.us/v2/users/me")

    def test_teams_callback_saves_separate_microsoft_connection(self) -> None:
        state = "teams-callback-state-with-enough-entropy"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/microsoft-production-ABC123"
        )
        self.data_table.put_item(Item={
            **self.external._state_key(state),
            "userId": "user-1", "provider": "microsoft_teams", "verifier": "verifier-token",
            "returnUrl": "heytim://app?connection=microsoft_teams",
            "clientSecretArn": secret_arn, "expiresAt": 2_000,
        })
        with (
            patch.object(self.external.time, "time", return_value=1_000),
            patch.object(self.external, "_exchange_code", return_value={
                "access_token": "access-token", "refresh_token": "refresh-token",
                "expires_in": 3600,
                "scope": "User.Read Team.ReadBasic.All Channel.ReadBasic.All ChannelMessage.Read.All",
            }),
            patch.object(self.external, "_bearer_json", return_value={
                "id": "account-1", "mail": "owner@example.com",
            }),
            patch.object(self.catalog, "save_external_oauth_connection") as save,
        ):
            response = self.external._external_callback(
                {"state": state, "code": "authorization-code"}
            )
        self.assertIn("status=connected", response["headers"]["location"])
        self.assertEqual(save.call_args.args[1:4], (
            "microsoft_teams", "owner@example.com", "account-1"
        ))

    def test_jira_callback_requires_one_site_and_saves_its_id(self) -> None:
        state = "jira-callback-state-with-enough-entropy"
        site_id = "11223344-a1b2-3b33-c444-def123456789"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/jira-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.external._state_key(state),
                "userId": "user-1",
                "provider": "jira",
                "verifier": "verifier-token",
                "returnUrl": "heytim://app?connection=jira",
                "clientSecretArn": secret_arn,
                "expiresAt": 2_000,
            }
        )
        with (
            patch.object(self.external.time, "time", return_value=1_000),
            patch.object(
                self.external, "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3_600,
                },
            ),
            patch.object(
                self.external, "_bearer_list",
                return_value=[{
                    "id": site_id,
                    "name": "Frog team",
                    "scopes": ["read:jira-work"],
                }],
            ),
            patch.object(self.catalog, "save_external_oauth_connection") as save,
        ):
            response = self.external._external_callback(
                {"state": state, "code": "authorization-code"}
            )
        self.assertIn("status=connected", response["headers"]["location"])
        self.assertEqual(save.call_args.args[1:4], ("jira", "Frog team", site_id))

    def test_hubspot_callback_saves_only_the_selected_crm_account(self) -> None:
        state = "hubspot-callback-state-with-enough-entropy"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/hubspot-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.external._state_key(state),
                "userId": "user-1",
                "provider": "hubspot",
                "verifier": "verifier-token",
                "returnUrl": "heytim://app?connection=hubspot",
                "clientSecretArn": secret_arn,
                "expiresAt": 2_000,
            }
        )
        with (
            patch.object(self.external.time, "time", return_value=1_000),
            patch.object(
                self.external, "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3_600,
                },
            ),
            patch.object(
                self.external, "_oauth_client",
                return_value=("client-id", "client-secret", secret_arn),
            ),
            patch.object(
                self.external, "_request_json",
                return_value={
                    "active": True,
                    "hub_id": 12345,
                    "hub_domain": "example.com",
                    "scopes": list(self.external.EXTERNAL_PROVIDER_SPECS["hubspot"]["scopes"]),
                },
            ) as inspect,
            patch.object(self.catalog, "save_external_oauth_connection") as save,
        ):
            response = self.external._external_callback(
                {"state": state, "code": "authorization-code"}
            )
        self.assertIn("status=connected", response["headers"]["location"])
        self.assertEqual(
            save.call_args.args[1:4], ("hubspot", "example.com", "12345")
        )
        self.assertEqual(save.call_args.args[4]["refreshToken"], "refresh-token")
        self.assertIn("/oauth/2026-03/token/introspect", inspect.call_args.args[0].full_url)

    def test_microsoft_callback_accepts_case_normalized_read_scopes(self) -> None:
        state = "microsoft-callback-state-with-enough-entropy"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/microsoft-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.external._state_key(state),
                "userId": "user-1",
                "provider": "microsoft",
                "verifier": "verifier-token",
                "returnUrl": "heytim://app?connection=microsoft",
                "clientSecretArn": secret_arn,
                "expiresAt": 2_000,
            }
        )
        with (
            patch.object(self.external.time, "time", return_value=1_000),
            patch.object(
                self.external,
                "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3_600,
                    "scope": (
                        "user.read mail.read calendars.read files.read.all "
                        "sites.read.all openid profile email offline_access"
                    ),
                },
            ),
            patch.object(
                self.external,
                "_bearer_json",
                return_value={"id": "account-1", "mail": "owner@example.com"},
            ),
            patch.object(self.catalog, "save_external_oauth_connection") as save,
        ):
            response = self.external._external_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertIn("status=connected", response["headers"]["location"])
        self.assertEqual(
            save.call_args.args[1:4], ("microsoft", "owner@example.com", "account-1")
        )
        self.assertEqual(save.call_args.args[4]["expiresAt"], 4_600)

    def test_external_authorization_urls_are_provider_specific_and_read_only(
        self,
    ) -> None:
        redirect_uri = "https://api.example.com/public/oauth/provider/callback"
        environment = {"EXTERNAL_OAUTH_REDIRECT_URI": redirect_uri}
        with (
            patch.dict(self.external.os.environ, environment),
            patch.object(
                self.external,
                "_oauth_client",
                return_value=(
                    "client-id-1234",
                    "client-secret-long-enough",
                    "secret-arn",
                ),
            ),
            patch.object(
                self.external.secrets,
                "token_urlsafe",
                side_effect=[
                    "slack-state-with-enough-entropy",
                    "slack-verifier-with-enough-entropy",
                    "microsoft-state-with-enough-entropy",
                    "microsoft-verifier-with-enough-entropy",
                    "notion-state-with-enough-entropy",
                    "notion-verifier-with-enough-entropy",
                ],
            ),
        ):
            value = {"returnUrl": "heytim://app?oauth=connection"}
            slack = self.external._begin_slack_authorization("user-1", value)
            microsoft = self.external._begin_microsoft_authorization("user-1", value)
            notion = self.external._begin_notion_authorization("user-1", value)

        slack_query = dict(
            self.external.urllib.parse.parse_qsl(
                slack["authorizationUrl"].split("?", 1)[1]
            )
        )
        self.assertEqual(
            set(slack_query["user_scope"].split(",")),
            set(self.external.EXTERNAL_PROVIDER_SPECS["slack"]["scopes"]),
        )
        self.assertNotIn("chat:write", slack_query["user_scope"])

        microsoft_query = dict(
            self.external.urllib.parse.parse_qsl(
                microsoft["authorizationUrl"].split("?", 1)[1]
            )
        )
        self.assertEqual(microsoft_query["code_challenge_method"], "S256")
        self.assertIn("Mail.Read", microsoft_query["scope"])
        self.assertNotIn("Mail.Send", microsoft_query["scope"])
        self.assertNotIn("Files.ReadWrite", microsoft_query["scope"])

        notion_query = dict(
            self.external.urllib.parse.parse_qsl(
                notion["authorizationUrl"].split("?", 1)[1]
            )
        )
        self.assertEqual(notion_query["owner"], "user")
        self.assertEqual(notion_query["redirect_uri"], redirect_uri)

    def test_slack_callback_saves_rotating_user_grant(self) -> None:
        state = "slack-callback-state-with-enough-entropy"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/slack-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.external._state_key(state),
                "userId": "user-1",
                "provider": "slack",
                "verifier": "verifier-token",
                "returnUrl": "heytim://app?connection=slack",
                "clientSecretArn": secret_arn,
                "expiresAt": 2_000,
            }
        )
        scopes = self.external.EXTERNAL_PROVIDER_SPECS["slack"]["scopes"]
        with (
            patch.object(self.external.time, "time", return_value=1_000),
            patch.object(
                self.external,
                "_exchange_code",
                return_value={
                    "ok": True,
                    "team": {"id": "T123", "name": "Froggy Workspace"},
                    "authed_user": {
                        "id": "U123",
                        "scope": ",".join(scopes),
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                        "expires_in": 43_200,
                    },
                },
            ),
            patch.object(self.catalog, "save_external_oauth_connection") as save,
        ):
            response = self.external._external_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertIn("status=connected", response["headers"]["location"])
        save.assert_called_once_with(
            "user-1",
            "slack",
            "Froggy Workspace",
            "T123:U123",
            {
                "accessToken": "access-token",
                "refreshToken": "refresh-token",
                "expiresAt": 44_200,
            },
            secret_arn,
            list(scopes),
        )

    def test_notion_callback_saves_only_workspace_content_access(self) -> None:
        state = "notion-callback-state-with-enough-entropy"
        secret_arn = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/notion-production-ABC123"
        )
        self.data_table.put_item(
            Item={
                **self.external._state_key(state),
                "userId": "user-1",
                "provider": "notion",
                "verifier": "verifier-token",
                "returnUrl": "heytim://app?connection=notion",
                "clientSecretArn": secret_arn,
                "expiresAt": 2_000,
            }
        )
        with (
            patch.object(self.external.time, "time", return_value=1_000),
            patch.object(
                self.external,
                "_exchange_code",
                return_value={
                    "access_token": "access-token",
                    "token_type": "bearer",
                    "workspace_id": "workspace-1",
                    "workspace_name": "Froggy Notes",
                    "bot_id": "notion-bot-1",
                    "owner": {
                        "type": "user",
                        "user": {
                            "id": "owner-1",
                            "person": {"email": "owner@example.com"},
                        },
                    },
                },
            ),
            patch.object(self.catalog, "save_external_oauth_connection") as save,
        ):
            response = self.external._external_callback(
                {"state": state, "code": "authorization-code"}
            )

        self.assertIn("status=connected", response["headers"]["location"])
        save.assert_called_once_with(
            "user-1",
            "notion",
            "Froggy Notes · owner@example.com",
            "workspace-1:owner-1",
            {"accessToken": "access-token"},
            secret_arn,
            ["read_content"],
        )

    def test_notion_accounts_in_one_workspace_have_distinct_ids(self) -> None:
        token = {
            "access_token": "access-token",
            "token_type": "bearer",
            "workspace_id": "workspace-1",
            "workspace_name": "Froggy Notes",
            "owner": {"type": "user", "user": {"id": "owner-1"}},
        }
        first_id, _, _ = self.external._notion_connection(token)
        token["owner"]["user"]["id"] = "owner-2"
        second_id, _, _ = self.external._notion_connection(token)
        self.assertEqual(first_id, "workspace-1:owner-1")
        self.assertEqual(second_id, "workspace-1:owner-2")


class ModuleGlobals:
    """Expose a callback's defining module globals without re-importing it."""

    def __init__(self, function) -> None:
        object.__setattr__(self, "_values", function.__globals__)

    def __getattr__(self, name):
        return self._values[name]

    def __getattribute__(self, name):
        if name == "__dict__":
            return object.__getattribute__(self, "_values")
        return object.__getattribute__(self, name)

    def __setattr__(self, name, value) -> None:
        self._values[name] = value

    def __delattr__(self, name) -> None:
        del self._values[name]
