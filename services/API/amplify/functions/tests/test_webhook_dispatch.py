from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from shared.webhooks import event_key, source_key
from worker_test_case import WorkerTestCase


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

    def _configure_fallback(self):
        source = self.table.items[("USER#owner", f"WEBHOOK_SOURCE#{self.source_id}")]
        source["fallbackBotId"] = "bot-1"
        event = self.table.items[("USER#owner", f"WEBHOOK_EVENT#{self.event_id}")]
        event["routingDecision"] = {"method": "local_fallback", "botId": "bot-1", "reasoningEffort": "high",
            "localDecision": {"botId": None, "reasoningEffort": "low", "confidence": .2}}
        return source, event

    def test_fallback_dispatch_keeps_raw_snapshot_and_fences_policy_without_binding_secret_rotation(self):
        source, event = self._configure_fallback()
        raw = deepcopy(event["routingDecision"]["localDecision"])
        def persist(_table, _user, item, **kwargs):
            guard = kwargs["required_item_condition"]
            self.assertNotIn("updatedAt", guard["ConditionExpression"])
            self.assertNotIn("credentialVersion", guard["ConditionExpression"])
            self.assertEqual(guard["ExpressionAttributeValues"][":fallback"], "bot-1")
            self.table.items[(item["pk"], item["sk"])] = item
        source.update(credentialVersion=2, secretArn="rotated", updatedAt="later")
        with patch.dict(self.job.process_webhook_dispatch.__globals__, {
            "grants_for_job": lambda *_: [], "put_user_item_while_account_active": persist}):
            self.job.process_webhook_dispatch({"messageId": "fallback"}, self.request)
        turn = next(item for item in self.table.items.values() if item.get("entity") == "TURN")
        self.assertEqual(turn["routingDecision"]["method"], "local_fallback")
        self.assertEqual(turn["routingDecision"]["reasoningEffort"], "high")
        self.assertEqual(turn["routingDecision"]["localDecision"], raw)
        self.assertEqual(json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])["type"], "AGENT_REPLY")

    def test_removed_changed_or_disabled_fallback_policy_stops_dispatch(self):
        source, _ = self._configure_fallback()
        original = deepcopy(source)
        for fields in ({"fallbackBotId": None}, {"fallbackBotId": "another-bot"},
                       {"enabled": False}, {"routingMode": "fixed"}):
            with self.subTest(fields=fields):
                source.clear()
                source.update({**original, **fields})
                self.sqs.reset_mock()
                self.job.process_webhook_dispatch({"messageId": "fallback"}, self.request)
                self.assertFalse(self.sqs.send_message.called)
                self.assertFalse(any(item.get("entity") == "TURN" for item in self.table.items.values()))

    def test_local_to_fixed_and_fixed_to_local_changes_stop_dispatch_even_with_same_bot(self):
        source, event = self._configure_fallback()
        for method, mode in (("local", "fixed"), ("fixed", "local")):
            with self.subTest(method=method, mode=mode):
                event["routingDecision"]["method"] = method
                source["routingMode"] = mode
                self.sqs.reset_mock()
                self.job.process_webhook_dispatch({"messageId": "mode-change"}, self.request)
                self.assertFalse(self.sqs.send_message.called)
                self.assertFalse(any(item.get("entity") == "TURN" for item in self.table.items.values()))

    def test_partial_fallback_queue_retry_revokes_only_unstarted_turn_and_frees_bot(self):
        source, _ = self._configure_fallback()
        def persist(_table, _user, item, **_kwargs):
            self.table.items[(item["pk"], item["sk"])] = item
        self.sqs.send_message.side_effect = TimeoutError()
        try:
            with patch.dict(self.job.process_webhook_dispatch.__globals__, {
                "grants_for_job": lambda *_: [], "put_user_item_while_account_active": persist}):
                with self.assertRaises(TimeoutError):
                    self.job.process_webhook_dispatch({"messageId": "first"}, self.request)
                turn = next(item for item in self.table.items.values() if item.get("entity") == "TURN")
                original = deepcopy(turn)
                self.assertTrue(self.job._active_turn_exists(self.user_id, "bot-1", "different-turn"))
                source.pop("fallbackBotId")
                self.sqs.send_message.side_effect = None
                self.sqs.reset_mock()
                original_update = self.table.update_item
                def update(**kwargs):
                    original_update(**kwargs)
                    values = kwargs.get("ExpressionAttributeValues", {})
                    if values.get(":cancelled") == "CANCELLED":
                        self.assertIn("attribute_not_exists(startedAt)", kwargs["ConditionExpression"])
                        self.assertIn("attribute_not_exists(leaseOwner)", kwargs["ConditionExpression"])
                        stored = self.table.items[(kwargs["Key"]["pk"], kwargs["Key"]["sk"])]
                        stored.update(status=values[":cancelled"], assistantText=values[":message"], completedAt=values[":now"])
                with patch.object(self.table, "update_item", side_effect=update):
                    self.job.process_webhook_dispatch({"messageId": "retry"}, self.request)
                self.assertFalse(self.sqs.send_message.called)
                self.assertEqual(turn["status"], "CANCELLED")
                self.assertFalse(self.job._active_turn_exists(self.user_id, "bot-1", "different-turn"))
                self.assertEqual(turn["userText"], original["userText"])
                self.assertEqual(turn["routingDecision"], original["routingDecision"])
                self.assertEqual(len([item for item in self.table.items.values() if item.get("entity") == "TURN"]), 1)
        finally:
            self.sqs.send_message.side_effect = None

    def test_revocation_does_not_cancel_running_started_or_unrelated_turns(self):
        source, event = self._configure_fallback()
        source.pop("fallbackBotId")
        turn_id = self.job._webhook_turn_id(self.user_id, self.event_id)
        turn = {"pk": "CHAT#owner#bot-1", "sk": f"TURN#{event['createdAt']}#{turn_id}",
                "entity": "TURN", "id": turn_id, "botId": "bot-1", "status": "PENDING",
                "webhookEventId": self.event_id, "eventSourceId": self.source_id}
        unrelated = {**turn, "sk": "TURN#unrelated", "id": "unrelated"}
        self.table.items[(unrelated["pk"], unrelated["sk"])] = unrelated
        for changed in ({"status": "RUNNING"}, {"startedAt": "already-started"},
                        {"leaseOwner": "active-worker"}, {"webhookEventId": "another-event"},
                        {"eventSourceId": "another-source"}):
            with self.subTest(changed=changed):
                stored = {**turn, **changed}
                self.table.items[(stored["pk"], stored["sk"])] = stored
                self.table.updates.clear()
                self.job.process_webhook_dispatch({"messageId": "revoked"}, self.request)
                self.assertFalse(any(":cancelled" in update.get("ExpressionAttributeValues", {}) for update in self.table.updates))
                self.assertEqual(stored, {**turn, **changed})
                self.assertEqual(unrelated["status"], "PENDING")

    def test_owner_manual_reroute_same_bot_after_partial_revocation_creates_one_new_attempt(self):
        source, event = self._configure_fallback()
        def persist(_table, _user, item, **_kwargs):
            key = (item["pk"], item["sk"])
            if key in self.table.items:
                raise self.job.UserItemConflictError()
            self.table.items[key] = item
        original_update = self.table.update_item
        def update(**kwargs):
            original_update(**kwargs)
            values = kwargs.get("ExpressionAttributeValues", {})
            if values.get(":cancelled") == "CANCELLED":
                stored = self.table.items[(kwargs["Key"]["pk"], kwargs["Key"]["sk"])]
                stored.update(status="CANCELLED", assistantText=values[":message"], completedAt=values[":now"])
        with patch.dict(self.job.process_webhook_dispatch.__globals__, {
            "grants_for_job": lambda *_: [], "put_user_item_while_account_active": persist}), \
                patch.object(self.table, "update_item", side_effect=update):
            self.sqs.send_message.side_effect = TimeoutError()
            try:
                with self.assertRaises(TimeoutError):
                    self.job.process_webhook_dispatch({"messageId": "partial"}, self.request)
            finally:
                self.sqs.send_message.side_effect = None
            old = next(item for item in self.table.items.values() if item.get("entity") == "TURN")
            source.pop("fallbackBotId")
            self.job.process_webhook_dispatch({"messageId": "revoked"}, self.request)
            self.assertEqual(old["status"], "CANCELLED")
            old_snapshot = deepcopy(old)
            event["routingDecision"] = {"method": "manual", "botId": "bot-1", "reasoningEffort": "high",
                "manualAttemptId": str(uuid.uuid4()), "localDecision": old["routingDecision"]["localDecision"]}
            self.sqs.reset_mock()
            self.job.process_webhook_dispatch({"messageId": "manual"}, self.request)
            self.job.process_webhook_dispatch({"messageId": "duplicate-manual"}, self.request)
            turns = [item for item in self.table.items.values() if item.get("entity") == "TURN"]
            self.assertEqual(len(turns), 2)
            new = next(item for item in turns if item["id"] != old["id"])
            self.assertEqual(new["status"], "PENDING")
            self.assertEqual(new["routingDecision"]["method"], "manual")
            self.assertEqual(new["routingDecision"]["localDecision"], old["routingDecision"]["localDecision"])
            self.assertEqual(old, old_snapshot)
            jobs = [json.loads(call.kwargs["MessageBody"]) for call in self.sqs.send_message.call_args_list]
            self.assertEqual([job["turnId"] for job in jobs], [new["id"], new["id"]])
