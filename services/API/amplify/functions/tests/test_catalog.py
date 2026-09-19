from __future__ import annotations

import time
import unittest
from decimal import Decimal
from unittest.mock import patch

import shared.catalog_sync as sync_module
from catalog_connection_test_support import ConnectionCatalogCases
from catalog_test_fakes import FakeSecrets, FakeTable
from shared.catalog import CatalogError, CatalogService


def _tool(tool_id: str, provider: str, risk: str, runtime: dict, action: str) -> dict:
    return {
        "id": tool_id,
        "name": f"Test {tool_id.replace('_', ' ')}",
        "description": f"Exercise the {tool_id} test binding.",
        "provider": provider,
        "risk": risk,
        "category": "Testing",
        "author": "Test suite",
        "tags": ["test"],
        "actions": [action],
        "runtime": runtime,
        "enabled": True,
    }


TEST_TOOLS = [
    _tool(
        "web",
        "stan",
        "read",
        {"kind": "stan_builtin", "name": "web_fetch"},
        "Read a page",
    ),
    _tool(
        "web_search",
        "agentcore-gateway",
        "read",
        {"kind": "gateway", "operations": ["WebSearch"]},
        "Search sources",
    ),
    _tool(
        "calculator",
        "heytim",
        "read",
        {"kind": "local", "name": "calculator"},
        "Calculate a result",
    ),
    _tool(
        "current_time",
        "heytim",
        "read",
        {"kind": "local", "name": "current_time"},
        "Read a timezone",
    ),
    _tool(
        "delegate",
        "stan",
        "sandbox",
        {"kind": "stan_subagent", "name": "generalist"},
        "Delegate a task",
    ),
    _tool(
        "browser",
        "agentcore",
        "interactive",
        {"kind": "agentcore", "name": "browser"},
        "Interact with a page",
    ),
]

TEST_SKILLS = [
    {
        "id": "planner",
        "version": 1,
        "name": "Test planner",
        "description": "Plan a test outcome.",
        "instructions": "Create a concise test plan.",
        "requiredToolIds": [],
        "source": "official",
        "visibility": "public",
        "editable": False,
        "category": "Testing",
        "author": "Test suite",
        "tags": ["test"],
        "featured": True,
    }
]


