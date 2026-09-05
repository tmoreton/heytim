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
                    "lastMessageAt": "2026-09-01T20:00:00Z",
                },
            ],
        )

        self.assertEqual(ordered[0]["id"], "chief")


if __name__ == "__main__":
    unittest.main()
