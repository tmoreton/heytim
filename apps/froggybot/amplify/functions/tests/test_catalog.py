from __future__ import annotations

import time
import unittest
from contextlib import contextmanager
from decimal import Decimal

import shared.catalog_sync as sync_module
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
        "frogbot",
        "read",
        {"kind": "local", "name": "calculator"},
        "Calculate a result",
    ),
    _tool(
        "current_time",
        "frogbot",
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

class FakeConditionalCheckFailed(Exception):
    def __init__(self) -> None:
        super().__init__("conditional check failed")
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeBatch:
    def __init__(self, table: FakeTable):
        self.table = table

    def put_item(self, Item: dict) -> None:
        self.table.put_item(Item=Item)

    def delete_item(self, Key: dict) -> None:
        self.table.items.pop((Key["pk"], Key["sk"]), None)


class FakeTable:
    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    def put_item(self, *, Item: dict) -> None:
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def update_item(
        self,
        *,
        Key: dict,
        UpdateExpression: str,
        ConditionExpression: str,
        ExpressionAttributeNames: dict,
        ExpressionAttributeValues: dict,
    ) -> None:
        item = self.items.setdefault((Key["pk"], Key["sk"]), dict(Key))
        lease_name = ExpressionAttributeNames["#lease_id"]
        if "attribute_not_exists" in ConditionExpression:
            lease_until_name = ExpressionAttributeNames["#lease_until"]
            if item.get(lease_until_name, 0) > ExpressionAttributeValues[":now"]:
                raise FakeConditionalCheckFailed
            item.update(
                {
                    ExpressionAttributeNames["#entity"]: ExpressionAttributeValues[
                        ":entity"
                    ],
                    lease_until_name: ExpressionAttributeValues[":lease_until"],
                    lease_name: ExpressionAttributeValues[":lease_id"],
                    ExpressionAttributeNames["#status"]: ExpressionAttributeValues[
                        ":syncing"
                    ],
                }
            )
            return
        if item.get(lease_name) != ExpressionAttributeValues[":lease_id"]:
            raise FakeConditionalCheckFailed
        item.update(
            {
                ExpressionAttributeNames["#next_sync"]: ExpressionAttributeValues[
                    ":next_sync"
                ],
                ExpressionAttributeNames["#last_sync"]: ExpressionAttributeValues[
                    ":last_sync"
                ],
                ExpressionAttributeNames["#status"]: ExpressionAttributeValues[
                    ":status"
                ],
            }
        )
        item.pop(ExpressionAttributeNames["#lease_until"], None)
        item.pop(lease_name, None)

    def query(
        self, *, ExpressionAttributeValues: dict, Limit: int | None = None, **_kwargs
    ) -> dict:
        pk = ExpressionAttributeValues[":pk"]
        prefix = ExpressionAttributeValues.get(":prefix", "")
        items = [
            dict(item)
            for (item_pk, sk), item in self.items.items()
            if item_pk == pk and sk.startswith(prefix)
        ]
        return {"Items": items[:Limit] if Limit else items}

    @contextmanager
    def batch_writer(self):
        yield FakeBatch(self)


class FakeSecrets:
    class ResourceNotFoundException(Exception):
        pass

    def __init__(self):
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []
        self.exceptions = type(
            "Exceptions",
            (),
            {"ResourceNotFoundException": self.ResourceNotFoundException},
        )()

    def create_secret(self, *, Name: str, SecretString: str, **_kwargs) -> dict:
        arn = f"arn:aws:secretsmanager:us-east-1:123456789012:secret:{Name}-ABC123"
        self.values[arn] = SecretString
        return {"ARN": arn}

    def put_secret_value(self, *, SecretId: str, SecretString: str) -> None:
        self.values[SecretId] = SecretString

    def delete_secret(self, *, SecretId: str, RecoveryWindowInDays: int) -> None:
        if SecretId not in self.values:
            raise self.ResourceNotFoundException
        assert RecoveryWindowInDays == 7
        self.deleted.append(SecretId)
        self.values.pop(SecretId)


class CatalogServiceTests(unittest.TestCase):
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
            "https://froggybot.com/catalog.json",
            "https://froggybot.com/skills/trip-planner/SKILL.md",
        )
        for url in trusted:
            self.assertEqual(sync_module._trusted_catalog_url(url), url)
        for url in (
            "http://froggybot.com/catalog.json",
            "https://example.com/catalog.json",
            "https://froggybot.com/private/catalog.json",
            "https://froggybot.com/catalog.json?ref=other",
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
        self.assertEqual(
            {tool["id"]: (tool["provider"], tool["risk"]) for tool in tools},
            {
                "web": ("stan", "read"),
                "web_search": ("agentcore-gateway", "read"),
                "calculator": ("frogbot", "read"),
                "current_time": ("frogbot", "read"),
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
        with self.assertRaisesRegex(CatalogError, "Unknown tools: never_existed"):
            self.catalog.validate_tools("owner", ["web", "never_existed"])

    def test_private_mcp_connection_is_user_scoped_and_resolves_without_secret(
        self,
    ) -> None:
        saved = self.catalog.save_connection(
            "owner",
            {
                "name": "Private notes",
                "description": "Read and update my private notes.",
                "endpoint": "https://mcp.example.com/mcp",
                "risk": "interactive",
                "authType": "bearer",
                "credential": "private-token",
            },
        )

        self.assertTrue(saved["hasCredential"])
        self.assertNotIn("secretArn", saved)
        self.assertNotIn("credential", saved)
        self.assertIn(
            saved["id"], {tool["id"] for tool in self.catalog.list_tools("owner")}
        )
        self.assertNotIn(
            saved["id"], {tool["id"] for tool in self.catalog.list_tools("other")}
        )

        resolved = self.catalog.resolve_tools_for_runtime("owner", [saved["id"]])
        self.assertEqual(resolved[0]["runtime"]["kind"], "mcp")
        self.assertEqual(resolved[0]["runtime"]["headerName"], "Authorization")
        self.assertNotIn("credential", resolved[0]["runtime"])

    def test_private_connection_rejects_local_network_endpoints(self) -> None:
        for endpoint in (
            "http://mcp.example.com/mcp",
            "https://localhost/mcp",
            "https://127.0.0.1/mcp",
            "https://mcp.example.com:8443/mcp",
            "https://mcp.example.com/mcp?token=secret",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(CatalogError):
                self.catalog.save_connection(
                    "owner",
                    {
                        "name": "Unsafe server",
                        "description": "This endpoint should not be accepted.",
                        "endpoint": endpoint,
                        "risk": "read",
                        "authType": "none",
                    },
                )

    def test_private_connection_can_replace_a_deleted_credential(self) -> None:
        saved = self.catalog.save_connection(
            "owner",
            {
                "name": "Private notes",
                "description": "Read my notes.",
                "endpoint": "https://mcp.example.com/mcp",
                "risk": "read",
                "authType": "bearer",
                "credential": "first-token",
            },
        )
        first_item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]
        first_secret = first_item["secretArn"]

        self.catalog.save_connection("owner", {"authType": "none"}, saved["id"])
        replaced = self.catalog.save_connection(
            "owner",
            {"authType": "bearer", "credential": "second-token"},
            saved["id"],
        )
        second_item = self.table.items[("USER#owner", f"CONNECTION#{saved['id']}")]

        self.assertTrue(replaced["hasCredential"])
        self.assertIn(first_secret, self.secrets.deleted)
        self.assertNotEqual(first_secret, second_item["secretArn"])

    def test_connection_cannot_be_deleted_while_a_bot_uses_it(self) -> None:
        saved = self.catalog.save_connection(
            "owner",
            {
                "name": "Private notes",
                "description": "Read my notes.",
                "endpoint": "https://mcp.example.com/mcp",
                "risk": "read",
                "authType": "none",
            },
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
        connection = self.catalog.save_connection(
            "owner",
            {
                "name": "Private notes",
                "description": "Read my private notes.",
                "endpoint": "https://mcp.example.com/mcp",
                "risk": "read",
                "authType": "none",
            },
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
            "https://github.com/tmoreton/frogbot-skills/blob/main/CONTRIBUTING.md",
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


if __name__ == "__main__":
    unittest.main()
