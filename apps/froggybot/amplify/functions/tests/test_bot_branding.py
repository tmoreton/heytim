from __future__ import annotations

import unittest
from unittest.mock import patch

import test_api_safety


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
        self.assertTrue(result["needsBotOnboarding"])


if __name__ == "__main__":
    unittest.main()