class CatalogServiceTests(ConnectionCatalogCases, unittest.TestCase):
    def setUp(self) -> None:
        sync_module._last_sync_at = time.monotonic()
        sync_module._local_sync_delay = sync_module.SYNC_SECONDS
        self.table = FakeTable()
        self.secrets = FakeSecrets()
        self.catalog = CatalogService(self.table, self.secrets)
        self.catalog._store_official(TEST_TOOLS, TEST_SKILLS, [])

    def test_cold_start_performs_initial_sync(self) -> None:
        sync_module._last_sync_at = 0
        calls = []
        self.catalog._sync_remote = lambda: calls.append("sync")
        self.catalog.sync_official()
        self.assertEqual(calls, ["sync"])
        metadata = self.table.items[("SYSTEM#CATALOG", "METADATA")]
        self.assertEqual(metadata["syncStatus"], "READY")
        self.assertNotIn("syncLeaseId", metadata)

    def test_cold_instances_share_catalog_freshness(self) -> None:
        self.table.put_item(
            Item={
                "pk": "SYSTEM#CATALOG",
                "sk": "METADATA",
                "nextSyncAt": int(time.time()) + sync_module.SYNC_SECONDS,
            }
        )
        sync_module._last_sync_at = 0
        calls = []
        self.catalog._sync_remote = lambda: calls.append("sync")

        self.catalog.sync_official()

        self.assertEqual(calls, [])

    def test_cold_instances_do_not_duplicate_an_active_refresh(self) -> None:
        self.table.put_item(
            Item={
                "pk": "SYSTEM#CATALOG",
                "sk": "METADATA",
                "nextSyncAt": 0,
                "syncLeaseUntil": int(time.time()) + sync_module.SYNC_LEASE_SECONDS,
                "syncLeaseId": "another-instance",
            }
        )
        sync_module._last_sync_at = 0
        calls = []
        self.catalog._sync_remote = lambda: calls.append("sync")

        self.catalog.sync_official()

        self.assertEqual(calls, [])

    def test_failed_refresh_retries_on_the_short_interval(self) -> None:
        sync_module._last_sync_at = 0

        def fail() -> None:
            raise CatalogError("temporary failure")

        self.catalog._sync_remote = fail
        with self.assertLogs(sync_module.logger, level="ERROR"):
            self.catalog.sync_official()
        self.assertEqual(sync_module._local_sync_delay, sync_module.SYNC_RETRY_SECONDS)

        self.table.items[("SYSTEM#CATALOG", "METADATA")]["nextSyncAt"] = 0
        sync_module._last_sync_at = (
            time.monotonic() - sync_module.SYNC_RETRY_SECONDS - 1
        )
        calls = []
        self.catalog._sync_remote = lambda: calls.append("sync")
        self.catalog.sync_official()

        self.assertEqual(calls, ["sync"])
        self.assertEqual(sync_module._local_sync_delay, sync_module.SYNC_SECONDS)

    def test_catalog_fetches_only_from_the_reviewed_repository(self) -> None:
        trusted = (
            "https://heytim.ai/catalog.json",
            "https://heytim.ai/skills/trip-planner/SKILL.md",
        )
        for url in trusted:
            self.assertEqual(sync_module._trusted_catalog_url(url), url)
        for url in (
            "http://heytim.ai/catalog.json",
            "https://example.com/catalog.json",
            "https://heytim.ai/private/catalog.json",
            "https://heytim.ai/catalog.json?ref=other",
        ):
            with self.subTest(url=url), self.assertRaises(CatalogError):
                sync_module._trusted_catalog_url(url)

    def test_custom_skill_versions_are_immutable_and_pinned(self) -> None:
        first = self.catalog.save_skill(
            "owner",
            {
                "name": "Interview analyst",
                "description": "Find themes in customer interviews.",
                "instructions": "Group evidence into themes and quote only supplied material.",
                "requiredToolIds": [],
                "visibility": "private",
            },
        )
        pins = self.catalog.validate_and_pin("owner", [first["id"]])
        second = self.catalog.save_skill(
            "owner",
            {
                "name": "Interview analyst",
                "description": "Find themes in customer interviews.",
                "instructions": "Group evidence into themes, include counts, and quote only supplied material.",
                "requiredToolIds": [],
                "visibility": "link",
            },
            first["id"],
        )

        self.assertEqual(pins[first["id"]], 1)
        self.assertEqual(second["version"], 2)
        self.assertIn(
            "quote only", self.catalog.get_version(first["id"], 1)["instructions"]
        )
        self.assertIn(
            "include counts", self.catalog.get_version(first["id"], 2)["instructions"]
        )

    def test_custom_skill_can_use_a_replay_safe_creation_id(self) -> None:
        skill = self.catalog.save_skill(
            "owner",
            {
                "name": "Newsletter review",
                "description": "Reviews newsletter copy before publication.",
                "instructions": "Flag specific style issues without guessing authorship.",
                "requiredToolIds": [],
                "visibility": "private",
            },
            new_skill_id="skill-ai-1234567890abcdef",
        )

        self.assertEqual(skill["id"], "skill-ai-1234567890abcdef")
        self.assertEqual(
            self.catalog.get_skill("owner", skill["id"])["instructions"],
            "Flag specific style issues without guessing authorship.",
        )

    def test_shared_skill_installs_without_becoming_editable(self) -> None:
        skill = self.catalog.save_skill(
            "owner",
            {
                "name": "Launch reviewer",
                "description": "Review a launch plan before release.",
                "instructions": "Check audience, evidence, owner, timing, and rollback plan.",
                "requiredToolIds": ["current_time"],
                "visibility": "link",
            },
        )
        share = self.catalog.create_share("owner", skill["id"])
        token = share["token"]
        imported = self.catalog.import_share("recipient", token)

        self.assertFalse(imported["editable"])
        self.assertEqual(imported["relationship"], "installed")
        self.assertEqual(imported["requiredToolIds"], ["current_time"])

    def test_catalog_tools_are_visible_and_use_reviewed_runtime_bindings(self) -> None:
        tools = self.catalog.list_tools()
        self.assertEqual(len(tools), len(TEST_TOOLS))
        self.assertEqual({tool.get("source") for tool in tools}, {"official"})
        self.assertEqual(
            {tool["id"]: (tool["provider"], tool["risk"]) for tool in tools},
            {
                "web": ("stan", "read"),
                "web_search": ("agentcore-gateway", "read"),
                "calculator": ("heytim", "read"),
                "current_time": ("heytim", "read"),
                "delegate": ("stan", "sandbox"),
                "browser": ("agentcore", "interactive"),
            },
        )

        resolved = self.catalog.resolve_tools_for_runtime(
            "owner", ["delegate", "web_search", "calculator"]
        )
        self.assertEqual(
            resolved,
            [
                {
                    "id": "delegate",
                    "risk": "sandbox",
                    "runtime": {"kind": "stan_subagent", "name": "generalist"},
                },
                {
                    "id": "web_search",
                    "risk": "read",
                    "runtime": {"kind": "gateway", "operations": ["WebSearch"]},
                },
                {
                    "id": "calculator",
                    "risk": "read",
                    "runtime": {"kind": "local", "name": "calculator"},
                },
            ],
        )
        self.assertEqual(
            self.catalog.approval_tool_names("owner", ["web", "browser"]),
            ["Test browser"],
        )
        self.assertEqual(
            self.catalog.approval_tool_ids("owner", ["web", "browser"]),
            ["browser"],
        )
        self.assertEqual(
            self.catalog.unapproved_tools("owner", ["web", "browser"], ["browser"]),
            [],
        )

    def test_retired_tool_is_removed_but_unknown_tools_are_rejected(self) -> None:
        selected = self.catalog.validate_tools("owner", ["web", "meme_composer", "web"])
        self.assertEqual(selected, ["web"])
        self.assertEqual(
            self.catalog.retired_tool_ids(),
            ["meme_composer", "x_search", "youtube_search"],
        )
        with self.assertRaisesRegex(CatalogError, "Unknown tools: never_existed"):
            self.catalog.validate_tools("owner", ["web", "never_existed"])

    def test_execution_ignores_a_stale_connection_without_weakening_edits(self) -> None:
        configured = ["web", "connection_removed", "web"]

        self.assertEqual(self.catalog.available_tool_ids("owner", configured), ["web"])
        self.assertEqual(self.catalog.unapproved_tools("owner", configured, []), [])
        with self.assertRaisesRegex(CatalogError, "Unknown tools: connection_removed"):
            self.catalog.validate_tools("owner", configured)

    def test_available_tools_describe_unlisted_existing_capabilities(self) -> None:
        tools = [dict(item) for item in TEST_TOOLS]
        next(item for item in tools if item["id"] == "calculator")["listed"] = False
        self.catalog._store_official(tools, TEST_SKILLS, [])

        self.assertNotIn(
            "calculator", {item["id"] for item in self.catalog.list_tools("owner")}
        )
        available = self.catalog.available_tools(
            "owner", ["calculator", "connection_removed"]
        )

        self.assertEqual([item["id"] for item in available], ["calculator"])
        self.assertEqual(available[0]["name"], "Test calculator")
        self.assertNotIn("runtime", available[0])

    def test_managed_connection_is_user_scoped_without_exposing_secrets(self) -> None:
        saved = self.catalog.save_gmail_connection(
            "owner",
            "owner@example.com",
            "refresh-token",
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/google-ABC123",
        )

        self.assertNotIn("hasCredential", saved)
        self.assertNotIn("authType", saved)
        self.assertNotIn("endpoint", saved)
        self.assertNotIn("secretArn", saved)
        self.assertIn(
            saved["id"], {tool["id"] for tool in self.catalog.list_tools("owner")}
        )
        self.assertNotIn(
            saved["id"], {tool["id"] for tool in self.catalog.list_tools("other")}
        )
        resolved = self.catalog.resolve_tools_for_runtime("owner", [saved["id"]])
        self.assertEqual(resolved[0]["runtime"]["authType"], "oauth")
        self.assertNotIn("refreshToken", resolved[0]["runtime"])

    def test_google_workspace_connection_has_only_reviewed_read_tools(self) -> None:
        saved = self.catalog.save_google_workspace_connection(
            "owner",
            "owner@example.com",
            "permission-1",
            "refresh-token",
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/google-ABC123",
            [
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/documents.readonly",
                "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
                "https://www.googleapis.com/auth/calendar.events.freebusy",
                "https://www.googleapis.com/auth/calendar.events.readonly",
            ],
        )

        with patch(
            "shared.catalog_rules._hostname_resolves_publicly", return_value=True
        ):
            runtime = self.catalog.resolve_tools_for_runtime(
                "owner", [saved["id"]]
            )[0]["runtime"]

        self.assertEqual(runtime["kind"], "mcp_bundle")
        self.assertEqual(runtime["oauthProvider"], "google")
        self.assertEqual(
            {server["endpoint"] for server in runtime["servers"]},
            {
                "https://drivemcp.googleapis.com/mcp/v1",
                "https://docsmcp.googleapis.com/mcp/v1",
                "https://sheetsmcp.googleapis.com/mcp/v1",
                "https://calendarmcp.googleapis.com/mcp/v1",
            },
        )
        self.assertNotIn("delete_file", repr(runtime))
        self.assertNotIn("create_event", repr(runtime))

    def test_external_oauth_connection_keeps_credentials_server_side(self) -> None:
        scopes = [
            "openid",
            "profile",
            "email",
            "offline_access",
            "User.Read",
            "Mail.Read",
            "Calendars.Read",
            "Files.Read.All",
            "Sites.Read.All",
        ]
        saved = self.catalog.save_external_oauth_connection(
            "owner",
            "microsoft",
            "owner@example.com",
            "account-1",
            {
                "accessToken": "access-token",
                "refreshToken": "refresh-token",
                "expiresAt": 2_000_000_000,
            },
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/microsoft-production-ABC123",
            scopes,
        )

        self.assertNotIn("accessToken", repr(saved))
        self.assertNotIn("refreshToken", repr(saved))
        runtime = self.catalog.resolve_tools_for_runtime("owner", [saved["id"]])[0][
            "runtime"
        ]
        self.assertEqual(runtime["kind"], "provider_api")
        self.assertEqual(runtime["provider"], "microsoft")
        self.assertEqual(runtime["scopes"], scopes)
        self.assertNotIn("accessToken", repr(runtime))
        self.assertNotIn("refreshToken", repr(runtime))

    def test_external_oauth_connection_rejects_write_scope(self) -> None:
        with self.assertRaisesRegex(CatalogError, "OAuth scopes are invalid"):
            self.catalog.save_external_oauth_connection(
                "owner",
                "microsoft",
                "owner@example.com",
                "account-1",
                {
                    "accessToken": "access-token",
                    "refreshToken": "refresh-token",
                    "expiresAt": 2_000_000_000,
                },
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
                "heytim/oauth/microsoft-production-ABC123",
                ["User.Read", "Mail.Read", "Mail.Send"],
            )

    def test_jira_projects_are_limited_for_one_bot(self) -> None:
        site_id = "11223344-a1b2-3b33-c444-def123456789"
        saved = self.catalog.save_external_oauth_connection(
            "owner", "jira", "Frog team", site_id,
            {
                "accessToken": "access-token",
                "refreshToken": "refresh-token",
                "expiresAt": 2_000_000_000,
            },
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:"
            "heytim/oauth/jira-production-ABC123",
            ["offline_access", "read:jira-work"],
        )
        access = self.catalog.validate_jira_project_access(
            "owner", [saved["id"]], {saved["id"]: ["FROG"]}
        )
        with patch(
            "shared.catalog_rules._hostname_resolves_publicly", return_value=True
        ):
            runtime = self.catalog.resolve_tools_for_runtime(
                "owner", [saved["id"]], {}, access
            )[0]["runtime"]
        self.assertEqual(runtime["siteId"], site_id)
        self.assertEqual(runtime["projectKeys"], ["FROG"])
        with self.assertRaisesRegex(CatalogError, "project keys"):
            self.catalog.validate_jira_project_access(
                "owner", [saved["id"]], {saved["id"]: ["frog"]}
            )

    def test_legacy_connection_records_are_inert(self) -> None:
        self.table.put_item(
            Item={
                "pk": "USER#owner",
                "sk": "CONNECTION#connection_aaaaaaaaaaaaaaaaaaaa",
                "entity": "CONNECTION",
                "id": "connection_aaaaaaaaaaaaaaaaaaaa",
                "name": "Legacy token",
                "provider": "mcp",
                "authType": "bearer",
                "source": "user",
                "editable": True,
                "enabled": True,
            }
        )

        self.assertEqual(self.catalog.list_connections("owner"), [])
        with self.assertRaisesRegex(CatalogError, "Unknown tools"):
            self.catalog.resolve_tools_for_runtime(
                "owner", ["connection_aaaaaaaaaaaaaaaaaaaa"]
            )

    def test_public_catalog_contains_only_reviewed_installable_metadata(self) -> None:
        personal = self.catalog.save_skill(
            "owner",
            {
                "name": "Private helper",
                "description": "A private test skill.",
                "instructions": "Help with a private task.",
                "requiredToolIds": [],
                "visibility": "private",
            },
        )

        result = self.catalog.public_catalog()
        planner = next(skill for skill in result["skills"] if skill["id"] == "planner")
        search = next(tool for tool in result["tools"] if tool["id"] == "web_search")

        self.assertNotIn(personal["id"], {skill["id"] for skill in result["skills"]})
        self.assertNotIn("instructions", planner)
        self.assertNotIn("runtime", search)
        self.assertNotIn("credential", search)
        self.assertNotIn("x_search", {tool["id"] for tool in result["tools"]})
        self.assertEqual(planner["category"], "Testing")
        self.assertEqual(search["actions"], ["Search sources"])
        self.assertEqual(
            result["contributionUrl"],
            "https://github.com/tmoreton/heytim/blob/main/CONTRIBUTING.md",
        )
    def test_runtime_resolves_dynamodb_decimal_skill_versions(self) -> None:
        skill = self.catalog.resolve_for_runtime({"planner": Decimal(1)})
        self.assertEqual(skill[0]["id"], "planner")
        self.assertEqual(skill[0]["version"], 1)
    def test_catalog_removes_stale_listings_but_keeps_immutable_versions(self) -> None:
        stale = {
            "id": "old-skill",
            "version": 1,
            "name": "Old skill",
            "description": "No longer listed.",
            "requiredToolIds": [],
            "instructions": "Old instructions.",
            "source": "official",
            "visibility": "public",
            "editable": False,
        }
        self.catalog._store_official(
            [
                *TEST_TOOLS,
                {"id": "old_tool", "name": "Old", "description": "Old tool."},
            ],
            [*TEST_SKILLS, stale],
            [],
        )
        self.catalog._store_official(TEST_TOOLS, TEST_SKILLS, [])

        self.assertNotIn(("SYSTEM#TOOLS", "TOOL#old_tool"), self.table.items)
        self.assertNotIn(("SYSTEM#SKILLS", "SKILL#old-skill"), self.table.items)
        self.assertIn(("SKILL#old-skill", "VERSION#000000001"), self.table.items)

    def test_catalog_requires_new_versions_for_changed_skill_and_bot_content(self) -> None:
        original_skill = self.table.items[("SKILL#planner", "VERSION#000000001")].copy()
        revised_skill = {**TEST_SKILLS[0], "instructions": "A revised plan."}
        with self.assertRaisesRegex(CatalogError, "publish a new version"):
            self.catalog._store_official(TEST_TOOLS, [revised_skill], [])
        self.assertEqual(
            self.table.items[("SKILL#planner", "VERSION#000000001")],
            original_skill,
        )

        bot = {"id": "helper", "version": 1, "name": "Helper", "prompt": "First prompt"}
        self.catalog._store_official(TEST_TOOLS, TEST_SKILLS, [bot])
        with self.assertRaisesRegex(CatalogError, "publish a new version"):
            self.catalog._store_official(
                TEST_TOOLS, TEST_SKILLS, [{**bot, "prompt": "Revised prompt"}]
            )
        self.assertEqual(
            self.table.items[("BOT_TEMPLATE#helper", "VERSION#000000001")]["prompt"],
            "First prompt",
        )

        self.catalog._store_official(
            TEST_TOOLS,
            [{**revised_skill, "version": 2}],
            [{**bot, "version": 2, "prompt": "Revised prompt"}],
        )
        self.assertIn(("SKILL#planner", "VERSION#000000002"), self.table.items)
        self.assertIn(("BOT_TEMPLATE#helper", "VERSION#000000002"), self.table.items)

if __name__ == "__main__":
    unittest.main()
