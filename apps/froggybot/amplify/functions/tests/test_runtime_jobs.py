from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from worker_test_case import WorkerTestCase


class RuntimeJobTests(WorkerTestCase):
    def setUp(self):
        super().setUp()
        self.jobs = self.runtime_jobs
        self.s3.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
        self.agentcore.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        self.key = {"pk": "CHAT#1", "sk": "TURN#1"}
        self.resume = {
            "type": "AGENT_REPLY",
            "userId": "user",
            "botId": "bot",
            "turnKey": "TURN#1",
        }
        payload = {"artifacts": {"prefix": "users/actor/bots/bot/artifacts/turn"}}
        self.work_item = self.jobs.runtime_work(payload, [])
        self.item = {**self.key, "status": "PENDING", "pendingWork": [self.work_item]}

    def state(self, value):
        self.s3.get_object.return_value = {
            "Body": io.BytesIO(json.dumps(value).encode())
        }

    def poll(self):
        self.jobs.poll_runtime_work(self.key, self.item, self.work_item, self.resume)

    def test_live_job_keeps_running_after_seven_hours(self):
        self.work_item["startedAt"] = (
            datetime.now(UTC) - timedelta(hours=7)
        ).isoformat()
        self.state(
            {
                "status": "RUNNING",
                "heartbeatAt": datetime.now(UTC).isoformat(),
                "progress": ["Tests are running"],
            }
        )
        self.poll()
        self.agentcore.stop_runtime_session.assert_not_called()
        self.assertEqual(
            self.table.updates[-1]["ExpressionAttributeValues"][":activity"],
            ["Tests are running"],
        )
        self.assertEqual(self.sqs.send_message.call_args.kwargs["DelaySeconds"], 10)

    def test_eight_hour_limit_stops_only_the_matching_session(self):
        self.work_item["startedAt"] = (
            datetime.now(UTC) - timedelta(hours=8, seconds=1)
        ).isoformat()
        self.state({"status": "RUNNING", "heartbeatAt": datetime.now(UTC).isoformat()})
        self.poll()
        self.assertEqual(
            self.agentcore.stop_runtime_session.call_args.kwargs["runtimeSessionId"],
            self.work_item["sessionId"],
        )
        result = self.table.updates[-1]["ExpressionAttributeValues"][":result"]
        self.assertIn("eight-hour", result["terminalError"]["message"])

    def test_stale_heartbeat_fails_without_replaying_actions(self):
        self.state(
            {
                "status": "RUNNING",
                "heartbeatAt": (datetime.now(UTC) - timedelta(minutes=4)).isoformat(),
            }
        )
        self.poll()
        self.agentcore.invoke_agent_runtime.assert_not_called()
        self.assertIn(
            "interrupted",
            self.table.updates[-1]["ExpressionAttributeValues"][":result"][
                "terminalError"
            ]["message"],
        )

    def test_terminal_result_is_saved_before_original_group_round_resumes(self):
        self.resume = {
            "type": "GROUP_AGENT_ROUND",
            "groupId": "g",
            "nextReplyIndex": 2,
            "replies": [{"botId": "b"}],
        }
        self.state(
            {
                "status": "COMPLETE",
                "text": "verified",
                "pendingWork": [],
                "usage": {"models": []},
            }
        )
        self.poll()
        self.assertEqual(
            self.table.updates[-1]["ExpressionAttributeValues"][":result"]["text"],
            "verified",
        )
        self.assertEqual(
            json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"]),
            self.resume,
        )

    def test_cancel_race_does_not_publish_result_or_resume(self):
        self.state({"status": "COMPLETE", "text": "verified"})
        self.table.fail_condition = True
        self.poll()
        self.sqs.send_message.assert_not_called()

    def test_saved_result_never_invokes_model_again(self):
        result = self.agent._invoke(
            "user", "bot", {}, runtime_result={"text": "Verified", "pendingWork": []}
        )
        self.assertEqual(result.text, "Verified")
        self.agentcore.invoke_agent_runtime.assert_not_called()

    def test_crash_after_saving_result_requeues_completion(self):
        self.table.items[(self.key["pk"], self.key["sk"])] = {
            **self.key,
            "status": "PENDING",
            "runtimeResult": {"text": "verified"},
        }
        self.background_work._process_background_work(
            {}, {"itemKey": self.key, "resumeRequest": self.resume}
        )
        self.sqs.send_message.assert_called_once()

    def test_dispatch_releases_worker_before_starting_runtime(self):
        bot = {"name": "Engineer", "prompt": "Work", "skillVersions": {}, "toolIds": []}
        order = []
        with (
            patch.object(
                self.agent,
                "_pause_work",
                side_effect=lambda *_a: order.append("persist") or True,
            ),
            patch.object(
                self.agent,
                "queue_runtime_poll",
                side_effect=lambda *_a: order.append("poll"),
            ),
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[]),
            patch.object(
                self.agent.catalog, "resolve_tools_for_runtime", return_value=[]
            ),
        ):
            self.agentcore.invoke_agent_runtime.side_effect = lambda **_k: (
                order.append("dispatch") or {"response": io.BytesIO(b"accepted")}
            )
            result = self.agent._invoke(
                "user",
                "bot",
                bot,
                event_id="turn",
                history=[{"role": "user", "content": [{"text": "work"}]}],
                work_key=self.key,
                lease_owner="lease",
                resume_request=self.resume,
            )
        self.agentcore.invoke_agent_runtime.side_effect = None
        self.assertEqual(order, ["persist", "poll", "dispatch"])
        self.assertEqual(result.pending_work[0]["provider"], "agentcore_runtime")

    def test_account_cleanup_only_stops_owned_background_sessions(self):
        def entry(session, owner=None):
            return {"botOwnerId": owner, "pendingWork": [{"provider": "agentcore_runtime", "sessionId": session}]}

        sessions = self.account_cleanup.AccountCleanupService.owned_agent_session_ids(
            "user", [entry("direct")],
            {"shared": [entry("mine", "user"), entry("theirs", "another")],
             "owned": [{"entity": "GROUP", "ownerId": "user"}, entry("owned-group", "another")]},
        )
        self.assertEqual(sessions, {"direct", "mine", "owned-group"})
