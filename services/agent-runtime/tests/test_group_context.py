from __future__ import annotations

import unittest

from group_context import collaboration_instructions


class GroupContextTests(unittest.TestCase):
    def test_rejects_unknown_contract_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "schemaVersion"):
            collaboration_instructions({"schemaVersion": 2})

    def test_instructions_explain_roster_and_contributor_role(self) -> None:
        instructions = collaboration_instructions(
            {
                "name": "Launch room",
                "memory": "Launch Friday and keep the budget under $5,000.",
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
                "round": {
                    "position": 2,
                    "size": 3,
                    "role": "contributor",
                    "coordinatorName": "Chief",
                },
            }
        )
        self.assertIn('"name":"Chief"', instructions)
        self.assertIn('"name":"Research Scout"', instructions)
        self.assertIn("answer directly from GROUP_ROSTER", instructions)
        self.assertIn("reply 2 of 3", instructions)
        self.assertIn("Chief is coordinating this round", instructions)
        self.assertIn("Do not restart the task", instructions)
        self.assertIn(
            '"sharedMemory":"Launch Friday and keep the budget under $5,000."',
            instructions,
        )
        self.assertIn("group owner controls sharedMemory", instructions)

    def test_synthesizer_must_return_one_final_team_answer(self) -> None:
        instructions = collaboration_instructions(
            {
                "name": "Launch room",
                "people": [{"name": "Taylor", "role": "owner"}],
                "bots": [
                    {
                        "name": "Chief",
                        "tagline": "Connects the dots.",
                        "isCurrent": True,
                    },
                    {
                        "name": "Research Scout",
                        "tagline": "Finds evidence.",
                        "isCurrent": False,
                    },
                ],
                "round": {
                    "position": 3,
                    "size": 3,
                    "role": "synthesizer",
                    "coordinatorName": "Chief",
                },
            }
        )
        self.assertIn("Produce one final, self-contained team answer", instructions)
        self.assertIn("returning after the other bots contributed", instructions)


if __name__ == "__main__":
    unittest.main()
