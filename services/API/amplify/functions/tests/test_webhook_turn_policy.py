from __future__ import annotations

import json
import uuid
from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from worker_test_case import WorkerTestCase


class WebhookTurnPolicyTests(WorkerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.bot = {
            "id": "bot-1", "name": "Assistant", "prompt": "Answer clearly.", "entity": "BOT",
            "reasoningEffort": "high", "toolIds": ["current_time"],
            "skillVersions": {},
        }
        self.turn = {
            "pk": "CHAT#user-1#bot-1", "sk": "TURN#now#turn-1", "id": "turn-1",
            "userId": "user-1", "botId": "bot-1", "status": "PENDING",
            "createdAt": "now", "source": "webhook", "text": "What time is it?",
            "webhookEventId": "event-1", "eventSourceId": "source-1",
            "routingDecision": {
                "botId": "bot-1", "reasoningEffort": "low", "method": "local",
                "eventId": "event-1", "sourceId": "source-1",
            },
        }
        self.source_id = str(uuid.uuid4())
        self.turn["eventSourceId"] = self.source_id
        self.turn["routingDecision"]["sourceId"] = self.source_id
        self.source = {"pk": "USER#user-1", "sk": f"WEBHOOK_SOURCE#{self.source_id}",
                       "entity": "WEBHOOK_SOURCE", "id": self.source_id, "enabled": True, "allowedBotIds": ["bot-1"]}
        self.usage = {"models": [{
            "provider": "openrouter", "modelId": "deepseek/deepseek-v4.1-flash",
            "callCount": 1, "inputTokens": 100, "outputTokens": 20,
            "providerCostUsd": "0.00012",
        }]}

    def _run(self, result=None):
        self.table.items[(self.turn["pk"], self.turn["sk"])] = deepcopy(self.turn)
        self.table.items[("USER#user-1", "BOT#bot-1")] = {**deepcopy(self.bot), "entity": "BOT"}
        if self.source:
            self.table.items[(self.source["pk"], self.source["sk"])] = deepcopy(self.source)
        else:
            self.table.items.pop(("USER#user-1", f"WEBHOOK_SOURCE#{self.source_id}"), None)
        result = result or self.agent.AgentInvocationResult(text="It is noon.", usage=self.usage)
        values = {}
        with ExitStack() as stack:
            for name, kwargs in {
                "_account_is_active": {"return_value": True},
                "_claim_work": {"return_value": "lease-1"},
                "admit_run": {"return_value": SimpleNamespace(allowed=True)},
                "_invoke": {"return_value": result},
                "record_invocation_usage": {},
                "_collect_generated_artifacts": {"return_value": []},
                "_delete_generated_artifacts": {},
                "_finish_work": {"return_value": "finished-at"},
                "_update_schedule_result": {},
                "_queue_reply_notification": {},
                "_queue_email_delivery": {},
                "queue_approval_expiry": {},
                "delete_approval_snapshot": {},
                "create_device_call": {},
                "apply_bot_mutations": {},
                "finish_failed_attempt": {"return_value": SimpleNamespace(
                    disposition=self.direct_job.FailureDisposition.FINISHED,
                    completed_at="finished-at",
                )},
                "record_terminal_error": {},
                "logger": {},
            }.items():
                values[name] = stack.enter_context(patch.object(self.direct_job, name, **kwargs))
            self.direct_job._process_agent_reply(
                {"messageId": "queue-1"},
                {"userId": "user-1", "botId": "bot-1", "turnKey": self.turn["sk"]},
            )
        return values

    def test_webhook_question_uses_pinned_effort_and_reports_actual_effort(self) -> None:
        original = deepcopy(self.bot)
        mocks = self._run()
        args = mocks["_invoke"].call_args
        self.assertEqual(args.args[2]["reasoningEffort"], "low")
        self.assertEqual(args.args[2]["prompt"], original["prompt"])
        self.assertEqual(args.args[2]["inputProvenance"], {"kind": "webhook"})
        self.assertFalse(args.kwargs["allow_bot_management"])
        self.assertFalse(args.kwargs["allow_device_tools"])
        self.assertEqual(self.table.items[("USER#user-1", "BOT#bot-1")], {**original, "entity": "BOT"})
        self.assertEqual(self.turn["text"], "What time is it?")
        summary = mocks["_finish_work"].call_args.kwargs["usage_summary"]
        self.assertEqual(summary["reasoningEffort"], "low")
        self.assertEqual(summary["costUsd"], "0.000120000000")

    def test_background_completion_keeps_pinned_effort_after_bot_setting_changes(self) -> None:
        self.bot["reasoningEffort"] = "max"
        self.turn["backgroundResults"] = [{"label": "lookup", "status": "complete"}]
        self.turn["runtimeResult"] = {"text": "Finished", "usage": self.usage}
        mocks = self._run()
        invocation = mocks["_invoke"].call_args
        self.assertEqual(invocation.args[2]["reasoningEffort"], "low")
        self.assertEqual(invocation.kwargs["continuation"], self.turn["backgroundResults"])
        self.assertEqual(invocation.kwargs["runtime_result"], self.turn["runtimeResult"])
        self.assertEqual(
            mocks["_finish_work"].call_args.kwargs["usage_summary"]["reasoningEffort"], "low"
        )

    def test_invalid_or_stale_decision_stops_before_model_invocation(self) -> None:
        valid = deepcopy(self.turn)
        cases = [None, [], {},
                 {**valid["routingDecision"], "reasoningEffort": "medium"},
                 {**valid["routingDecision"], "reasoningEffort": ["low"]},
                 {**valid["routingDecision"], "botId": "other-bot"},
                 {**valid["routingDecision"], "eventId": "old-event"},
                 {**valid["routingDecision"], "sourceId": "other-source"}]
        for routing in cases:
            with self.subTest(routing=routing):
                self.turn = {**valid, "routingDecision": routing}
                mocks = self._run()
                mocks["_invoke"].assert_not_called()
                mocks["finish_failed_attempt"].assert_called_once()

    def test_unrouted_app_turn_preserves_saved_bot_preferences(self) -> None:
        self.turn = {**self.turn, "source": "app"}
        del self.turn["routingDecision"]
        mocks = self._run()
        invocation = mocks["_invoke"].call_args
        self.assertEqual(invocation.args[2], self.bot)
        self.assertTrue(invocation.kwargs["allow_bot_management"])
        self.assertTrue(invocation.kwargs["allow_device_tools"])
        self.assertEqual(
            mocks["_finish_work"].call_args.kwargs["usage_summary"]["reasoningEffort"], "high"
        )

    def test_webhook_can_pause_and_resume_normal_tool_approval(self) -> None:
        proposal = {
            "id": "approval-1", "digest": "a" * 64, "toolUseId": "tool-1",
            "toolName": "browser", "expiresAt": "2099-09-18T12:00:00+00:00",
        }
        self.bot["toolIds"] = ["browser"]
        with patch.object(self.direct_job.catalog, "approval_tool_names", return_value=["browser"]):
            paused = self._run(self.agent.AgentInvocationResult(text="", pending_approval=proposal))
            paused["queue_approval_expiry"].assert_called_once()
            self.assertEqual(
                self.table.updates[-1]["ExpressionAttributeValues"][":awaiting"], "AWAITING_APPROVAL"
            )
            self.turn.update({
                "approvalRequest": proposal,
                "approvalDecision": {key: proposal[key] for key in ("id", "digest", "toolUseId")},
                "approvalGrantDigest": self.direct_job.approval_grant_digest(
                    self.direct_job.catalog, "user-1", self.bot
                ),
            })
            resumed = self._run()
        self.assertEqual(resumed["_invoke"].call_args.kwargs["action_approval"], self.turn["approvalDecision"])
        self.assertEqual(resumed["_invoke"].call_args.args[2]["reasoningEffort"], "low")
        self.assertFalse(resumed["_invoke"].call_args.kwargs["allow_bot_management"])

    def test_webhook_rejects_stored_device_resume_before_dispatch(self) -> None:
        self.turn["deviceResult"] = {"status": "success", "result": {"value": "stale"}}
        mocks = self._run()
        mocks["_invoke"].assert_not_called()
        mocks["create_device_call"].assert_not_called()
        mocks["finish_failed_attempt"].assert_called_once()

    def test_webhook_rejects_returned_device_calls_and_configuration_mutations(self) -> None:
        for fields in ({"pending_device_call": {"id": "stale-interrupt"}},
                       {"bot_mutations": [{"action": "install_template"}]}):
            with self.subTest(fields=fields):
                mocks = self._run(self.agent.AgentInvocationResult(text="", **fields))
                mocks["create_device_call"].assert_not_called()
                mocks["apply_bot_mutations"].assert_not_called()
                mocks["_finish_work"].assert_not_called()
                mocks["finish_failed_attempt"].assert_called_once()

    def test_skill_dependencies_cannot_restore_disabled_management_or_device_tools(self) -> None:
        tools = [
            {"id": "current_time", "runtime": {"kind": "local", "name": "current_time"}},
            {"id": "bot_manager", "runtime": {"kind": "local", "name": "bot_manager"}},
            {"id": "mac_computer", "runtime": {"kind": "device", "platform": "macos"}},
        ]
        self.bot["toolIds"] = [tool["id"] for tool in tools]
        self.bot["inputProvenance"] = {"kind": "webhook"}
        with (
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[{
                "id": "skill-1", "requiredToolIds": ["bot_manager", "current_time"],
            }]),
            patch.object(self.agent.catalog, "available_tool_ids", side_effect=lambda _owner, ids: ids),
            patch.object(self.agent.catalog, "resolve_tools_for_runtime", return_value=tools) as resolve,
            patch.object(self.agent, "_team_roster", return_value=[]),
            patch.object(self.agent, "read_agent_stream", return_value="It is noon."),
        ):
            self.agent._invoke(
                "user-1", "bot-1", self.bot, history=[], event_id="turn-1",
                allow_bot_management=False, allow_device_tools=False,
            )
        self.assertNotIn("bot_manager", resolve.call_args.args[1])
        payload = json.loads(self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"])
        self.assertEqual([tool["id"] for tool in payload["bot"]["tools"]], ["current_time"])
        self.assertNotIn("botManagement", payload)
        self.assertIn("aiConsent", payload)
        self.assertEqual(payload["inputProvenance"], {"kind": "webhook"})

    def test_source_revocation_and_allowlist_changes_fence_queued_and_resumed_turns(self):
        original_source = deepcopy(self.source)
        for state in (None, {**original_source, "enabled": False}, {**original_source, "allowedBotIds": ["different-bot"]}):
            for resumed in (False, True):
                with self.subTest(source=state, resumed=resumed):
                    self.source = state
                    self.turn["runtimeResult"] = {"text": "Finished", "usage": self.usage} if resumed else None
                    mocks = self._run()
                    mocks["_invoke"].assert_not_called()
                    mocks["finish_failed_attempt"].assert_called_once()
