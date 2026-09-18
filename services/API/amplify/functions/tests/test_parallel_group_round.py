from __future__ import annotations

import json
from unittest.mock import patch

from shared.workflows import group_run_record, is_parallel_group_round, task_metadata
from worker_test_case import WorkerTestCase


class ParallelGroupRoundTests(WorkerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.request = {
            "type": "GROUP_AGENT_ROUND",
            "requestedBy": "owner",
            "groupId": "work",
            "messageId": "run-1",
            "userText": "Compare options",
            "replies": [
                {"botId": "chief", "replyKey": "MESSAGE#lead", "roundRole": "lead"},
                {"botId": "research", "replyKey": "MESSAGE#research", "roundRole": "contributor"},
                {"botId": "writer", "replyKey": "MESSAGE#writer", "roundRole": "contributor"},
                {"botId": "chief", "replyKey": "MESSAGE#final", "roundRole": "synthesizer"},
            ],
        }

    def test_contract_carries_run_task_identity(self) -> None:
        run = group_run_record(
            "GROUP#work", "run-1", "owner", "chat", "now", ["lead", "final"]
        )
        self.assertEqual(run["workflowVersion"], 1)
        self.assertEqual(run["status"], "PENDING")
        self.assertEqual(task_metadata("run-1", "lead", "lead")["runId"], "run-1")
        self.assertTrue(is_parallel_group_round(self.request["replies"]))

    def test_lead_dispatches_all_specialists_without_waiting_for_each_other(self) -> None:
        with (
            patch.object(self.group_job, "_activate_group_reply"),
            patch.object(self.group_job, "_set_group_run_status"),
            patch.object(self.group_job, "_process_group_agent_reply", return_value="Lead"),
        ):
            self.group_job._process_group_agent_round(
                {"messageId": "queue-lead"}, self.request
            )
        jobs = [json.loads(call.kwargs["MessageBody"]) for call in self.sqs.send_message.call_args_list]
        self.assertEqual([job["nextReplyIndex"] for job in jobs], [1, 2])
        self.assertTrue(all(job["type"] == "GROUP_AGENT_CONTRIBUTOR" for job in jobs))
        self.assertTrue(all(job["parallelRound"] for job in jobs))

    def test_synthesis_waits_for_every_specialist(self) -> None:
        for key, status in (("MESSAGE#research", "COMPLETE"), ("MESSAGE#writer", "RUNNING")):
            self.table.put_item(Item={"pk": "GROUP#work", "sk": key, "status": status})
        self.group_job._queue_parallel_synthesis_if_ready(self.request)
        self.sqs.send_message.assert_not_called()

        self.table.items[("GROUP#work", "MESSAGE#writer")]["status"] = "ERROR"
        self.group_job._queue_parallel_synthesis_if_ready(self.request)
        job = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(job["nextReplyIndex"], 3)
        self.assertEqual(job["type"], "GROUP_AGENT_ROUND")

    def test_child_retries_recheck_barrier_after_cached_result(self) -> None:
        for key in ("MESSAGE#research", "MESSAGE#writer"):
            self.table.put_item(Item={"pk": "GROUP#work", "sk": key, "status": "COMPLETE"})
        with (
            patch.object(self.group_job, "_activate_group_reply"),
            patch.object(self.group_job, "_process_group_agent_reply", return_value="Cached"),
        ):
            self.group_job._process_group_agent_contributor(
                {"messageId": "queue-retry"},
                {**self.request, "type": "GROUP_AGENT_CONTRIBUTOR", "nextReplyIndex": 1},
            )
        self.assertEqual(self.sqs.send_message.call_count, 1)

    def test_invalid_parallel_job_cannot_invoke_a_reply(self) -> None:
        with (patch.object(self.group_job, "_process_group_agent_reply") as invoke,
              self.assertRaises(ValueError)):
            self.group_job._process_group_agent_contributor(
                {"messageId": "forged"},
                {**self.request, "nextReplyIndex": 3},
            )
        invoke.assert_not_called()

    def test_cancelled_run_never_starts_another_specialist_or_synthesis(self) -> None:
        self.table.put_item(Item={
            "pk": "GROUP#work", "sk": "RUN#run-1", "entity": "WORKFLOW_RUN",
            "status": "CANCELLED",
        })
        with patch.object(self.group_job, "_process_group_agent_reply") as invoke:
            self.group_job._process_group_agent_round(
                {"messageId": "queued-final"},
                {**self.request, "nextReplyIndex": 3, "parallelRound": True},
            )
        invoke.assert_not_called()
        self.sqs.send_message.assert_not_called()

    def test_parallel_specialist_sees_lead_but_not_sibling_or_later_message(self) -> None:
        items = [
            {"sk": "MESSAGE#1#00#run-1", "id": "run-1", "status": "COMPLETE",
             "authorType": "user", "authorName": "Owner", "text": "Compare options"},
            {"sk": "MESSAGE#1#01#lead", "roundId": "run-1", "roundRole": "lead",
             "status": "COMPLETE", "authorType": "bot", "authorName": "Chief", "text": "Research costs"},
            {"sk": "MESSAGE#1#02#research", "roundId": "run-1", "roundRole": "contributor",
             "status": "COMPLETE", "authorType": "bot", "authorName": "Research", "text": "Costs are low"},
            {"sk": "MESSAGE#2#00#later", "status": "COMPLETE", "authorType": "user",
             "authorName": "Owner", "text": "New, unrelated request"},
        ]
        with patch.object(self.agent.table, "query", return_value={"Items": items}):
            contributor = self.agent._get_group_history(
                "work", "writer", "run-1", parallel_role="contributor"
            )
            synthesizer = self.agent._get_group_history(
                "work", "chief", "run-1", parallel_role="synthesizer"
            )
        contributor_text = json.dumps(contributor)
        synthesis_text = json.dumps(synthesizer)
        self.assertIn("Research costs", contributor_text)
        self.assertNotIn("Costs are low", contributor_text)
        self.assertNotIn("unrelated", contributor_text)
        self.assertIn("Costs are low", synthesis_text)

    def test_parallel_history_queries_before_run_boundary_and_reports_failed_child(self) -> None:
        current_key = "MESSAGE#2026-09-18T12:00:00Z#00#run-1"
        source = {"sk": current_key, "id": "run-1", "entity": "GROUP_MESSAGE",
                  "status": "COMPLETE", "authorType": "user", "text": "Compare options"}
        lead = {"sk": "MESSAGE#2026-09-18T12:00:00Z#01#lead", "roundId": "run-1",
                "roundRole": "lead", "status": "COMPLETE", "authorType": "bot",
                "authorName": "Chief", "text": "Check prices"}
        failed = {"sk": "MESSAGE#2026-09-18T12:00:00Z#02#research", "roundId": "run-1",
                  "roundRole": "contributor", "status": "ERROR", "authorType": "bot",
                  "authorName": "Research", "text": "Source unavailable"}
        with patch.object(self.agent.table, "query", side_effect=[
            {"Items": [source]}, {"Items": [lead, failed]},
        ]) as query:
            history = self.agent._get_group_history(
                "work", "chief", "run-1", parallel_role="synthesizer",
                current_message_sk=current_key,
            )
        self.assertEqual(query.call_args_list[0].kwargs["ExpressionAttributeValues"][":cutoff"], current_key)
        self.assertIn("Source unavailable", json.dumps(history))
