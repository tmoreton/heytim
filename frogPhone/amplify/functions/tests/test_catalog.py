from __future__ import annotations

import time
import unittest
from contextlib import contextmanager
from decimal import Decimal

import shared.catalog as catalog_module
from shared.catalog import CatalogService


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

    def query(self, *, ExpressionAttributeValues: dict, Limit: int | None = None, **_kwargs) -> dict:
        pk = ExpressionAttributeValues[":pk"]
        prefix = ExpressionAttributeValues.get(":prefix", "")
        items = [dict(item) for (item_pk, sk), item in self.items.items() if item_pk == pk and sk.startswith(prefix)]
        return {"Items": items[:Limit] if Limit else items}

    @contextmanager
    def batch_writer(self):
        yield FakeBatch(self)


class CatalogServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_module._last_sync_at = time.monotonic()
        self.table = FakeTable()
        self.catalog = CatalogService(self.table)
        self.catalog._store_official(catalog_module.FALLBACK_TOOLS, catalog_module.FALLBACK_SKILLS)

    def test_cold_start_performs_initial_sync(self) -> None:
        catalog_module._last_sync_at = 0
        calls = []
        self.catalog._sync_remote = lambda: calls.append("sync")
        self.catalog.sync_official()
        self.assertEqual(calls, ["sync"])

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
        self.assertIn("quote only", self.catalog.get_version(first["id"], 1)["instructions"])
        self.assertIn("include counts", self.catalog.get_version(first["id"], 2)["instructions"])

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

    def test_all_catalog_tools_are_visible_and_resolve_to_reviewed_runtime_bindings(self) -> None:
        tools = self.catalog.list_tools()
        self.assertEqual(len(tools), sum(tool["enabled"] for tool in catalog_module.FALLBACK_TOOLS))

        resolved = self.catalog.resolve_tools_for_runtime(["delegate", "web_search", "calculator"])
        self.assertEqual(
            resolved,
            [
                {"id": "delegate", "runtime": {"kind": "stan_subagent", "name": "generalist"}},
                {"id": "web_search", "runtime": {"kind": "gateway", "operations": ["WebSearch"]}},
                {"id": "calculator", "runtime": {"kind": "local", "name": "calculator"}},
            ],
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
            [*catalog_module.FALLBACK_TOOLS, {"id": "old_tool", "name": "Old", "description": "Old tool."}],
            [*catalog_module.FALLBACK_SKILLS, stale],
        )
        self.catalog._store_official(catalog_module.FALLBACK_TOOLS, catalog_module.FALLBACK_SKILLS)

        self.assertNotIn(("SYSTEM#TOOLS", "TOOL#old_tool"), self.table.items)
        self.assertNotIn(("SYSTEM#SKILLS", "SKILL#old-skill"), self.table.items)
        self.assertIn(("SKILL#old-skill", "VERSION#000000001"), self.table.items)


if __name__ == "__main__":
    unittest.main()
