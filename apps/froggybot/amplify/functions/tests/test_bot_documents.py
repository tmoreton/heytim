from __future__ import annotations

from unittest.mock import patch

from api_test_case import ApiTestCase


class BotDocumentTests(ApiTestCase):
    def test_bot_deletion_purges_documents_before_removing_the_bot(self) -> None:
        turns = [
            {
                "pk": "CHAT#user-1#bot-1",
                "sk": "TURN#now#turn-1",
                "status": "COMPLETE",
            }
        ]
        with (
            patch.object(self.bots, "_get_bot", return_value={"id": "bot-1"}),
            patch.object(self.bots, "_partition_items", side_effect=[turns, []]),
            patch.object(self.bots, "_schedule_items", return_value=[]),
            patch.object(self.bots, "_revoke_bot_shares", return_value=0),
            patch.object(
                self.bots,
                "_delete_bot_documents",
                return_value={
                    "deletedDocuments": 2,
                    "deletedDocumentVersions": 3,
                },
            ) as delete_documents,
        ):
            result = self.bots._delete_bot("user-1", "bot-1")

        delete_documents.assert_called_once_with("user-1", "bot-1", turns)
        self.assertEqual(result["deletedDocuments"], 2)
        self.assertIn({"pk": "USER#user-1", "sk": "BOT#bot-1"}, self.data_table.deleted)

    def test_listing_associates_legacy_turn_artifacts_with_the_bot(self) -> None:
        current = {
            "pk": "USER#user-1",
            "sk": "FILE#current",
            "entity": "FILE",
            "id": "current",
            "status": "READY",
            "source": "generated",
            "botId": "bot-1",
            "objectKey": ("users/actor/bots/bot-1/artifacts/turn/current--brief.pdf"),
            "name": "brief.pdf",
            "size": 100,
            "kind": "document",
            "format": "pdf",
            "contentType": "application/pdf",
            "createdAt": "2026-09-07T12:00:00Z",
        }
        legacy = {
            "pk": "USER#user-1",
            "sk": "FILE#legacy",
            "entity": "FILE",
            "id": "legacy",
            "status": "READY",
            "source": "generated",
            "objectKey": "users/actor/artifacts/turn/legacy--notes.docx",
            "name": "notes.docx",
            "size": 200,
            "kind": "document",
            "format": "docx",
            "contentType": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            "createdAt": "2026-09-06T12:00:00Z",
        }
        turns = [{"artifacts": [legacy]}]
        with (
            patch.object(self.bot_documents, "memory_actor_id", return_value="actor"),
            patch.object(
                self.bot_documents,
                "_partition_items",
                side_effect=[[current, legacy], turns],
            ),
        ):
            documents = self.bot_documents._list_bot_documents("user-1", "bot-1")

        self.assertEqual([item["id"] for item in documents], ["current", "legacy"])
        self.assertEqual(
            self.data_table.updated[-1]["ExpressionAttributeValues"][":bot"],
            "bot-1",
        )

    def test_deleting_removes_all_s3_versions_and_file_records(self) -> None:
        document = {
            "pk": "USER#user-1",
            "sk": "FILE#legacy",
            "id": "legacy",
            "objectKey": "users/actor/artifacts/turn/legacy--notes.pdf",
        }
        current_key = "users/actor/bots/bot-1/artifacts/turn/new.pdf"
        paginator = self.s3.get_paginator.return_value
        paginator.paginate.side_effect = [
            [
                {
                    "Versions": [{"Key": current_key, "VersionId": "v1"}],
                    "DeleteMarkers": [{"Key": current_key, "VersionId": "v2"}],
                }
            ],
            [
                {
                    "Versions": [
                        {"Key": document["objectKey"], "VersionId": "legacy-v1"},
                        {
                            "Key": f"{document['objectKey']}.other",
                            "VersionId": "other",
                        },
                    ]
                }
            ],
        ]
        self.s3.delete_objects.return_value = {}
        with (
            patch.object(self.bot_documents, "memory_actor_id", return_value="actor"),
            patch.object(
                self.bot_documents, "_owned_documents", return_value=[document]
            ),
        ):
            result = self.bot_documents._delete_bot_documents("user-1", "bot-1", [])

        self.assertEqual(result["deletedDocuments"], 1)
        self.assertEqual(result["deletedDocumentVersions"], 3)
        deleted = self.s3.delete_objects.call_args.kwargs["Delete"]["Objects"]
        self.assertEqual(
            {item["VersionId"] for item in deleted},
            {"v1", "v2", "legacy-v1"},
        )
        self.assertIn(
            {"pk": "USER#user-1", "sk": "FILE#legacy"}, self.data_table.deleted
        )
