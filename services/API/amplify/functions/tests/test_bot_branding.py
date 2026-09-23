from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

import test_api_safety
from shared.catalog import CatalogError


class BotBrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        base = test_api_safety.ApiSafetyTests
        if not hasattr(base, "bots"):
            base.setUpClass()
        cls.bots = base.bots
        cls.support = base.support

    def test_chief_is_green_and_other_bots_cannot_use_brand_green(self) -> None:
        chief = self.support._public_bot({"color": "#FFAA34", "systemRole": "chief"})
        other = self.support._public_bot({"color": self.support.CHIEF_COLOR})

        self.assertEqual(chief["color"], self.support.CHIEF_COLOR)
        self.assertEqual(other["color"], self.support.DEFAULT_BOT_COLOR)

        with (
            patch.object(self.bots.catalog, "sync_official"),
            self.assertRaises(self.support.ApiError) as raised,
        ):
            self.bots._bot_values(
                "user-1",
                {
                    "name": "Researcher",
                    "prompt": "Research carefully.",
                    "color": self.support.CHIEF_COLOR,
                },
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_chief_is_first_even_when_another_bot_is_more_recent(self) -> None:
        ordered = self.bots._ensure_chief(
            "user-1",
            [
                {
                    "id": "newer",
                    "name": "Researcher",
                    "color": "#FFAA34",
                    "lastMessageAt": "2026-09-05T20:00:00Z",
                },
                {
                    "id": "chief",
                    "name": "Chief",
                    "color": self.support.CHIEF_COLOR,
                    "systemRole": "chief",
                    "templateId": "chief",
                    "templateVersion": 1,
                    "lastMessageAt": "2026-09-01T20:00:00Z",
                },
            ],
        )

        self.assertEqual(ordered[0]["id"], "chief")

    def test_existing_chief_gets_skill_builder_once_without_losing_edits(self) -> None:
        chief = {
            "id": "chief",
            "name": "Chief",
            "prompt": "Keep my custom prompt.",
            "systemRole": "chief",
            "templateId": "chief",
            "templateVersion": Decimal(4),
            "skillIds": ["group-intake", "skill-personal"],
            "skillVersions": {"group-intake": 1, "skill-personal": 2},
        }
        with (
            patch.object(
                self.bots.catalog,
                "get_skill",
                return_value={"id": "skill-builder", "source": "official", "version": Decimal(1)},
            ),
            patch.object(self.bots.catalog, "get_version", return_value={"version": 1}),
            patch.object(self.bots.table, "update_item") as update,
        ):
            migrated = self.bots._ensure_chief("user-1", [chief])[0]
            opted_out = self.bots._ensure_chief(
                "user-1", [{**migrated, "skillIds": ["group-intake", "skill-personal"]}]
            )[0]

        self.assertEqual(migrated["prompt"], chief["prompt"])
        self.assertEqual(
            migrated["skillIds"],
            ["group-intake", "skill-personal", "skill-builder"],
        )
        self.assertEqual(migrated["skillVersions"]["skill-personal"], 2)
        self.assertEqual(migrated["skillVersions"]["skill-builder"], 1)
        self.assertEqual(migrated["templateVersion"], 5)
        self.assertEqual(opted_out["skillIds"], ["group-intake", "skill-personal"])
        update.assert_called_once()
        self.assertIn("skillIds = :previousSkillIds", update.call_args.kwargs["ConditionExpression"])

    def test_existing_chief_waits_for_skill_builder_publication(self) -> None:
        chief = {
            "id": "chief",
            "systemRole": "chief",
            "templateId": "chief",
            "templateVersion": 4,
            "skillIds": ["group-intake"],
            "skillVersions": {"group-intake": 1},
        }
        with (
            patch.object(
                self.bots.catalog,
                "get_skill",
                side_effect=CatalogError("Skill not found"),
            ),
            patch.object(self.bots.table, "update_item") as update,
        ):
            result = self.bots._ensure_chief("user-1", [chief])

        self.assertEqual(result[0]["skillIds"], ["group-intake"])
        update.assert_not_called()

    def test_existing_chief_receives_new_import_guidance_without_restoring_removed_skill(self) -> None:
        chief = {
            "id": "chief", "systemRole": "chief", "templateId": "chief",
            "templateVersion": 5, "skillIds": ["group-intake", "skill-builder"],
            "skillVersions": {"group-intake": 1, "skill-builder": 1},
        }
        with (
            patch.object(self.bots.catalog, "get_skill", return_value={
                "id": "skill-builder", "source": "official", "version": Decimal(2),
            }),
            patch.object(self.bots.catalog, "get_version", return_value={"version": 2}),
            patch.object(self.bots.table, "update_item") as update,
        ):
            refreshed = self.bots._ensure_chief("user-1", [chief])[0]
            opted_out = self.bots._ensure_chief(
                "user-1", [{**chief, "skillIds": ["group-intake"]}]
            )[0]
        self.assertEqual(refreshed["skillVersions"]["skill-builder"], 2)
        self.assertEqual(refreshed["templateVersion"], 6)
        self.assertEqual(opted_out["skillIds"], ["group-intake"])
        update.assert_called_once()

    def test_empty_signup_installs_chief_from_the_public_catalog(self) -> None:
        template = {
            "id": "chief",
            "version": 3,
            "name": "Chief",
            "tagline": "Coordinates the team.",
            "prompt": "Use this catalog prompt, not an app fallback.",
            "color": self.support.CHIEF_COLOR,
            "skillIds": ["group-intake"],
            "toolIds": ["current_time"],
        }
        with (
            patch.object(
                self.bots.catalog, "get_bot_template", return_value=template
            ) as get_template,
            patch.object(self.bots.catalog, "sync_official"),
            patch.object(
                self.bots.catalog,
                "validate_and_pin",
                side_effect=lambda _user, ids, _existing=None: {
                    skill_id: 1 for skill_id in ids
                },
            ),
            patch.object(
                self.bots.catalog,
                "get_version",
                return_value={"requiredToolIds": []},
            ),
            patch.object(
                self.bots.catalog,
                "validate_tools",
                side_effect=lambda _user, ids: list(dict.fromkeys(ids)),
            ),
            patch.object(self.bots.catalog, "approval_tool_ids", return_value=[]),
        ):
            seeded = self.bots._ensure_chief("new-user", [])

        get_template.assert_called_once_with("chief")
        self.assertEqual(
            [bot["id"] for bot in seeded],
            ["catalog-chief"],
        )
        self.assertEqual(seeded[0]["systemRole"], "chief")
        self.assertEqual(seeded[0]["templateId"], "chief")
        self.assertEqual(seeded[0]["templateVersion"], 3)
        self.assertEqual(seeded[0]["prompt"], template["prompt"])

    def test_legacy_starter_bot_is_linked_to_its_catalog_template(self) -> None:
        legacy = {
            "id": "starter-trip-planner",
            "name": "Trip Planner",
            "skillVersions": {},
            "extraToolIds": [],
        }
        with (
            patch.object(self.bots, "_list_bots", return_value=[legacy]),
            patch.object(self.bots, "_ensure_chief", return_value=[legacy]),
            patch.object(self.bots, "_list_groups", return_value=[]),
            patch.object(self.bots.catalog, "list_bot_templates", return_value=[]),
            patch.object(self.bots.catalog, "list_tools", return_value=[]),
            patch.object(self.bots.catalog, "list_skills", return_value=[]),
        ):
            self.bots.table.items[("USER#new-user", "STATE")] = {
                "pk": "USER#new-user",
                "sk": "STATE",
            }
            result = self.bots._bootstrap("new-user")

        self.assertEqual(result["bots"][0]["templateId"], "trip-planner")
        self.assertEqual(result["bots"][0]["templateVersion"], 1)

    def test_first_bootstrap_returns_chief_and_catalog_onboarding(self) -> None:
        chief = {
            "id": "catalog-chief",
            "systemRole": "chief",
            "templateId": "chief",
            "templateVersion": 1,
            "skillVersions": {},
            "extraToolIds": [],
        }
        templates = [{"id": "trip-planner", "version": 1}]
        with (
            patch.object(self.bots, "_list_bots", return_value=[]),
            patch.object(self.bots, "_ensure_chief", return_value=[chief]),
            patch.object(self.bots, "_list_groups", return_value=[]),
            patch.object(
                self.bots.catalog, "list_bot_templates", return_value=templates
            ),
            patch.object(self.bots.catalog, "list_tools", return_value=[]),
            patch.object(self.bots.catalog, "list_skills", return_value=[]),
        ):
            result = self.bots._bootstrap("brand-new-user")

        self.assertEqual(result["bots"], [chief])
        self.assertEqual(result["botTemplates"], templates)
        self.assertEqual(
            [provider["id"] for provider in result["connectionProviders"]],
            [
                "x",
                "youtube",
                "slack",
                "microsoft_teams",
                "github",
                "gmail",
                "google_workspace",
                "home_assistant",
                "hubspot",
                "jira",
                "mcp_server",
                "microsoft",
                "notion",
                "zoom",
            ],
        )
        provider = result["connectionProviders"][0]
        self.assertNotIn("clientSecret", provider)
        self.assertNotIn("authType", provider)
        self.assertNotIn("uiKind", provider)
        self.assertEqual(provider["connectLabel"], "Connect account")
        self.assertEqual(provider["reconnectLabel"], "Reconnect account")
        google = [
            provider
            for provider in result["connectionProviders"]
            if provider.get("familyId") == "google"
        ]
        self.assertEqual(
            [provider["serviceName"] for provider in google],
            ["Gmail", "Workspace"],
        )
        self.assertTrue(
            all(provider["familyName"] == "Google" for provider in google)
        )
        self.assertTrue(all("familyIncludedToolIds" not in provider for provider in google))
        x_provider = next(
            provider
            for provider in result["connectionProviders"]
            if provider["id"] == "x"
        )
        self.assertEqual(x_provider["serviceName"], "Account access")
        self.assertNotIn("familyIncludedSummary", x_provider)
        self.assertNotIn("familyIncludedToolIds", x_provider)
        self.assertTrue(result["needsBotOnboarding"])
        self.assertEqual(result["constraints"]["messageMaxLength"], 8_000)
        self.assertEqual(result["constraints"]["maxAttachmentsPerMessage"], 5)

    def test_unconfigured_provider_is_hidden_from_bootstrap(self) -> None:
        with patch.dict(
            "os.environ", {"DISABLED_CONNECTION_PROVIDER_IDS": "microsoft"}
        ):
            providers = self.bots.connection_providers()

        self.assertNotIn("microsoft", [provider["id"] for provider in providers])
        self.assertIn("slack", [provider["id"] for provider in providers])


if __name__ == "__main__":
    unittest.main()
