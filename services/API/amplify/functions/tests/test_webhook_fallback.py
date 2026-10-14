from __future__ import annotations

import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from api_test_case import ApiTestCase
from shared.webhooks import (
    MODEL_ID,
    MODEL_REVISION,
    WebhookError,
    event_key,
    owner_key,
    source_key,
)


class WebhookFallbackTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.ingress = SimpleNamespace(**self.public_handler.incoming_webhook.__globals__)
        self.routing = SimpleNamespace(**self.handler.authenticated_routes.webhook_route.__globals__)
        self.sources = SimpleNamespace(**self.routing.save_source.__globals__)
        self.user_id, self.source_id, self.device_id = "owner", str(uuid.uuid4()), str(uuid.uuid4())
        self.source = {**source_key(self.user_id, self.source_id), "entity": "WEBHOOK_SOURCE",
            "id": self.source_id, "userId": self.user_id, "name": "Index", "kind": "generic",
            "enabled": True, "routingMode": "local", "authentication": "either",
            "allowedBotIds": ["bot-1", "bot-2"], "fallbackBotId": "bot-2",
            "secretArn": "arn:aws:secretsmanager:r:a:secret:source", "credentialVersion": 1,
            "mutationRevision": 1, "createdAt": "2026-10-14T12:00:00Z", "updatedAt": "2026-10-14T12:00:00Z"}
        self._put(self.source)
        self._put({**owner_key(self.source_id), "entity": "WEBHOOK_SOURCE_OWNER", "userId": self.user_id})
        for bot_id, effort in (("bot-1", "high"), ("bot-2", "low")):
            self._put({"pk": "USER#owner", "sk": f"BOT#{bot_id}", "entity": "BOT",
                       "id": bot_id, "name": bot_id, "prompt": "Answer questions.", "reasoningEffort": effort})
        secret = patch.object(self.ingress.catalog, "_secret_document",
                              return_value={"credential": "bearer", "signingSecret": "signing"})
        secret.start()
        self.addCleanup(secret.stop)

    def _put(self, item):
        self.data_table.items[(item["pk"], item["sk"])] = dict(item)

    def _claim(self):
        self.routing.register_router(self.user_id, self.device_id,
            {"schemaVersion": 1, "appVersion": "test", "modelId": MODEL_ID, "modelRevision": MODEL_REVISION})
        incoming = self.ingress.ingest({"body": json.dumps({"id": "recording", "text": "An unclear question"}),
            "headers": {"content-type": "application/json", "authorization": "Bearer bearer"}}, self.source_id)
        claim = self.routing.list_requests(self.user_id, self.device_id)["requests"][0]
        item = self.data_table.get_item(Key=event_key(self.user_id, incoming["eventId"]))["Item"]
        item.update(status="routing", routingDeviceId=self.device_id, routingLeaseToken=claim["leaseToken"],
                    requestDigest=claim["requestDigest"], routingLeaseExpiresAt=int(time.time()) + 300)
        self._put(item)
        result = {"modelId": MODEL_ID, "modelRevision": MODEL_REVISION,
            "requestDigest": claim["requestDigest"], "leaseToken": claim["leaseToken"], "botId": None,
            "confidence": .55, "probabilities": {"bot-1": .2, "bot-2": .1, "clarify": .7},
            "reasoningEffort": "high", "reasoningConfidence": .95,
            "reasoningDeferred": True, "suggestedReasoningEffort": "max"}
        return item, result

    def _submit(self, item, result):
        with patch.dict(self.routing.submit_result.__globals__, {"require_request_consent": lambda _: None}):
            return self.routing.submit_result(self.user_id, self.device_id, item["id"], result)

    def _decision(self):
        return self.data_table.updated[-1]["ExpressionAttributeValues"][":decision"]

    def test_local_fallback_is_optional_explicit_owned_and_allowlisted_on_create_and_edit(self):
        with patch.object(self.sources.catalog, "_create_secret", return_value="arn:aws:secretsmanager:r:a:secret:new"):
            unset = self.sources.save_source(self.user_id, {"name": "No automatic default", "routingMode": "local"}, {})
            self.assertNotIn("fallbackBotId", unset["source"])
            chosen = self.sources.save_source(self.user_id, {"routingMode": "local", "allowedBotIds": ["bot-2"], "fallbackBotId": "bot-2"}, {})
            self.assertEqual(chosen["source"]["fallbackBotId"], "bot-2")
            for fields in ({"fallbackBotId": "foreign"}, {"allowedBotIds": ["bot-1"], "fallbackBotId": "bot-2"}):
                with self.assertRaises(WebhookError):
                    self.sources.save_source(self.user_id, fields, {})
                with self.assertRaises(WebhookError):
                    self.sources.save_source(self.user_id, fields, {}, self.source_id)
        cleared = self.sources.save_source(self.user_id, {"fallbackBotId": None}, {}, self.source_id)
        self.assertNotIn("fallbackBotId", cleared["source"])

    def test_abstention_uses_owner_fallback_saved_effort_and_retains_only_validated_model_fields(self):
        item, result = self._claim()
        response = self._submit(item, result)
        self.assertEqual(response["status"], "dispatch_pending")
        decision = self._decision()
        self.assertEqual(decision["method"], "local_fallback")
        self.assertEqual(decision["botId"], "bot-2")
        self.assertEqual(decision["reasoningEffort"], "low")
        self.assertEqual(decision["fallbackReason"], "local_abstention")
        self.assertIsNone(decision["localDecision"]["botId"])
        self.assertEqual(decision["localDecision"]["reasoningEffort"], "high")
        self.assertEqual(decision["localDecision"]["suggestedReasoningEffort"], "max")
        self.assertEqual(float(decision["localDecision"]["confidence"]), .55)
        self.assertNotIn("confidence", decision)
        self.assertNotIn("requestDigest", decision["localDecision"])
        self.assertNotIn("leaseToken", decision["localDecision"])
        self.assertEqual(json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])["type"], "WEBHOOK_DISPATCH")

    def test_valid_local_choice_below_server_gate_falls_back_without_inheriting_its_effort(self):
        item, result = self._claim()
        result.update(botId="bot-1", probabilities={"bot-1": .7, "bot-2": .1, "clarify": .2},
                      reasoningEffort="max", reasoningDeferred=False)
        self._submit(item, result)
        decision = self._decision()
        self.assertEqual(decision["botId"], "bot-2")
        self.assertEqual(decision["reasoningEffort"], "low")
        self.assertEqual(decision["fallbackReason"], "routing_gate")
        self.assertEqual(decision["localDecision"]["botId"], "bot-1")
        self.assertEqual(decision["localDecision"]["reasoningEffort"], "max")

    def test_no_configured_fallback_leaves_abstention_for_manual_review(self):
        self.source.pop("fallbackBotId")
        self._put(self.source)
        item, result = self._claim()
        self.assertEqual(self._submit(item, result)["status"], "needs_review")
        self.assertEqual(self._decision()["method"], "local")
        self.assertFalse(self.sqs.send_message.called)

    def test_configured_local_fallback_still_waits_for_a_mac_result(self):
        incoming = self.ingress.ingest({"body": json.dumps({"id": "offline-recording", "text": "A question"}),
            "headers": {"content-type": "application/json", "authorization": "Bearer bearer"}}, self.source_id)
        self.assertEqual(incoming["status"], "awaiting_routing")
        self.assertFalse(self.sqs.send_message.called)

    def test_confident_eligible_model_route_is_not_replaced_by_fallback(self):
        item, result = self._claim()
        result.update(botId="bot-1", confidence=.775, probabilities={"bot-1": .85, "bot-2": .05, "clarify": .1},
                      reasoningEffort="max", reasoningDeferred=False)
        self._submit(item, result)
        self.assertEqual(self._decision()["method"], "local")
        self.assertEqual(self._decision()["botId"], "bot-1")
        self.assertEqual(self._decision()["reasoningEffort"], "max")

    def test_changing_fallback_after_claim_rejects_stale_callback(self):
        item, result = self._claim()
        for fallback in (None, "bot-1"):
            self.source["fallbackBotId"] = fallback
            self._put(self.source)
            with self.assertRaises(WebhookError) as error:
                self._submit(item, result)
            self.assertEqual(error.exception.status, 409)
        self.assertFalse(self.sqs.send_message.called)

    def test_credential_rotation_does_not_change_routing_policy_or_block_accepted_message(self):
        item, result = self._claim()
        self.source.update(credentialVersion=2, secretArn="arn:aws:secretsmanager:r:a:secret:rotated", updatedAt="later")
        self._put(self.source)
        self.assertEqual(self._submit(item, result)["status"], "dispatch_pending")

    def test_revoked_source_or_fallback_membership_stops_callback(self):
        item, result = self._claim()
        for fields in ({"enabled": False}, {"enabled": True, "allowedBotIds": ["bot-1"]}):
            self.source.update(fields)
            self._put(self.source)
            with self.assertRaises(WebhookError):
                self._submit(item, result)
        self.assertFalse(self.sqs.send_message.called)

    def test_fallback_requires_consent_before_persisting_dispatch(self):
        item, result = self._claim()
        updates = len(self.data_table.updated)
        def denied(_):
            raise self.routing.ApiError(403, "Consent is required")
        with (patch.dict(self.routing.submit_result.__globals__, {"require_request_consent": denied}),
              self.assertRaises(self.routing.ApiError)):
            self.routing.submit_result(self.user_id, self.device_id, item["id"], result)
        self.assertEqual(len(self.data_table.updated), updates)
        self.assertFalse(self.sqs.send_message.called)

    def test_fallback_does_not_bypass_invalid_model_or_foreign_selected_bot(self):
        item, result = self._claim()
        for fields in ({"modelRevision": "wrong"}, {"confidence": float("nan")}, {"botId": "foreign"}):
            with self.assertRaises(WebhookError):
                self._submit(item, {**result, **fields})
        self.assertFalse(self.sqs.send_message.called)

    def test_manual_review_retains_original_local_model_snapshot(self):
        item, result = self._claim()
        self._submit(item, result)
        original = self._decision()["localDecision"]
        item.update(status="needs_review", routingDecision=self._decision())
        self._put(item)
        self.source.pop("fallbackBotId")
        self._put(self.source)
        with patch.dict(self.routing.manual_route.__globals__, {"require_request_consent": lambda _: None}):
            self.routing.manual_route(self.user_id, item["id"], {"botId": "bot-1", "reasoningEffort": "high"})
        self.assertEqual(self._decision()["method"], "manual")
        self.assertEqual(self._decision()["localDecision"], original)
        self.assertEqual(str(uuid.UUID(self._decision()["manualAttemptId"])), self._decision()["manualAttemptId"])
