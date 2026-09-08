from __future__ import annotations

from unittest.mock import patch

from api_test_case import ApiTestCase


class InviteAuthorityTests(ApiTestCase):
    def test_invite_grant_is_revoked_before_metadata_cleanup(self) -> None:
        token = "secret-token"
        access = {
            "tokenHash": self.support.invite_token_hash(token),
            "kind": "bot",
            "targetId": "bot-1",
            "expiresAt": 9_999_999_999,
        }
        self.invite_table.put_item(Item=access)
        share = {
            "pk": f"SHARE#{token}",
            "sk": "META",
            "entity": "SHARE",
            "ownerId": "user-1",
        }

        with (
            patch.object(
                self.data_table,
                "batch_writer",
                side_effect=RuntimeError("metadata cleanup failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "metadata cleanup failed"),
        ):
            self.support._delete_share_record("user-1", share)

        self.assertNotIn(
            ("tokenHash", self.support.invite_token_hash(token)),
            self.invite_table.items,
        )
