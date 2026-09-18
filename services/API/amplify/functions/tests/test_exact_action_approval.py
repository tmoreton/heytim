from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from api_test_case import ApiTestCase


class GroupActionApprovalTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.proposal = {
            "id": "interrupt-1", "digest": "a" * 64,
            "toolUseId": "call-1", "toolName": "github_issue_write",
            "input": {"repository": "owner/repo", "title": "Exact title"},
            "expiresAt": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        }
        self.request = {"type": "GROUP_AGENT_ROUND", "groupId": "room",
                        "messageId": "run", "replies": [{"replyKey": "MESSAGE#task"}]}
        self.run = {"pk": "GROUP#room", "sk": "RUN#run", "entity": "WORKFLOW_RUN",
                    "id": "run", "ownerId": "owner", "status": "AWAITING_APPROVAL",
                    "taskIds": ["task"], "taskKeys": ["MESSAGE#task"], "source": "chat"}
        self.task = {"pk": "GROUP#room", "sk": "MESSAGE#task", "id": "task",
                     "runId": "run", "authorId": "bot", "botOwnerId": "owner",
                     "status": "AWAITING_APPROVAL", "approvalRequest": self.proposal,
                     "approvalGrantDigest": "grant-1", "resumeRequest": self.request}
        for item in (self.run, self.task, {"pk": "USER#owner", "sk": "BOT#bot", "toolIds": ["github"]}):
            self.data_table.put_item(Item=item)

    def _decide(self, owner: str = "owner", approved: bool = True):
        with (patch.object(self.group_runs, "_require_group_member", return_value=({}, [])),
              patch.object(self.group_runs.catalog, "approval_tool_names", return_value=["GitHub"]),
              patch.object(self.group_runs, "approval_grant_digest", return_value="grant-1")):
            return self.group_runs._decide_group_action(owner, "room", "run", "task", approved)

    def test_owner_approves_only_saved_proposal_with_one_execution_key(self) -> None:
        result = self._decide()
        self.assertEqual(result["status"], "pending")
        update = self.data_table.updated[-1]
        self.assertIn("approvalRequest = :proposal", update["ConditionExpression"])
        self.assertEqual(update["ExpressionAttributeValues"][":proposal"], self.proposal)
        self.assertEqual(len(update["ExpressionAttributeValues"][":decision"]["executionKey"]), 36)
        self.assertEqual(len(self.sqs.send_message.call_args_list), 2)
        self.assertEqual(json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"]), self.request)

    def test_other_room_member_cannot_approve_owner_action(self) -> None:
        with self.assertRaises(self.support.ApiError) as error:
            self._decide(owner="another-member")
        self.assertEqual(error.exception.status_code, 403)
        self.assertFalse(self.data_table.updated)

    def test_expired_action_never_queues_resume(self) -> None:
        self.task["approvalRequest"]["expiresAt"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        self.data_table.put_item(Item=self.task)
        with self.assertRaises(self.support.ApiError) as error:
            self._decide()
        self.assertEqual(error.exception.status_code, 409)
        self.sqs.send_message.assert_not_called()

    def test_denial_completes_task_and_discards_snapshot(self) -> None:
        result = self._decide(approved=False)
        self.assertEqual(result["status"], "denied")
        self.assertIn("#status = :error", self.data_table.updated[-1]["UpdateExpression"])
        self.s3.delete_object.assert_called_once()
