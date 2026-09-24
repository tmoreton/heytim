from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import shared.catalog_sync as sync_module
import test_api_safety
import test_catalog

TEST_BOT = {
    "id": "test-planner",
    "version": 1,
    "name": "Test planner",
    "tagline": "Turns a test request into a practical plan.",
    "prompt": "Create a concise plan and make assumptions explicit.",
    "color": "#58BEAA",
    "skillIds": ["planner"],
    "toolIds": [],
    "source": "official",
    "category": "Testing",
    "author": "Test suite",
    "tags": ["test"],
    "featured": True,
}


class BotCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        sync_module._last_sync_at = time.monotonic()
        self.table = test_catalog.FakeTable()
        self.catalog = test_catalog.CatalogService(
            self.table, test_catalog.FakeSecrets()
        )
        self.catalog._store_official(
            test_catalog.TEST_TOOLS, test_catalog.TEST_SKILLS, [TEST_BOT]
        )

    def test_public_bot_metadata_is_installable_without_runtime_or_secrets(self) -> None:
        result = self.catalog.public_catalog()
        template = result["bots"][0]

        self.assertEqual(template["id"], "test-planner")
        self.assertEqual(template["skillIds"], ["planner"])
        self.assertNotIn("runtime", template)
        self.assertNotIn("credential", template)

    def test_stale_bot_listing_is_removed_but_version_is_retained(self) -> None:
        stale = {**TEST_BOT, "id": "old-bot", "skillIds": []}
        self.catalog._store_official(
            test_catalog.TEST_TOOLS, test_catalog.TEST_SKILLS, [TEST_BOT, stale]
        )
        self.catalog._store_official(
            test_catalog.TEST_TOOLS, test_catalog.TEST_SKILLS, [TEST_BOT]
        )

        self.assertNotIn(("SYSTEM#BOTS", "BOT#old-bot"), self.table.items)
        self.assertIn(
            ("BOT_TEMPLATE#old-bot", "VERSION#000000001"), self.table.items
        )

    def test_catalog_rejects_model_or_runtime_choices_in_bot_config(self) -> None:
        raw_skill = {
            **test_catalog.TEST_SKILLS[0],
            "path": "skills/planner/SKILL.md",
        }
        raw_bot = {**TEST_BOT, "model": "provider.fast"}
        with (
            patch.object(
                sync_module,
                "_fetch_json",
                return_value={
                    "schemaVersion": 3,
                    "repository": "tmoreton/heytim",
                    "release": "skills-v11",
                    "tools": test_catalog.TEST_TOOLS,
                    "skills": [raw_skill],
                    "bots": [raw_bot],
                },
            ),
            patch.object(
                sync_module,
                "_fetch_text",
                return_value=(
                    "---\nname: planner\ndescription: Test planner.\n---\n"
                    "Create a concise test plan."
                ),
            ),
            self.assertRaisesRegex(test_catalog.CatalogError, "unsupported bot fields"),
        ):
            self.catalog._sync_remote()


class BotInstallTests(test_api_safety.ApiTestCase):
    def test_catalog_template_install_unions_skill_required_tools(self) -> None:
        template = {
            **TEST_BOT,
            "id": "youtube-studio",
            "skillIds": ["youtube-strategy", "youtube-thumbnail-director"],
        }
        required_tools = {
            "youtube-strategy": ["youtube_search", "web_search"],
            "youtube-thumbnail-director": ["image_generator", "web_search"],
        }
        with (
            patch.object(self.bots.catalog, "get_bot_template", return_value=template),
            patch.object(self.bots, "_list_bots", return_value=[]),
            patch.object(
                self.bots.catalog,
                "validate_and_pin",
                return_value={
                    "youtube-strategy": 2,
                    "youtube-thumbnail-director": 3,
                },
            ),
            patch.object(
                self.bots.catalog,
                "get_version",
                side_effect=lambda skill_id, _version: {
                    "requiredToolIds": required_tools[skill_id]
                },
            ),
            patch.object(
                self.bots.catalog,
                "validate_tools",
                side_effect=lambda _user, tool_ids: list(dict.fromkeys(tool_ids)),
            ),
            patch.object(
                self.bots.catalog,
                "approval_tool_ids",
                return_value=["image_generator"],
            ),
        ):
            installed = self.bots._install_bot_template("user-1", template["id"])

        self.assertEqual(
            installed["toolIds"],
            ["youtube_search", "web_search", "image_generator"],
        )
        self.assertEqual(installed["extraToolIds"], [])
        self.assertEqual(installed["actionApprovalMode"], "automatic")
        self.assertEqual(installed["alwaysAllowedToolIds"], ["image_generator"])
        self.assertEqual(
            installed["skillVersions"],
            {"youtube-strategy": 2, "youtube-thumbnail-director": 3},
        )

    def test_catalog_template_install_tracks_provenance(self) -> None:
        template = {
            **TEST_BOT,
            "id": "decision-coach",
            "version": 2,
            "skillIds": [],
        }
        with (
            patch.object(self.bots.catalog, "get_bot_template", return_value=template),
            patch.object(self.bots, "_list_bots", return_value=[]),
            patch.object(
                self.bots,
                "_bot_values",
                return_value={
                    "name": template["name"],
                    "tagline": template["tagline"],
                    "prompt": template["prompt"],
                    "color": template["color"],
                    "toolIds": [],
                    "extraToolIds": [],
                    "alwaysAllowedToolIds": [],
                    "githubRepositoryAccess": {},
                    "skillIds": [],
                    "skillVersions": {},
                },
            ),
        ):
            installed = self.bots._install_bot_template("user-1", template["id"])

        self.assertEqual(installed["templateId"], "decision-coach")
        self.assertEqual(installed["templateVersion"], 2)
        self.assertNotEqual(installed["id"], template["id"])

    def test_catalog_template_cannot_be_installed_twice(self) -> None:
        template = {"id": "decision-coach", "version": 1}
        with (
            patch.object(self.bots.catalog, "get_bot_template", return_value=template),
            patch.object(
                self.bots,
                "_list_bots",
                return_value=[{"templateId": "decision-coach"}],
            ),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.bots._install_bot_template("user-1", template["id"])

        self.assertEqual(error.exception.status_code, 409)

    def test_chief_template_install_applies_the_protected_role(self) -> None:
        template = {**TEST_BOT, "id": "chief", "skillIds": []}
        values = {
            "name": template["name"],
            "tagline": template["tagline"],
            "prompt": template["prompt"],
            "color": "#FFBC3B",
            "toolIds": [],
            "extraToolIds": [],
            "alwaysAllowedToolIds": [],
            "githubRepositoryAccess": {},
            "skillIds": [],
            "skillVersions": {},
        }
        with (
            patch.object(self.bots.catalog, "get_bot_template", return_value=template),
            patch.object(self.bots, "_list_bots", return_value=[]),
            patch.object(self.bots, "_bot_values", return_value=values),
        ):
            installed = self.bots._install_bot_template("user-1", "chief")

        self.assertEqual(installed["systemRole"], "chief")
        self.assertEqual(installed["templateId"], "chief")
        self.assertEqual(installed["color"], "#FFBC3B")


if __name__ == "__main__":
    unittest.main()
