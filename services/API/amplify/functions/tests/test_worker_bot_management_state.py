from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from worker_test_case import WorkerTestCase


class WorkerBotManagementStateTests(WorkerTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.apply_bot_mutations = staticmethod(cls.direct_job.apply_bot_mutations)
        cls.bot_mutation_globals = cls.direct_job.apply_bot_mutations.__globals__

    def test_bot_can_create_a_replay_safe_personal_memory(self) -> None:
        mutation_id = str(uuid.uuid4())
        memory_api = SimpleNamespace(_create_user_memory=MagicMock())
        raw = [
            {
                "mutationId": mutation_id,
                "action": "create_memory",
                "value": {"kind": "fact", "content": "I live in Boston."},
            }
        ]

        with patch.dict(self.bot_mutation_globals, {"_memory_api": lambda: memory_api}):
            self.apply_bot_mutations("user-1", {"id": "writer"}, {}, raw)

        memory_api._create_user_memory.assert_called_once_with(
            "user-1",
            {"kind": "fact", "content": "I live in Boston."},
            request_identifier=mutation_id,
        )

    def test_mutation_rejects_non_chief_and_scheduled_runs(self) -> None:
        raw = [
            {
                "mutationId": str(uuid.uuid4()),
                "action": "install_template",
                "value": {"templateId": "meme-maker"},
            }
        ]
        with self.assertRaisesRegex(ValueError, "direct Chief"):
            self.apply_bot_mutations("user-1", {"systemRole": "specialist"}, {}, raw)
        with self.assertRaisesRegex(ValueError, "scheduled runs"):
            self.apply_bot_mutations(
                "user-1", {"systemRole": "chief"}, {"source": "schedule"}, raw
            )

    def test_direct_email_requires_exact_approval_and_enabled_inbox(self) -> None:
        raw = [{
            "mutationId": str(uuid.uuid4()), "action": "send_email",
            "value": {"to": "Friend@Example.com", "subject": "Hello", "body": "Report attached."},
        }]
        turn = {"pk": "CHAT#user-1#writer", "sk": "TURN#one", "id": "one", "source": "app"}
        with self.assertRaisesRegex(ValueError, "exact approval"):
            self.apply_bot_mutations("user-1", {"id": "writer"}, turn, raw)

        proposal = {"id": "interrupt", "digest": "digest", "toolUseId": "call",
                    "toolName": "send_bot_email", "input": {
                        "to": "Friend@Example.com", "subject": "Hello", "body": "Report attached."}}
        turn.update(approvalRequest=proposal, approvalDecision={
            "id": "interrupt", "digest": "digest", "toolUseId": "call"})
        bot_api = SimpleNamespace(_get_bot=MagicMock(return_value={
            "id": "writer", "emailToken": "abcdefghijklmnop",
            "emailOwnerAddress": "owner@example.com",
        }))
        with patch.dict(self.bot_mutation_globals, {"_bot_api": lambda: bot_api}):
            self.apply_bot_mutations("user-1", {"id": "writer"}, turn, raw)
            raw[0]["value"]["body"] = "Changed after approval"
            with self.assertRaisesRegex(ValueError, "changed after approval"):
                self.apply_bot_mutations("user-1", {"id": "writer"}, turn, raw)

        self.assertEqual(turn["outboundEmail"]["to"], "friend@example.com")
        self.assertIn("outboundEmail = :email", self.table.updates[-1]["UpdateExpression"])


if __name__ == "__main__":
    import unittest

    unittest.main()
