from __future__ import annotations

from shared.catalog import CatalogError
from shared.connection_providers import connection_specs


class ConnectionCatalogCases:
    def test_multiple_mcp_servers_are_private_and_independently_assignable(self) -> None:
        first = self.catalog.save_mcp_server_connection(
            "owner", "Planning", "https://planning.example.com/mcp", "p" * 48
        )
        second = self.catalog.save_mcp_server_connection(
            "owner", "Research", "https://research.example.com/mcp", "r" * 48
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["provider"], "mcp_server")
        self.assertEqual(first["endpoint"], "https://planning.example.com/mcp")
        self.assertNotIn("p" * 48, repr(first))
        self.assertNotIn("r" * 48, repr(second))
        resolved = self.catalog.resolve_tools_for_runtime("owner", [first["id"]])
        self.assertEqual([tool["id"] for tool in resolved], [first["id"]])
        self.assertEqual(resolved[0]["runtime"]["authType"], "bearer_token")
        self.assertEqual(resolved[0]["runtime"]["endpoint"], "https://planning.example.com/mcp")
        replaced = self.catalog.save_mcp_server_connection(
            "owner", "Planning updated", "https://planning.example.com/mcp", "n" * 48
        )
        self.assertEqual(replaced["id"], first["id"])
        with self.assertRaises(CatalogError):
            self.catalog.save_mcp_server_connection(
                "owner", "Private", "https://127.0.0.1/mcp", "p" * 48
            )
        with self.assertRaises(CatalogError):
            self.catalog.save_mcp_server_connection(
                "owner", "Malformed", "https://planning.example.com/mcp", "p" * 47 + "\n"
            )
        with self.assertRaises(CatalogError):
            self.catalog.save_mcp_server_connection(
                "owner", "Malformed", "https://planning.example.com:invalid/mcp", "p" * 48
            )

    def test_home_assistant_connection_is_private_and_bounded_to_assist(self) -> None:
        saved = self.catalog.save_home_assistant_connection(
            "owner", "https://home.example.com", "a" * 48
        )
        self.assertEqual(saved["name"], "Home Assistant")
        self.assertEqual(saved["endpoint"], "https://home.example.com/api/mcp/assist")
        self.assertEqual(saved["risk"], "interactive")
        self.assertNotIn("a" * 48, repr(saved))
        listed = self.catalog.list_tools("owner")
        self.assertIn(saved["id"], [tool["id"] for tool in listed])
        self.assertEqual(
            next(tool for tool in listed if tool["id"] == saved["id"])["provider"],
            "mcp_server",
        )
        runtime = self.catalog.resolve_tools_for_runtime("owner", [saved["id"]])[0]
        self.assertEqual(runtime["runtime"]["endpoint"], "https://home.example.com/api/mcp/assist")
        self.assertEqual(runtime["runtime"]["authType"], "home_assistant_token")
        self.assertIn("secretArn", runtime["runtime"])
        self.assertIn(saved["id"], self.catalog.approval_tool_ids("owner", [saved["id"]]))
        padded = self.catalog.save_home_assistant_connection(
            "owner", "https://home.example.com/api/mcp/assist", "a" * 47 + "="
        )
        self.assertEqual(padded["id"], saved["id"])
        with self.assertRaises(CatalogError):
            self.catalog.save_home_assistant_connection(
                "owner", "http://home.example.com", "a" * 48
            )
        with self.assertRaises(CatalogError):
            self.catalog.save_home_assistant_connection(
                "owner", "https://home.example.com/api/states", "a" * 48
            )
        with self.assertRaises(CatalogError):
            self.catalog.save_home_assistant_connection(
                "owner", "https://home.example.com", "a" * 47 + "\n"
            )

        migrated = self.catalog.save_mcp_server_connection(
            "owner", "Home Assistant", "https://home.example.com/api/mcp/assist", "b" * 48
        )
        self.assertEqual(migrated["id"], saved["id"])
        self.assertEqual(migrated["provider"], "mcp_server")
        self.assertEqual(
            self.catalog.resolve_tools_for_runtime("owner", [saved["id"]])[0]["runtime"]["authType"],
            "bearer_token",
        )
        self.assertEqual(len(self.catalog.list_connections("owner")), 1)

    def test_managed_connection_reconnect_rotates_its_secret(self) -> None:
        saved = self.catalog.save_gmail_connection(
            "owner",
            "owner@example.com",
            "first-token",
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/google-ABC123",
        )
        first_item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]
        first_secret = first_item["secretArn"]

        replaced = self.catalog.save_gmail_connection(
            "owner",
            "owner@example.com",
            "second-token",
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/google-ABC123",
        )
        second_item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]

        self.assertNotIn("hasCredential", replaced)
        self.assertIn(first_secret, self.secrets.deleted)
        self.assertNotEqual(first_secret, second_item["secretArn"])

    def test_distinct_gmail_accounts_keep_distinct_grants(self) -> None:
        client_secret = (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/google-ABC123"
        )
        first = self.catalog.save_gmail_connection(
            "owner", "first@example.com", "first-token", client_secret
        )
        second = self.catalog.save_gmail_connection(
            "owner", "second@example.com", "second-token", client_secret
        )
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(
            {item["connectedAccount"] for item in self.catalog.list_connections("owner")},
            {"first@example.com", "second@example.com"},
        )
        first_binding = self.catalog.resolve_tools_for_runtime("owner", [first["id"]])
        second_binding = self.catalog.resolve_tools_for_runtime("owner", [second["id"]])
        self.assertEqual([item["id"] for item in first_binding], [first["id"]])
        self.assertEqual([item["id"] for item in second_binding], [second["id"]])
        self.assertNotEqual(
            first_binding[0]["runtime"]["secretArn"],
            second_binding[0]["runtime"]["secretArn"],
        )
        self.assertEqual(first_binding[0]["runtime"]["accountLabel"], "first@example.com")
        self.assertEqual(second_binding[0]["runtime"]["accountLabel"], "second@example.com")
        second_secret = self.table.items[
            ("USER#owner", f"CONNECTION#{second['id']}")
        ]["secretArn"]
        renewed = self.catalog.save_gmail_connection(
            "owner", "first@example.com", "new-first-token", client_secret
        )
        self.assertEqual(renewed["id"], first["id"])
        self.assertEqual(
            self.table.items[("USER#owner", f"CONNECTION#{second['id']}")]["secretArn"],
            second_secret,
        )

    def test_multiple_provider_accounts_are_selected_by_connection_id(self) -> None:
        client_secret = "arn:aws:secretsmanager:us-east-1:123456789012:secret:heytim/oauth/test"
        specs = connection_specs()
        grants = []
        for provider in ("x", "youtube"):
            for index in (1, 2):
                grants.append(self.catalog.save_oauth_api_connection(
                    "owner", provider, f"{provider}-{index}@example.com",
                    f"{provider}-account-{index}", f"refresh-{provider}-{index}",
                    client_secret, specs[provider]["scopes"],
                ))
        for index in (1, 2):
            grants.append(self.catalog.save_external_oauth_connection(
                "owner", "slack", f"workspace-{index}", f"slack-{index}",
                {"accessToken": f"access-{index}", "refreshToken": f"refresh-{index}",
                 "expiresAt": 2_000_000_000}, client_secret, specs["slack"]["scopes"],
            ))
            grants.append(self.catalog.save_google_workspace_connection(
                "owner", f"workspace-{index}@example.com", f"google-{index}",
                f"refresh-workspace-{index}", client_secret,
                specs["google_workspace"]["scopes"],
            ))
            grants.append(self.catalog.save_github_connection(
                "owner", f"org-{index}", str(100 + index),
                [{"id": index, "name": f"org-{index}/repo"}],
                {"metadata": "read", "contents": "write"}, client_secret,
            ))
        ids = [grant["id"] for grant in grants]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {item["id"] for item in self.catalog.list_connections("owner")})
        selected = ids[::2]
        self.assertEqual(self.catalog.validate_tools("owner", selected), selected)
        resolved = self.catalog.resolve_tools_for_runtime("owner", selected)
        self.assertEqual([tool["id"] for tool in resolved], selected)

    def test_github_repository_selection_is_narrowed_per_bot(self) -> None:
        github = self.catalog.save_github_connection(
            "owner", "example-org", "12345",
            [{"id": 101, "name": "example-org/one"},
             {"id": 202, "name": "example-org/two"}],
            {"metadata": "read", "contents": "write"},
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/github-ABC123",
        )
        access = self.catalog.validate_github_repository_access(
            "owner", [github["id"]], {github["id"]: [101]}
        )
        resolved = self.catalog.resolve_tools_for_runtime(
            "owner", [github["id"]], access
        )
        self.assertEqual(resolved[0]["runtime"]["repositoryIds"], [101])
        self.assertNotIn(
            "repositoryIds",
            self.catalog.resolve_tools_for_runtime("owner", [github["id"]])[0]["runtime"],
        )
        with self.assertRaisesRegex(CatalogError, "Choose repositories"):
            self.catalog.validate_github_repository_access(
                "owner", [github["id"]], {github["id"]: [303]}
            )
        with self.assertRaisesRegex(CatalogError, "assigned installation"):
            self.catalog.validate_github_repository_access(
                "owner", [], {github["id"]: [101]}
            )

    def test_connection_cannot_be_deleted_while_a_bot_uses_it(self) -> None:
        saved = self.catalog.save_gmail_connection(
            "owner",
            "owner@example.com",
            "refresh-token",
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/google-ABC123",
        )
        self.table.put_item(
            Item={
                "pk": "USER#owner",
                "sk": "BOT#one",
                "entity": "BOT",
                "name": "Notes bot",
                "toolIds": [saved["id"]],
            }
        )

        with self.assertRaisesRegex(CatalogError, "Notes bot"):
            self.catalog.delete_connection("owner", saved["id"])

    def test_skill_share_never_carries_a_private_connection(self) -> None:
        connection = self.catalog.save_gmail_connection(
            "owner",
            "owner@example.com",
            "refresh-token",
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/google-ABC123",
        )
        skill = self.catalog.save_skill(
            "owner",
            {
                "name": "Notes helper",
                "description": "Use my private notes when answering.",
                "instructions": "Use the connected notes server when it is relevant.",
                "requiredToolIds": [connection["id"]],
                "visibility": "private",
            },
        )

        with self.assertRaisesRegex(CatalogError, "private connections"):
            self.catalog.create_share("owner", skill["id"])
