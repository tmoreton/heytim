from __future__ import annotations

import unittest

from shared.group_chat import (
    group_history_from_items,
    group_round_step,
    group_runtime_context,
    plan_group_reply_round,
    select_group_reply_targets,
)


class GroupChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [
            {"sk": "META", "entity": "GROUP", "name": "Launch room"},
            {"sk": "USER#1", "entity": "GROUP_USER", "name": "Taylor", "role": "owner"},
            {
                "sk": "BOT#research",
                "entity": "GROUP_BOT",
                "botId": "research",
                "name": "Research Scout",
                "tagline": "Finds evidence.",
            },
            {
                "sk": "BOT#chief",
                "entity": "GROUP_BOT",
                "botId": "chief",
                "name": "Chief",
                "tagline": "Connects the dots.",
            },
        ]

    def test_all_bots_reply_in_stable_name_order(self) -> None:
        targets = select_group_reply_targets(self.items, "all")
        self.assertEqual([target["botId"] for target in targets], ["chief", "research"])

    def test_context_identifies_people_bots_and_current_turn(self) -> None:
        context = group_runtime_context(self.items[0], self.items, "research", 2, 2)
        self.assertEqual(context["name"], "Launch room")
        self.assertEqual(context["people"], [{"name": "Taylor", "role": "owner"}])
        self.assertEqual(
            context["round"],
            {
                "position": 2,
                "size": 2,
                "role": "solo",
                "coordinatorName": "Research Scout",
            },
        )
        self.assertEqual(
            [bot["name"] for bot in context["bots"]], ["Chief", "Research Scout"]
        )
        self.assertEqual([bot["isCurrent"] for bot in context["bots"]], [False, True])

    def test_round_advances_one_bot_at_a_time(self) -> None:
        replies = [{"botId": "chief"}, {"botId": "research"}]
        first, first_is_final = group_round_step(replies, 0)
        second, second_is_final = group_round_step(replies, 1)
        self.assertEqual(first["botId"], "chief")
        self.assertFalse(first_is_final)
        self.assertEqual(second["botId"], "research")
        self.assertTrue(second_is_final)

    def test_team_round_returns_to_coordinator_for_final_answer(self) -> None:
        bots = select_group_reply_targets(self.items, "all")
        replies = plan_group_reply_round(bots, coordinated=True)
        self.assertEqual(
            [(reply["botId"], reply["roundRole"]) for reply in replies],
            [
                ("chief", "lead"),
                ("research", "contributor"),
                ("chief", "synthesizer"),
            ],
        )

    def test_single_bot_round_stays_single(self) -> None:
        bots = select_group_reply_targets(self.items, "research")
        replies = plan_group_reply_round(bots, coordinated=False)
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["roundRole"], "solo")

    def test_later_bot_sees_people_and_earlier_bot_replies(self) -> None:
        transcript = [
            {
                "sk": "MESSAGE#1#00#user",
                "status": "COMPLETE",
                "authorType": "user",
                "authorId": "1",
                "authorName": "Taylor",
                "text": "Make a launch plan.",
            },
            {
                "sk": "MESSAGE#1#01#chief",
                "status": "COMPLETE",
                "authorType": "bot",
                "authorId": "chief",
                "authorName": "Chief",
                "text": "First, choose an owner.",
            },
            {
                "sk": "MESSAGE#1#02#research",
                "status": "PENDING",
                "authorType": "bot",
                "authorId": "research",
                "authorName": "Research Scout",
                "text": "",
            },
        ]
        history = group_history_from_items(transcript, "research")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["role"], "user")
        self.assertIn("[Taylor]: Make a launch plan.", history[0]["content"][0]["text"])
        self.assertIn(
            "[Chief]: First, choose an owner.", history[0]["content"][0]["text"]
        )


if __name__ == "__main__":
    unittest.main()
