from __future__ import annotations

import unittest
from unittest.mock import patch

from api_test_case import ApiTestCase
from shared.action_grants import (
    action_approval_mode,
    effective_allowed_interactive_tool_ids,
)


class ActionApprovalPolicyTests(unittest.TestCase):
    def test_legacy_bot_defaults_to_automatic_actions(self) -> None:
        bot = {"toolIds": ["browser", "web"], "alwaysAllowedToolIds": []}

        self.assertEqual(action_approval_mode(bot), "automatic")
        self.assertEqual(
            effective_allowed_interactive_tool_ids(bot),
            ["browser", "web"],
        )

    def test_ask_mode_uses_only_explicit_grants(self) -> None:
        bot = {
            "toolIds": ["browser", "home"],
            "actionApprovalMode": "ask",
            "alwaysAllowedToolIds": ["home"],
        }

        self.assertEqual(action_approval_mode(bot), "ask")
        self.assertEqual(
            effective_allowed_interactive_tool_ids(bot),
            ["home"],
        )


class BotActionApprovalApiTests(ApiTestCase):
    @staticmethod
    def _home_bot(**updates) -> dict:
        bot = {
            "name": "Home Bot",
            "tagline": "Controls the house",
            "prompt": "Help control my Home Assistant devices.",
            "color": "#FFAA34",
            "toolIds": ["home"],
            "extraToolIds": ["home"],
            "alwaysAllowedToolIds": [],
            "skillIds": [],
            "skillVersions": {},
        }
        bot.update(updates)
        return bot

    def _bot_values(self, body: dict, previous: dict) -> dict:
        with (
            patch.object(self.bots.catalog, "sync_official"),
            patch.object(self.bots.catalog, "validate_and_pin", return_value={}),
            patch.object(
                self.bots.catalog,
                "validate_tools",
                side_effect=lambda _user, ids: list(ids),
            ),
            patch.object(
                self.bots.catalog,
                "available_tool_ids",
                side_effect=lambda _user, ids: list(ids),
            ),
            patch.object(
                self.bots.catalog, "approval_tool_ids", return_value=["home"]
            ),
        ):
            return self.bots._bot_values("user-1", body, previous)

    def test_ask_mode_cannot_grant_unapproved_tools(self) -> None:
        values = self._bot_values(
            {"actionApprovalMode": "ask", "alwaysAllowedToolIds": ["home"]},
            self._home_bot(actionApprovalMode="ask"),
        )

        self.assertEqual(values["alwaysAllowedToolIds"], [])

    def test_automatic_mode_allows_enabled_interactive_tools(self) -> None:
        values = self._bot_values({}, self._home_bot())

        self.assertEqual(values["actionApprovalMode"], "automatic")
        self.assertEqual(values["alwaysAllowedToolIds"], ["home"])

    def test_switching_to_ask_mode_clears_automatic_grants(self) -> None:
        previous = self._home_bot(
            actionApprovalMode="automatic", alwaysAllowedToolIds=["home"]
        )
        values = self._bot_values({"actionApprovalMode": "ask"}, previous)

        self.assertEqual(values["actionApprovalMode"], "ask")
        self.assertEqual(values["alwaysAllowedToolIds"], [])

    def test_public_legacy_bot_defaults_to_automatic_actions(self) -> None:
        bot = self.support._public_bot(
            {"id": "bot-1", "name": "Legacy bot", "color": "#58BEAA"}
        )

        self.assertEqual(bot["actionApprovalMode"], "automatic")


if __name__ == "__main__":
    unittest.main()
