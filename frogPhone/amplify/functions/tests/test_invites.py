from __future__ import annotations

import unittest

from shared.invites import invite_token_hash, invite_url


class InviteTests(unittest.TestCase):
    def test_invite_url_uses_one_universal_web_route(self) -> None:
        self.assertEqual(
            invite_url("https://frogbot.expo.app/", "group", "safe_token"),
            "https://frogbot.expo.app/invite?kind=group&token=safe_token",
        )

    def test_invite_hash_does_not_store_the_bearer_token(self) -> None:
        self.assertEqual(len(invite_token_hash("secret-token")), 64)
        self.assertNotIn("secret-token", invite_token_hash("secret-token"))


if __name__ == "__main__":
    unittest.main()
