from __future__ import annotations

from unittest.mock import patch

from api_test_case import ApiTestCase


class GroupDecisionTests(ApiTestCase):
    def test_group_items_include_paginated_decisions(self) -> None:
        group_id = "group-1"
        meta = {"pk": "GROUP#group-1", "sk": "META", "entity": "GROUP"}
        self.data_table.items[(meta["pk"], meta["sk"])] = meta
        with patch.object(
            self.data_table,
            "query",
            side_effect=[
                {"Items": []},
                {"Items": []},
                {
                    "Items": [{"sk": "DECISION#1"}],
                    "LastEvaluatedKey": {"pk": meta["pk"], "sk": "DECISION#1"},
                },
                {"Items": [{"sk": "DECISION#2"}]},
            ],
            create=True,
        ) as query:
            items = self.groups._group_items(group_id)
        self.assertEqual([item["sk"] for item in items], ["META", "DECISION#1", "DECISION#2"])
        self.assertEqual(
            query.call_args_list[3].kwargs["ExclusiveStartKey"],
            {"pk": meta["pk"], "sk": "DECISION#1"},
        )

    def test_completed_bot_answer_can_be_saved_once(self) -> None:
        group_id = "group-1"
        meta = {"entity": "GROUP", "ownerId": "owner"}
        member = {"entity": "GROUP_USER", "sk": "USER#user-1"}
        source = {
            "entity": "GROUP_MESSAGE",
            "id": "message-1",
            "authorType": "bot",
            "authorName": "Chief",
            "status": "COMPLETE",
            "text": "Choose Portland because it meets every fixed constraint.",
        }
        with (
            patch.object(
                self.groups,
                "_require_group_member",
                return_value=(meta, [meta, member]),
            ),
            patch.object(self.groups, "_partition_items", return_value=[source]),
        ):
            saved = self.groups._save_group_decision(
                "user-1", "Taylor", group_id, {"messageId": "message-1"}
            )

        self.assertEqual(saved["sourceAuthorName"], "Chief")
        self.assertEqual(saved["createdByName"], "Taylor")
        self.assertEqual(self.data_table.put[-1]["entity"], "GROUP_DECISION")

        existing = self.data_table.put[-1]
        with patch.object(
            self.groups,
            "_require_group_member",
            return_value=(meta, [meta, member, existing]),
        ):
            repeated = self.groups._save_group_decision(
                "user-1", "Taylor", group_id, {"messageId": "message-1"}
            )
        self.assertEqual(repeated["id"], saved["id"])

    def test_people_messages_cannot_be_saved_as_decisions(self) -> None:
        source = {
            "id": "message-1",
            "authorType": "user",
            "status": "COMPLETE",
            "text": "My preference",
        }
        with (
            patch.object(
                self.groups,
                "_require_group_member",
                return_value=({"ownerId": "user-1"}, []),
            ),
            patch.object(self.groups, "_partition_items", return_value=[source]),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.groups._save_group_decision(
                "user-1", "Taylor", "group-1", {"messageId": "message-1"}
            )

        self.assertEqual(error.exception.status_code, 400)

    def test_intermediate_team_replies_cannot_be_saved_as_decisions(self) -> None:
        source = {
            "id": "message-1",
            "authorType": "bot",
            "status": "COMPLETE",
            "roundRole": "contributor",
            "text": "Intermediate research",
        }
        with (
            patch.object(
                self.groups,
                "_require_group_member",
                return_value=({"ownerId": "user-1"}, []),
            ),
            patch.object(self.groups, "_partition_items", return_value=[source]),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.groups._save_group_decision(
                "user-1", "Taylor", "group-1", {"messageId": "message-1"}
            )

        self.assertEqual(error.exception.status_code, 400)

    def test_only_saver_or_room_owner_can_remove_a_decision(self) -> None:
        key = ("GROUP#group-1", "DECISION#decision-1")
        self.data_table.items[key] = {
            "pk": key[0],
            "sk": key[1],
            "entity": "GROUP_DECISION",
            "createdById": "user-1",
        }
        with patch.object(
            self.groups,
            "_require_group_member",
            return_value=({"ownerId": "owner"}, []),
        ):
            result = self.groups._delete_group_decision(
                "user-1", "group-1", "decision-1"
            )
        self.assertTrue(result["deleted"])

        self.data_table.items[key] = {
            "pk": key[0],
            "sk": key[1],
            "entity": "GROUP_DECISION",
            "createdById": "someone-else",
        }
        with (
            patch.object(
                self.groups,
                "_require_group_member",
                return_value=({"ownerId": "owner"}, []),
            ),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.groups._delete_group_decision(
                "user-1", "group-1", "decision-1"
            )
        self.assertEqual(error.exception.status_code, 403)
