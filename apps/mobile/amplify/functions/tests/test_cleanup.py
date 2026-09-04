from __future__ import annotations

import unittest

from shared.cleanup import group_invite_records, group_member_ids, has_pending_work


class CleanupTests(unittest.TestCase):
    def test_pending_work_can_be_limited_to_one_bot(self) -> None:
        items = [
            {"status": "COMPLETE", "authorId": "chief"},
            {"status": "PENDING", "authorId": "research"},
        ]
        self.assertTrue(has_pending_work(items))
        self.assertTrue(has_pending_work(items, bot_id="research"))
        self.assertFalse(has_pending_work(items, bot_id="chief"))

    def test_cleanup_metadata_ignores_unrelated_items(self) -> None:
        items = [
            {"entity": "GROUP_USER", "userId": "owner"},
            {"entity": "GROUP_USER", "userId": 42},
            {
                "entity": "GROUP_INVITE_POINTER",
                "token": "invite-token",
                "tokenHash": "invite-hash",
            },
            {"entity": "GROUP_MESSAGE", "token": "not-an-invite"},
        ]
        self.assertEqual(group_member_ids(items), ["owner"])
        self.assertEqual(group_invite_records(items), [("invite-token", "invite-hash")])


if __name__ == "__main__":
    unittest.main()
