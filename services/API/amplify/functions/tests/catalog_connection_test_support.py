from __future__ import annotations

from shared.catalog import CatalogError


class ConnectionCatalogCases:
    def test_home_assistant_connection_is_private_and_bounded_to_assist(self) -> None:
        saved = self.catalog.save_home_assistant_connection(
            "owner", "https://home.example.com", "a" * 48
        )
        self.assertEqual(saved["name"], "Home Assistant")
        self.assertEqual(saved["risk"], "interactive")
        self.assertNotIn("a" * 48, repr(saved))
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
