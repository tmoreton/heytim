from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from worker_test_case import WorkerTestCase
from shared.webhooks import event_key, source_key


class WebhookDispatchTests(WorkerTestCase):
    def setUp(self):
        super().setUp()
        self.job = SimpleNamespace(**self.handler.process_webhook_dispatch.__globals__)
        self.user_id, self.source_id, self.event_id = "owner", str(uuid.uuid4()), str(uuid.uuid4())
        source = {**source_key(self.user_id, self.source_id), "entity": "WEBHOOK_SOURCE", "id": self.source_id,
                  "enabled": True, "routingMode": "local", "allowedBotIds": ["bot-1"], "updatedAt": "2026-10-14T12:00:00Z"}
        bot = {"pk": "USER#owner", "sk": "BOT#bot-1", "entity": "BOT", "id": "bot-1", "name": "Research", "reasoningEffort": "high"}
        event = {**event_key(self.user_id, self.event_id), "entity": "WEBHOOK_EVENT", "id": self.event_id,
                 "userId": self.user_id, "sourceId": self.source_id, "status": "dispatch_pending", "text": "A question",
                 "createdAt": "2026-10-14T12:00:00Z", "expiresAt": int(time.time()) + 1000,
                 "routingDecision": {"method": "local", "botId": "bot-1", "reasoningEffort": "low", "confidence": .95}}
        for item in (source, bot, event): self.table.items[(item["pk"], item["sk"])] = item
        self.request = {"type": "WEBHOOK_DISPATCH", "userId": self.user_id, "eventId": self.event_id}
        self.sqs.reset_mock()

    def test_dispatch_creates_deterministic_provenanced_turn_and_uses_existing_reply_worker(self):
        def persist(_table, _user, item, **kwargs):
            self.assertTrue(kwargs["require_absent"])
            self.table.items[(item["pk"], item["sk"])] = item
        with patch.dict(self.job.process_webhook_dispatch.__globals__, {
            "grants_for_job": lambda *_: [], "put_user_item_while_account_active": persist}):
            self.job.process_webhook_dispatch({"messageId": "queue-1"}, self.request)
        turns = [item for item in self.table.items.values() if item.get("entity") == "TURN"]
        self.assertEqual(len(turns), 1)
        turn = turns[0]
        self.assertEqual(turn["source"], "webhook")
        self.assertEqual(turn["routingDecision"]["reasoningEffort"], "low")
        self.assertEqual(turn["routingDecision"]["eventId"], turn["webhookEventId"])
        self.assertEqual(turn["routingDecision"]["sourceId"], turn["eventSourceId"])
        queued = [json.loads(call.kwargs["MessageBody"]) for call in self.sqs.send_message.call_args_list]
        self.assertEqual(queued[-1]["type"], "AGENT_REPLY")
        self.assertEqual(queued[-1]["turnId"], turn["id"])

    def test_busy_bot_requeues_external_event_without_interrupting_existing_turn(self):
        self.table.items[("CHAT#owner#bot-1", "TURN#active")] = {"entity": "TURN", "id": "active", "status": "RUNNING"}
        with patch.dict(self.job.process_webhook_dispatch.__globals__, {"grants_for_job": lambda *_: []}):
            self.job.process_webhook_dispatch({"messageId": "queue-1"}, self.request)
        queued = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(queued["type"], "WEBHOOK_DISPATCH")
        self.assertEqual(queued["waitAttempt"], 1)
        self.assertEqual(self.table.items[("CHAT#owner#bot-1", "TURN#active")]["status"], "RUNNING")
        self.assertEqual(len([item for item in self.table.items.values() if item.get("entity") == "TURN"]), 1)

    def test_revoked_source_or_bot_allowlist_change_does_not_invoke_agent(self):
        self.table.items[("USER#owner", f"WEBHOOK_SOURCE#{self.source_id}")]["allowedBotIds"] = ["another-bot"]
        self.job.process_webhook_dispatch({"messageId": "queue-1"}, self.request)
        self.assertFalse(self.sqs.send_message.called)
        self.assertFalse(any(item.get("entity") == "TURN" for item in self.table.items.values()))

    def test_watchdog_recovers_pending_and_expired_leases_but_skips_live_dispatch(self):
        first = self.table.items[("USER#owner", f"WEBHOOK_EVENT#{self.event_id}")]
        first["webhookDispatchPk"] = "PENDING"
        second = {**first, "id": str(uuid.uuid4()), "sk": f"WEBHOOK_EVENT#{uuid.uuid4()}", "status": "dispatching", "dispatchLeaseExpiresAt": int(time.time()) + 300}
        self.table.items[(second["pk"], second["sk"])] = second
        self.job.recover_webhook_dispatches()
        self.assertEqual(self.sqs.send_message.call_count, 1)
        self.assertEqual(json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])["eventId"], self.event_id)

    def test_queue_failure_retry_keeps_original_effort_when_bot_preferences_change(self):
        event = self.table.items[("USER#owner", f"WEBHOOK_EVENT#{self.event_id}")]
        event["routingDecision"] = {"method": "fixed", "botId": "bot-1"}
        self.table.items[("USER#owner", f"WEBHOOK_SOURCE#{self.source_id}")].update(routingMode="fixed", fallbackBotId="bot-1")
        def persist(_table, _user, item, **_kwargs):
            key = (item["pk"], item["sk"])
            if key in self.table.items: raise self.job.UserItemConflictError()
            self.table.items[key] = item
        self.sqs.send_message.side_effect = TimeoutError()
        try:
            with patch.dict(self.job.process_webhook_dispatch.__globals__, {
                "grants_for_job": lambda *_: [], "put_user_item_while_account_active": persist}):
                with self.assertRaises(TimeoutError): self.job.process_webhook_dispatch({"messageId": "first-attempt"}, self.request)
                turns = [item for item in self.table.items.values() if item.get("entity") == "TURN"]
                self.assertEqual(len(turns), 1)
                self.assertEqual(turns[0]["routingDecision"]["reasoningEffort"], "high")
                self.table.items[("USER#owner", "BOT#bot-1")]["reasoningEffort"] = "low"
                self.sqs.send_message.side_effect = None
                self.job.process_webhook_dispatch({"messageId": "second-attempt"}, self.request)
                queued = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
                self.assertEqual(queued["turnId"], turns[0]["id"])
                self.assertEqual(turns[0]["routingDecision"]["reasoningEffort"], "high")
                self.assertEqual(len([item for item in self.table.items.values() if item.get("entity") == "TURN"]), 1)
        finally:
            self.sqs.send_message.side_effect = None
