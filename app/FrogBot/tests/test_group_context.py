from __future__ import annotations

import unittest

from group_context import collaboration_instructions


class GroupContextTests(unittest.TestCase):
    def test_instructions_explain_roster_and_bounded_collaboration(self) -> None:
        instructions = collaboration_instructions(
            {
                "name": "Launch room",
                "people": [{"name": "Taylor", "role": "owner"}],
                "bots": [
                    {
                        "name": "Chief",
                        "tagline": "Connects the dots.",
                        "isCurrent": False,
                    },
                    {
                        "name": "Research Scout",
                        "tagline": "Finds evidence.",
                        "isCurrent": True,
                    },
                ],
                "round": {"position": 2, "size": 2},
            }
        )
        self.assertIn('"name":"Chief"', instructions)
        self.assertIn('"name":"Research Scout"', instructions)
        self.assertIn("answer directly from GROUP_ROSTER", instructions)
        self.assertIn("reply 2 of 2", instructions)
        self.assertIn("bounded single pass", instructions)


if __name__ == "__main__":
    unittest.main()
