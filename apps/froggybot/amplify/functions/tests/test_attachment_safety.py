from __future__ import annotations

from unittest.mock import patch

from api_test_case import ApiTestCase


class AttachmentSafetyTests(ApiTestCase):
    def test_upload_ticket_is_scoped_and_size_limited(self) -> None:
        self.s3.generate_presigned_post.return_value = {
            "url": "https://uploads.example",
            "fields": {"key": "value"},
        }

        result = self.attachments._create_upload(
            "user-1", {"filename": "quarterly report.pdf", "size": 125_000}
        )

        self.assertEqual(result["file"]["contentType"], "application/pdf")
        request = self.s3.generate_presigned_post.call_args.kwargs
        self.assertTrue(request["Key"].startswith("users/"))
        self.assertNotIn("user-1", request["Key"])
        self.assertIn(["content-length-range", 1, 4_500_000], request["Conditions"])

    def test_group_memory_is_owner_editable_and_bounded(self) -> None:
        meta = {
            "pk": "GROUP#group-1",
            "sk": "META",
            "entity": "GROUP",
            "id": "group-1",
            "name": "Trip",
            "ownerId": "user-1",
            "createdAt": "now",
            "updatedAt": "now",
        }
        with (
            patch.object(
                self.groups, "_require_group_member", return_value=(meta, [meta])
            ) as require,
            patch.object(
                self.groups,
                "_public_group",
                return_value={"id": "group-1", "memory": "Budget: $1,200"},
            ),
        ):
            result = self.groups._update_group(
                "user-1",
                "group-1",
                {"memory": "Budget: $1,200", "botIds": []},
            )

        require.assert_called_once_with("user-1", "group-1", owner=True)
        self.assertEqual(result["memory"], "Budget: $1,200")
        self.assertEqual(self.data_table.put[-1]["memory"], "Budget: $1,200")

        with (
            patch.object(
                self.groups, "_require_group_member", return_value=(meta, [meta])
            ),
            self.assertRaises(self.support.ApiError) as error,
        ):
            self.groups._update_group(
                "user-1",
                "group-1",
                {"memory": "x" * 4_001, "botIds": []},
            )

        self.assertEqual(error.exception.status_code, 400)

    def test_group_file_download_checks_current_membership(self) -> None:
        file_id = "12345678-1234-1234-1234-123456789012"
        self.data_table.items[("GROUP#group-1", "USER#user-1")] = {
            "pk": "GROUP#group-1",
            "sk": "USER#user-1",
            "entity": "GROUP_USER",
        }
        self.data_table.items[("GROUP#group-1", f"FILE#{file_id}")] = {
            "pk": "GROUP#group-1",
            "sk": f"FILE#{file_id}",
            "entity": "FILE",
            "id": file_id,
            "status": "READY",
            "name": "weekend.pdf",
            "contentType": "application/pdf",
            "objectKey": "groups/group-1/artifacts/reply-1/weekend.pdf",
        }
        self.s3.generate_presigned_url.return_value = "https://download.example"

        result = self.attachments._download_group_file("user-1", "group-1", file_id)

        self.assertEqual(result["url"], "https://download.example")
        with self.assertRaises(self.support.ApiError):
            self.attachments._download_group_file("outsider", "group-1", file_id)

    def test_group_message_copies_caller_upload_into_the_room(self) -> None:
        group_id = "12345678-1234-1234-1234-123456789012"
        file_id = "87654321-4321-4321-4321-210987654321"
        source = {
            "pk": "USER#user-1",
            "sk": f"FILE#{file_id}",
            "entity": "FILE",
            "id": file_id,
            "status": "READY",
            "name": "constraints.pdf",
            "size": 120_000,
            "kind": "document",
            "format": "pdf",
            "contentType": "application/pdf",
            "createdAt": "now",
            "objectKey": f"users/{'a' * 64}/uploads/{file_id}.pdf",
        }
        self.data_table.items[(source["pk"], source["sk"])] = source
        meta = {
            "pk": f"GROUP#{group_id}",
            "sk": "META",
            "entity": "GROUP",
            "id": group_id,
            "name": "Trip",
        }

        with patch.object(
            self.group_messages,
            "_require_group_member",
            return_value=(meta, [meta]),
        ):
            result = self.group_messages._send_group_message(
                "user-1",
                "Taylor",
                group_id,
                {"text": "", "attachmentIds": [file_id]},
            )

        self.assertIsNone(result["replyId"])
        copied = self.data_table.items[(f"GROUP#{group_id}", f"FILE#{file_id}")]
        self.assertEqual(
            copied["objectKey"], f"groups/{group_id}/uploads/{file_id}.pdf"
        )
        message = next(
            item for item in self.data_table.put if item.get("entity") == "GROUP_MESSAGE"
        )
        self.assertEqual(message["text"], "Please review the attached files.")
        self.assertEqual(message["attachments"][0]["id"], file_id)
        self.s3.copy_object.assert_called_once()

    def test_oversized_image_upload_is_rejected_before_signing(self) -> None:
        with self.assertRaises(self.support.ApiError) as error:
            self.attachments._create_upload(
                "user-1", {"filename": "photo.png", "size": 3_750_001}
            )

        self.assertEqual(error.exception.status_code, 400)
        self.s3.generate_presigned_post.assert_not_called()

    def test_account_file_cleanup_deletes_all_object_versions(self) -> None:
        page = {
            "Versions": [{"Key": "users/actor/file.pdf", "VersionId": "one"}],
            "DeleteMarkers": [
                {"Key": "users/actor/file.pdf", "VersionId": "deleted"}
            ],
            "IsTruncated": False,
        }
        self.s3.get_paginator.return_value.paginate.return_value = [page]
        self.s3.delete_objects.return_value = {}
        with patch.object(self.account, "memory_actor_id", return_value="actor"):
            deleted = self.account._delete_user_files("user-1")

        self.assertEqual(deleted, 2)
        objects = self.s3.delete_objects.call_args.kwargs["Delete"]["Objects"]
        self.assertEqual({item["VersionId"] for item in objects}, {"one", "deleted"})
