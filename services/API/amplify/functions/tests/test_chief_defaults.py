from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

from api_test_case import ApiTestCase
from shared.catalog import CatalogError


class ChiefDefaultsTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.defaults = self.chief_defaults
        catalog = json.loads((Path(__file__).resolve().parents[5] / "catalog/catalog.json").read_text())
        self.template = next(bot for bot in catalog["bots"] if bot["id"] == "chief")
        self.chief = {
            "id": "chief", "systemRole": "chief", "templateId": "chief", "templateVersion": 8,
            "name": "My Chief", "prompt": "Keep my custom prompt.",
            "modelPreference": "glm", "actionApprovalMode": "ask",
            "toolIds": ["browser", "current_time", "private-connection"],
            "extraToolIds": ["browser", "current_time", "private-connection"],
            "skillIds": ["group-intake", "my-private-skill"],
            "skillVersions": {"group-intake": 1, "my-private-skill": 3},
            "alwaysAllowedToolIds": ["browser"],
            "resourceAccess": {"private-connection": ["reviewed-resource"]},
        }

    def _recipe(self, _user_id: str, value: dict, *, previous: dict) -> dict:
        return {
            "toolIds": value["toolIds"], "extraToolIds": value["toolIds"],
            "skillIds": value["skillIds"], "skillVersions": {
                skill_id: previous["skillVersions"].get(skill_id, 1)
                for skill_id in value["skillIds"]
            },
            "alwaysAllowedToolIds": previous["alwaysAllowedToolIds"],
        }

    def test_additive_upgrade_preserves_custom_recipe_and_later_removals(self) -> None:
        builder = Mock(side_effect=self._recipe)
        with (
            patch.object(self.defaults.catalog, "get_bot_template", return_value=self.template),
            patch.object(self.defaults.table, "update_item") as update,
        ):
            upgraded = self.defaults.upgrade_chief_defaults("user-1", self.chief, builder)
            opted_out = {**upgraded, "toolIds": ["current_time"], "skillIds": []}
            self.assertEqual(self.defaults.upgrade_chief_defaults("user-1", opted_out, builder), opted_out)
        self.assertEqual(upgraded["templateVersion"], 9)
        self.assertEqual(set(upgraded["toolIds"]), set(self.template["toolIds"]) | {"private-connection"})
        self.assertEqual(set(upgraded["skillIds"]), set(self.template["skillIds"]) | {"my-private-skill"})
        self.assertEqual(upgraded["skillVersions"]["my-private-skill"], 3)
        for key in ("name", "prompt", "modelPreference", "actionApprovalMode", "alwaysAllowedToolIds", "resourceAccess"):
            self.assertEqual(upgraded[key], self.chief[key])
        builder.assert_called_once()
        self.assertEqual(set(builder.call_args.args[1]), {"toolIds", "skillIds"})
        update.assert_called_once()
        condition = update.call_args.kwargs["ConditionExpression"]
        for field in ("toolIds", "skillVersions", "actionApprovalMode", "resourceAccess"):
            self.assertIn(f"{field} = :old_{field}", condition)

    def test_bootstrap_upgrades_existing_chief_without_replacing_other_bots(self) -> None:
        teammate = {"id": "research", "name": "Research"}
        with (
            patch.object(self.defaults.catalog, "get_bot_template", return_value=self.template),
            patch.object(self.defaults.table, "update_item"),
            patch.object(self.bots, "_bot_values", side_effect=self._recipe),
        ):
            bots = self.bots._ensure_chief("user-1", [teammate, self.chief])
        self.assertEqual(bots[0]["id"], "chief")
        self.assertEqual(bots[0]["templateVersion"], 9)
        self.assertEqual(bots[1], teammate)

    def test_unpublished_defaults_and_concurrent_edits_leave_saved_recipe_unchanged(self) -> None:
        for response in (CatalogError("not published"), {**self.template, "version": 8}):
            with (
                patch.object(self.defaults.catalog, "get_bot_template", side_effect=response if isinstance(response, Exception) else None, return_value=response),
                patch.object(self.defaults.table, "update_item") as update,
            ):
                self.assertEqual(self.defaults.upgrade_chief_defaults("user-1", self.chief, Mock()), self.chief)
                update.assert_not_called()
        with (
            patch.object(self.defaults.catalog, "get_bot_template", return_value=self.template),
            patch.object(self.defaults.table, "update_item", side_effect=self.defaults.table.meta.client.exceptions.ConditionalCheckFailedException),
        ):
            self.assertEqual(self.defaults.upgrade_chief_defaults("user-1", self.chief, self._recipe), self.chief)

    def test_custom_incompatible_or_over_limit_recipes_are_preserved(self) -> None:
        for chief in (
            {**self.chief, "toolIds": [*self.chief["toolIds"], "delegate"]},
            {**self.chief, "extraToolIds": ["private-one", "private-two"]},
            {**self.chief, "skillIds": [f"private-{index}" for index in range(4)]},
        ):
            with (
                patch.object(self.defaults.catalog, "get_bot_template", return_value=self.template),
                patch.object(self.defaults.table, "update_item") as update,
            ):
                self.assertEqual(self.defaults.upgrade_chief_defaults("user-1", chief, Mock()), chief)
                update.assert_not_called()

    def test_new_skill_cannot_add_an_unassigned_external_account(self) -> None:
        def unexpected_grant(*args, **kwargs):
            return {**self._recipe(*args, **kwargs), "toolIds": ["new-private-account"]}

        with (
            patch.object(self.defaults.catalog, "get_bot_template", return_value=self.template),
            patch.object(self.defaults.table, "update_item") as update,
        ):
            self.assertEqual(self.defaults.upgrade_chief_defaults("user-1", self.chief, unexpected_grant), self.chief)
            update.assert_not_called()
