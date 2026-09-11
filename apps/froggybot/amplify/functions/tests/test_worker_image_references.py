from __future__ import annotations

from unittest.mock import patch

from worker_test_case import WorkerTestCase


class WorkerImageReferenceTests(WorkerTestCase):
    def test_recent_image_references_reuse_same_chat_uploads_safely(self) -> None:
        self.table.items[("CHAT#user-1#bot-1", "TURN#2026-09-11#new")] = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#2026-09-11#new",
            "attachments": [],
        }
        self.table.items[("CHAT#user-1#bot-1", "TURN#2026-09-09#old")] = {
            "pk": "CHAT#user-1#bot-1",
            "sk": "TURN#2026-09-09#old",
            "attachments": [
                {
                    "id": "logo-1",
                    "name": "Codex logo.png",
                    "kind": "image",
                    "format": "png",
                    "objectKey": "users/actor-1/uploads/logo.png",
                },
                {
                    "id": "document-1",
                    "name": "notes.pdf",
                    "kind": "document",
                    "format": "pdf",
                    "objectKey": "users/actor-1/uploads/notes.pdf",
                },
            ],
        }

        with patch.object(self.artifacts, "memory_actor_id", return_value="actor-1"):
            references = self.agent._recent_image_references("user-1", "bot-1")

        self.assertEqual(
            references,
            [
                {
                    "name": "Codex logo.png",
                    "image": {
                        "format": "png",
                        "source": {
                            "s3Location": {
                                "uri": "s3://frogbot-user-files-123-us-east-1/users/actor-1/uploads/logo.png"
                            }
                        },
                    },
                }
            ],
        )
