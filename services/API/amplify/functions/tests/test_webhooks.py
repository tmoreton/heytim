from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import patch
from types import SimpleNamespace

from api_test_case import ApiTestCase
from shared.webhooks import (MODEL_ID, MODEL_REVISION, WebhookError, event_key,
                             owner_key, public_source, routing_device_key, source_key)


class WebhookTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.ingress = SimpleNamespace(**self.public_handler.incoming_webhook.__globals__)
        self.routing = SimpleNamespace(**self.handler.authenticated_routes.webhook_route.__globals__)
        self.sources = SimpleNamespace(**self.routing.save_source.__globals__)
        self.source_id, self.device_id = str(uuid.uuid4()), str(uuid.uuid4())
        self.user_id = "owner-1"
        self.secret = {"credential": "bearer-secret", "signingSecret": "signing-secret"}
        self.source = {**source_key(self.user_id, self.source_id), "entity": "WEBHOOK_SOURCE",
            "id": self.source_id, "userId": self.user_id, "name": "Index", "kind": "generic",
            "enabled": True, "routingMode": "local", "authentication": "either",
            "allowedBotIds": [], "secretArn": "arn:aws:secretsmanager:region:account:secret:heytim/connections/owner/webhook",
            "credentialVersion": 1, "mutationRevision": 1, "createdAt": "2026-10-14T12:00:00Z", "updatedAt": "2026-10-14T12:00:00Z"}
        self._put(self.source)
        self._put({**owner_key(self.source_id), "entity": "WEBHOOK_SOURCE_OWNER", "userId": self.user_id})
        self._put({"pk": "USER#owner-1", "sk": "BOT#bot-1", "entity": "BOT", "id": "bot-1", "name": "Research", "prompt": "Research questions", "reasoningEffort": "high"})
        secret = patch.object(self.ingress.catalog, "_secret_document", return_value=self.secret)
        secret.start(); self.addCleanup(secret.stop)

    def _put(self, item):
        self.data_table.items[(item["pk"], item["sk"])] = dict(item)

    def _json(self, payload=None):
        return {"body": json.dumps(payload or {"id": "message-1", "text": "What is on my calendar?"}),
                "headers": {"content-type": "application/json", "authorization": "Bearer bearer-secret"}}

    def _pebble(self, timestamp=None, text="A voice question", test=False):
        raw = ("--boundary\r\nContent-Disposition: form-data; name=\"transcription\"\r\n\r\n"
               + text + "\r\n--boundary\r\nContent-Disposition: form-data; name=\"recordedAt\"\r\n\r\n1700000000123\r\n--boundary--\r\n").encode()
        timestamp = str(timestamp or int(time.time()))
        trigger = "test-event" if test else "single-click-hold"
        prefix = f"v1\n{timestamp}\nrecording-1\n{trigger}\n{int(test)}\n".encode()
        hs = {"content-type": "multipart/form-data; boundary=boundary", "x-index-webhook-version": "1",
              "x-index-timestamp": timestamp, "x-index-delivery": "recording-1", "x-index-trigger": trigger,
              "x-index-signature": hmac.new(b"signing-secret", prefix + raw, hashlib.sha256).hexdigest()}
        if test: hs["x-index-test"] = "true"
        return {"body": raw.decode(), "headers": hs}

    def test_ingress_persists_user_owned_normalized_text_without_payload_or_secrets(self):
        result = self.ingress.ingest(self._json({"id": "message-1", "text": "Hello", "userId": "victim", "botId": "victim-bot"}), self.source_id)
        stored = self.data_table.get_item(Key=event_key(self.user_id, result["eventId"]))["Item"]
        self.assertEqual(stored["userId"], self.user_id)
        self.assertEqual(stored["text"], "Hello")
        self.assertEqual(stored["status"], "awaiting_routing")
        self.assertNotIn("botId", stored)
        self.assertNotIn("credential", json.dumps(stored))
        self.assertFalse(self.sqs.send_message.called)

    def test_replayed_delivery_is_one_event_and_conflicting_content_is_rejected(self):
        first = self.ingress.ingest(self._json(), self.source_id)
        second = self.ingress.ingest(self._json(), self.source_id)
        self.assertEqual(first["eventId"], second["eventId"])
        events = [item for item in self.data_table.items.values() if item.get("entity") == "WEBHOOK_EVENT"]
        self.assertEqual(len(events), 1)
        with self.assertRaises(WebhookError) as error:
            self.ingress.ingest(self._json({"id": "message-1", "text": "Changed"}), self.source_id)
        self.assertEqual(error.exception.status, 409)

    def test_revoked_disabled_cross_owner_and_bad_bearer_sources_cannot_ingest(self):
        bad = self._json(); bad["headers"]["authorization"] = "Bearer incorrect"
        with self.assertRaises(WebhookError): self.ingress.ingest(bad, self.source_id)
        self.source["enabled"] = False; self._put(self.source)
        with self.assertRaises(WebhookError): self.ingress.ingest(self._json(), self.source_id)
        self.data_table.delete_item(Key=owner_key(self.source_id))
        with self.assertRaises(WebhookError): self.ingress.ingest(self._json(), self.source_id)
        with self.assertRaises(WebhookError): self.sources.save_source("another-owner", {}, {}, self.source_id)

    def test_pebble_exact_signature_binds_raw_multipart_trigger_test_and_timestamp(self):
        self.source["kind"] = "pebble"; self._put(self.source)
        event = self._pebble()
        accepted = self.ingress.ingest(event, self.source_id)
        self.assertEqual(accepted["status"], "awaiting_routing")
        for changed in ("body", "x-index-trigger", "x-index-test"):
            altered = json.loads(json.dumps(event))
            if changed == "body": altered["body"] += " "
            else: altered["headers"][changed] = "true" if changed.endswith("test") else "double-click-hold"
            # A bearer alongside the invalid signature must never downgrade authentication.
            altered["headers"]["authorization"] = "Bearer bearer-secret"
            with self.assertRaises(WebhookError) as error: self.ingress.ingest(altered, self.source_id)
            self.assertEqual(error.exception.status, 401)
        with self.assertRaises(WebhookError): self.ingress.ingest(self._pebble(int(time.time()) - 301), self.source_id)

    def test_generic_hmac_timestamp_and_signed_body_identity_ignore_unbound_header_ids(self):
        event = self._json(); timestamp = str(int(time.time()))
        event["headers"].update({"x-webhook-timestamp": timestamp,
            "x-webhook-signature": "sha256=" + hmac.new(b"signing-secret", timestamp.encode() + b"." + event["body"].encode(), hashlib.sha256).hexdigest()})
        first = self.ingress.ingest(event, self.source_id)
        event["headers"]["x-webhook-id"] = "attacker-changed-unsigned-header"
        self.assertEqual(self.ingress.ingest(event, self.source_id)["eventId"], first["eventId"])

    def test_pebble_tests_do_not_dispatch_and_hmac_only_rejects_legacy_bearer(self):
        self.source["kind"] = "pebble"; self._put(self.source)
        self.assertEqual(self.ingress.ingest(self._pebble(test=True), self.source_id)["status"], "test")
        self.assertFalse(self.sqs.send_message.called)
        self.source.update(kind="generic", authentication="hmac"); self._put(self.source)
        with self.assertRaises(WebhookError): self.ingress.ingest(self._json(), self.source_id)

    def test_transcript_bounds_malformed_multipart_and_audio_only_are_rejected(self):
        for value in ({"text": ""}, {"text": "x" * 8001}, {"text": "🚀" * 4001}, {"text": {"nested": "no"}}):
            with self.assertRaises(WebhookError): self.ingress.ingest(self._json(value), self.source_id)
        self.source["kind"] = "pebble"; self._put(self.source)
        event = self._pebble(text=""); event["headers"] = {"content-type": "multipart/form-data; boundary=boundary", "authorization": "Bearer bearer-secret"}
        with self.assertRaises(WebhookError): self.ingress.ingest(event, self.source_id)

    def test_source_public_shape_hides_secret_and_fixed_route_requires_owned_bot(self):
        self.assertNotIn("secretArn", public_source(self.source))
        with self.assertRaises(WebhookError): self.sources._values(self.user_id, {"routingMode": "fixed"})
        with self.assertRaises(WebhookError): self.sources._values(self.user_id, {"allowedBotIds": ["another-owners-bot"]})
        self.assertEqual(self.sources._values(self.user_id, {"routingMode": "fixed", "fallbackBotId": "bot-1"})["fallbackBotId"], "bot-1")

    def test_router_requires_pinned_model_and_wrong_device_cannot_submit_result(self):
        registration = {"schemaVersion": 1, "appVersion": "1.0", "modelId": MODEL_ID, "modelRevision": MODEL_REVISION}
        self.routing.register_router(self.user_id, self.device_id, registration)
        bad = dict(registration, modelRevision="unreviewed")
        with self.assertRaises(WebhookError): self.routing.register_router(self.user_id, self.device_id, bad)
        result = self.ingress.ingest(self._json(), self.source_id)
        requests = self.routing.list_requests(self.user_id, self.device_id)["requests"]
        self.assertEqual(len(requests), 1)
        claim = requests[0]
        item = self.data_table.get_item(Key=event_key(self.user_id, result["eventId"]))["Item"]
        item.update(status="routing", routingDeviceId="another-device", routingLeaseToken=claim["leaseToken"], requestDigest=claim["requestDigest"], routingLeaseExpiresAt=int(time.time()) + 300)
        self._put(item)
        with self.assertRaises(WebhookError): self.routing.submit_result(self.user_id, self.device_id, result["eventId"], dict(claim, botId="bot-1", confidence=.9, reasoningEffort="low"))
        self.assertFalse(self.sqs.send_message.called)

    def _claimed_event(self):
        self.routing.register_router(self.user_id, self.device_id, {"schemaVersion": 1, "appVersion": "1.0", "modelId": MODEL_ID, "modelRevision": MODEL_REVISION})
        created = self.ingress.ingest(self._json(), self.source_id)
        claim = self.routing.list_requests(self.user_id, self.device_id)["requests"][0]
        item = self.data_table.get_item(Key=event_key(self.user_id, created["eventId"]))["Item"]
        item.update(status="routing", routingDeviceId=self.device_id, routingLeaseToken=claim["leaseToken"], requestDigest=claim["requestDigest"], routingLeaseExpiresAt=int(time.time()) + 300)
        self._put(item)
        result = {"requestDigest": claim["requestDigest"], "leaseToken": claim["leaseToken"],
                  "botId": "bot-1", "reasoningEffort": "low", "confidence": .9,
                  "probabilities": {"bot-1": .95, "clarify": .05}, "reasoningConfidence": .9,
                  "reasoningDeferred": False, "suggestedReasoningEffort": "low", "modelId": MODEL_ID, "modelRevision": MODEL_REVISION}
        return item, result

    def test_valid_local_choice_dispatches_and_abstention_waits_for_manual_review(self):
        item, result = self._claimed_event()
        with patch.dict(self.routing.submit_result.__globals__, {"require_request_consent": lambda _: None}):
            response = self.routing.submit_result(self.user_id, self.device_id, item["id"], result)
        self.assertEqual(response["status"], "dispatch_pending")
        self.assertEqual(json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])["type"], "WEBHOOK_DISPATCH")
        self.sqs.reset_mock()
        result.update(botId=None, confidence=.2, probabilities={"bot-1": .4, "clarify": .6})
        response = self.routing.submit_result(self.user_id, self.device_id, item["id"], result)
        self.assertEqual(response["status"], "needs_review")
        self.assertFalse(self.sqs.send_message.called)

    def test_stale_catalog_expired_lease_bad_effort_and_nan_never_queue(self):
        item, result = self._claimed_event()
        for field, invalid in (("reasoningEffort", "medium"), ("confidence", float("nan")), ("modelRevision", "unreviewed"), ("botId", "outside-account")):
            with self.assertRaises(WebhookError): self.routing.submit_result(self.user_id, self.device_id, item["id"], dict(result, **{field: invalid}))
        item["routingLeaseExpiresAt"] = 0; self._put(item)
        with self.assertRaises(WebhookError): self.routing.submit_result(self.user_id, self.device_id, item["id"], result)
        item["routingLeaseExpiresAt"] = int(time.time()) + 300; self._put(item)
        bot = self.data_table.items[("USER#owner-1", "BOT#bot-1")]; bot["prompt"] = "New purpose"
        with self.assertRaises(WebhookError): self.routing.submit_result(self.user_id, self.device_id, item["id"], result)
        self.assertFalse(self.sqs.send_message.called)

    def test_source_create_rotate_one_time_secrets_and_disable_retains_owner_scoping(self):
        create = patch.object(self.sources.catalog, "_create_secret", side_effect=["arn:aws:secretsmanager:r:a:secret:one", "arn:aws:secretsmanager:r:a:secret:two"])
        with create, patch.object(self.sources.catalog, "_delete_secret") as delete:
            saved = self.sources.save_source(self.user_id, {"name": "Sensor"}, {})
            source_id = saved["source"]["id"]
            self.assertGreater(len(saved["credential"]), 30)
            self.assertGreater(len(saved["signingSecret"]), 30)
            self.assertNotIn("credential", self.sources.list_sources(self.user_id, {}))
            rotated = self.sources.rotate_source(self.user_id, source_id, {})
            self.assertNotEqual(rotated["credential"], saved["credential"])
            self.assertEqual(rotated["source"]["credentialVersion"], 2)
            self.assertTrue(delete.called)
            disabled = self.sources.save_source(self.user_id, {"enabled": False}, {}, source_id)
            self.assertFalse(disabled["source"]["enabled"])
            self.assertNotIn("credential", disabled)

    def test_unsigned_pebble_retry_boundary_changes_keep_one_recording_identity(self):
        self.source["kind"] = "pebble"; self._put(self.source)
        event = self._pebble()
        event["headers"] = {"content-type": "multipart/form-data; boundary=boundary", "authorization": "Bearer bearer-secret"}
        first = self.ingress.ingest(event, self.source_id)
        event["body"] = event["body"].replace("boundary", "different-boundary")
        event["headers"]["content-type"] = "multipart/form-data; boundary=different-boundary"
        second = self.ingress.ingest(event, self.source_id)
        self.assertEqual(first["eventId"], second["eventId"])

    def test_unicode_bot_metadata_fits_local_helper_byte_limits(self):
        from shared.webhooks import eligible_bots
        self.data_table.items[("USER#owner-1", "BOT#bot-1")].update(name="你好" * 200, prompt="🚀" * 1500)
        bot = eligible_bots(self.data_table, self.user_id, self.source)[0]
        self.assertLessEqual(len(bot["name"].encode()), 200)
        self.assertLessEqual(len(bot["description"].encode()), 2000)

    def test_choice_confidence_is_official_concentration_and_not_max_probability(self):
        item, result = self._claimed_event()
        with patch.dict(self.routing.submit_result.__globals__, {"require_request_consent": lambda _: None}):
            # Two labels: (2 * .9 - 1) / (2 - 1) = .8, not .9.
            result.update(confidence=.8, probabilities={"bot-1": .9, "clarify": .1})
            self.assertEqual(self.routing.submit_result(self.user_id, self.device_id, item["id"], result)["status"], "dispatch_pending")
            result["confidence"] = .9
            with self.assertRaises(WebhookError): self.routing.submit_result(self.user_id, self.device_id, item["id"], result)

    def test_fixed_ingress_persists_sparse_outbox_when_initial_sqs_handoff_fails(self):
        self.source.update(routingMode="fixed", fallbackBotId="bot-1"); self._put(self.source)
        self.sqs.send_message.side_effect = TimeoutError()
        try:
            with self.assertRaises(TimeoutError): self.ingress.ingest(self._json(), self.source_id)
            events = [item for item in self.data_table.items.values() if item.get("entity") == "WEBHOOK_EVENT"]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["status"], "dispatch_pending")
            self.assertEqual(events[0]["webhookDispatchPk"], "PENDING")
        finally:
            self.sqs.send_message.side_effect = None

    def test_invalid_unicode_and_non_ascii_credentials_are_cleanly_rejected(self):
        with self.assertRaises(WebhookError) as error:
            self.ingress.ingest(self._json({"id": "invalid-unicode", "text": "\ud800"}), self.source_id)
        self.assertEqual(error.exception.status, 400)
        event = self._json(); event["headers"]["authorization"] = "Bearer 你好"
        with self.assertRaises(WebhookError) as error: self.ingress.ingest(event, self.source_id)
        self.assertEqual(error.exception.status, 401)
        event["headers"].update({"x-webhook-timestamp": str(int(time.time())), "x-webhook-signature": "sha256=你好"})
        with self.assertRaises(WebhookError) as error: self.ingress.ingest(event, self.source_id)
        self.assertEqual(error.exception.status, 401)

    def test_uncertain_reasoning_uses_saved_effort_and_retains_raw_prediction(self):
        item, result = self._claimed_event()
        result.update(reasoningConfidence=.25, reasoningDeferred=True, suggestedReasoningEffort="max", reasoningEffort="high")
        with patch.dict(self.routing.submit_result.__globals__, {"require_request_consent": lambda _: None}):
            response = self.routing.submit_result(self.user_id, self.device_id, item["id"], result)
        self.assertEqual(response["status"], "dispatch_pending")
        decision = self.data_table.updated[-1]["ExpressionAttributeValues"][":decision"]
        self.assertEqual(decision["reasoningEffort"], "high")
        self.assertEqual(decision["suggestedReasoningEffort"], "max")
        self.assertTrue(decision["reasoningDeferred"])
        self.assertEqual(float(decision["reasoningConfidence"]), .25)

    def test_reasoning_metadata_missing_is_conservative_and_malformed_is_rejected(self):
        from shared.webhooks import reasoning_decision
        default = reasoning_decision({"reasoningEffort": "max"}, {"reasoningEffort": "low"})
        self.assertEqual(default["reasoningEffort"], "low")
        self.assertEqual(default["suggestedReasoningEffort"], "max")
        self.assertTrue(default["reasoningDeferred"])
        valid = {"reasoningEffort": "low", "reasoningConfidence": .9, "reasoningDeferred": False, "suggestedReasoningEffort": "low"}
        for fields in ({"reasoningConfidence": float("nan")}, {"reasoningConfidence": -.1},
                       {"reasoningDeferred": "false"}, {"suggestedReasoningEffort": "medium"},
                       {"reasoningConfidence": .4}, {"suggestedReasoningEffort": "max"},
                       {"reasoningEffort": []}):
            with self.assertRaises(WebhookError): reasoning_decision({**valid, **fields}, {"reasoningEffort": "high"})
        with self.assertRaises(WebhookError):
            reasoning_decision({**valid, "reasoningConfidence": .4, "reasoningDeferred": True}, {"reasoningEffort": "high"})

    def test_no_selected_bot_may_defer_confident_effort_without_any_execution(self):
        from shared.webhooks import reasoning_decision
        result = reasoning_decision({"reasoningEffort": "high", "reasoningConfidence": .95,
                                     "reasoningDeferred": True, "suggestedReasoningEffort": "max"}, None)
        self.assertTrue(result["reasoningDeferred"])
        self.assertEqual(result["suggestedReasoningEffort"], "max")

    def test_reasoning_gate_boundary_accepts_confident_formal_max_at_half(self):
        from shared.webhooks import reasoning_decision
        decision = reasoning_decision({"reasoningEffort": "max", "reasoningConfidence": .5655,
                                       "reasoningDeferred": False, "suggestedReasoningEffort": "max"}, {"reasoningEffort": "high"})
        self.assertEqual(decision["reasoningEffort"], "max")
        self.assertFalse(decision["reasoningDeferred"])

    def test_generic_message_field_path_extracts_nested_text_and_ignores_control_fields(self):
        self.source["textPath"] = "event.message.text"; self._put(self.source)
        payload = {"id": "nested-1", "event": {"message": {"text": "A nested question"}},
                   "userId": "another-owner", "botId": "other-bot", "reasoningEffort": "max"}
        result = self.ingress.ingest(self._json(payload), self.source_id)
        stored = self.data_table.get_item(Key=event_key(self.user_id, result["eventId"]))["Item"]
        self.assertEqual(stored["text"], "A nested question")
        self.assertEqual(stored["userId"], self.user_id)
        self.assertNotIn("reasoningEffort", stored)
        self.assertNotIn("botId", stored)

    def test_message_path_rejects_missing_nontext_arrays_and_unsafe_or_unbounded_paths(self):
        from shared.webhooks import validate_text_path
        self.source["textPath"] = "event.message.text"; self._put(self.source)
        for payload in ({"event": {}}, {"event": {"message": {"text": 1}}},
                        {"event": {"message": [{"text": "array"}]}}):
            with self.assertRaises(WebhookError) as error: self.ingress.ingest(self._json(payload), self.source_id)
            self.assertEqual(error.exception.status, 422)
        for path in ("event..text", "event.__proto__.text", "event.constructor", "event.prototype",
                     "event.\ntext", "event.messages[0].text", ".text", "a." * 8 + "text", "🚀" * 17, ["event", "text"]):
            with self.assertRaises(WebhookError): validate_text_path(path)
        self.assertEqual(validate_text_path("event.message.text"), "event.message.text")
        self.assertIsNone(validate_text_path(""))

    def test_message_path_source_policy_is_retained_on_update_and_can_be_cleared(self):
        with patch.object(self.sources.catalog, "_create_secret", return_value="arn:aws:secretsmanager:r:a:secret:one"):
            saved = self.sources.save_source(self.user_id, {"kind": "generic", "textPath": "event.message.text"}, {})
        source_id = saved["source"]["id"]
        self.assertEqual(saved["source"]["textPath"], "event.message.text")
        updated = self.sources.save_source(self.user_id, {"name": "Renamed"}, {}, source_id)
        self.assertEqual(updated["source"]["textPath"], "event.message.text")
        cleared = self.sources.save_source(self.user_id, {"textPath": ""}, {}, source_id)
        self.assertNotIn("textPath", cleared["source"])
