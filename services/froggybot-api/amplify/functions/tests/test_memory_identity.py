from __future__ import annotations

import unittest

from shared.memory_identity import (
    direct_session_id,
    group_memory_actor_id,
    group_memory_session_id,
    memory_actor_id,
    scoped_session_id,
)


class MemoryIdentityTests(unittest.TestCase):
    def test_actor_and_session_ids_are_stable_non_pii_hashes(self) -> None:
        actor = memory_actor_id("person@example.com")
        session = direct_session_id("person@example.com", "bot-1")

        self.assertEqual(actor, memory_actor_id("person@example.com"))
        self.assertEqual(session, direct_session_id("person@example.com", "bot-1"))
        self.assertEqual(len(actor), 64)
        self.assertEqual(len(session), 64)
        self.assertNotIn("person", actor)
        self.assertNotEqual(session, scoped_session_id("group:group-1:bot:bot-1"))

    def test_group_memory_is_shared_by_the_group_but_isolated_from_people(self) -> None:
        actor = group_memory_actor_id("group-1")

        self.assertEqual(actor, group_memory_actor_id("group-1"))
        self.assertNotEqual(actor, group_memory_actor_id("group-2"))
        self.assertNotEqual(actor, memory_actor_id("group-1"))
        self.assertNotEqual(actor, group_memory_session_id("group-1"))


if __name__ == "__main__":
    unittest.main()
