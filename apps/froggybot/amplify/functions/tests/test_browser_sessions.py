from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
import threading
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from api_test_case import ApiTestCase, ConditionalCheckFailedException


class Condition:
    def __init__(self, name, operator=None, value=None):
        self.name, self.operator, self.value = name, operator, value

    def eq(self, value):
        return Condition(self.name, "eq", value)

    def not_exists(self):
        return Condition(self.name, "absent")

    def is_in(self, value):
        return Condition(self.name, "in", value)

    def matches(self, item):
        if self.operator == "absent":
            return self.name not in item
        if self.operator == "in":
            return item.get(self.name) in self.value
        return item.get(self.name) == self.value


class BrowserTable:
    def __init__(self):
        self.items, self.writes = {}, []
        self.name = "test-table"
        self.lock = threading.Lock()
        client = SimpleNamespace(
            exceptions=SimpleNamespace(ConditionalCheckFailedException=ConditionalCheckFailedException),
            get_paginator=lambda _name: SimpleNamespace(paginate=self.pages),
        )
        self.meta = SimpleNamespace(client=client)

    def get_item(self, *, Key, **kwargs):
        assert kwargs.get("ConsistentRead") is True
        with self.lock:
            return {"Item": copy.deepcopy(self.items.get((Key["pk"], Key["sk"])))}

    def put_item(self, *, Item, ConditionExpression=None):
        with self.lock:
            key = Item["pk"], Item["sk"]
            if ConditionExpression and not ConditionExpression.matches(self.items.get(key, {})):
                raise ConditionalCheckFailedException()
            self.items[key] = copy.deepcopy(Item)
            self.writes.append(copy.deepcopy(Item))

    def pages(self, **kwargs):
        assert kwargs["ConsistentRead"] is True
        matching = [item for item in self.items.values()
                    if kwargs["KeyConditionExpression"].matches(item)]
        # An empty filtered page must not stop pagination.
        yield {"Items": []}
        yield {"Items": [item for item in matching if kwargs["FilterExpression"].matches(item)]}


class ModuleGlobals:
    """Patch a route retained by the existing fixture after sys.modules is restored."""
    def __init__(self, values):
        object.__setattr__(self, "values", values)

    def __getattr__(self, name):
        try:
            return self.values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self.values[name] = value

    def __delattr__(self, name):
        del self.values[name]


class BrowserSessionTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.module = importlib.import_module("shared.browser_sessions")
        self.store_module = importlib.import_module("shared.browser_session_store")
        route = self.handler.authenticated_routes.browser_session_route
        self.routes = ModuleGlobals(route.__globals__)
        conditions = ModuleType("boto3.dynamodb.conditions")
        conditions.Attr = conditions.Key = Condition
        self.enterContext(patch.dict(sys.modules, {"boto3.dynamodb.conditions": conditions}))
        self.table = BrowserTable()
        self.table.put_item(Item={"pk": "USER#user-1", "sk": "BOT#bot-1", "entity": "BOT",
                                  "id": "bot-1", "name": "Engineer", "toolIds": ["browser"]})
        self.catalog = MagicMock()
        self.catalog.resolve_for_runtime.return_value = []
        self.catalog.resolve_tools_for_runtime.return_value = [
            {"runtime": {"kind": "agentcore", "name": "browser"}},
        ]
        self.enterContext(patch.object(self.store_module, "CatalogService", return_value=self.catalog))
        self.dp, self.cp = MagicMock(), MagicMock()
        missing = type("NotFound", (Exception,), {})
        self.dp.exceptions.ResourceNotFoundException = missing
        self.cp.exceptions.ResourceNotFoundException = missing
        self.dp.start_browser_session.return_value = {"sessionId": "session1"}
        self.dp.get_browser_session.return_value = {
            "name": self.module.managed_session_name("user-1", "bot-1"), "status": "READY",
            "streams": {"automationStream": {"streamStatus": "ENABLED"}},
        }
        self.cp.create_browser_profile.return_value = {"profileId": "frogbot_test-0123456789"}
        self.cp.get_browser_profile.return_value = {"status": "READY", "lastSavedBrowserSessionId": "session1"}
        self.now = 1789000000
        self.signer = MagicMock(return_value="https://example.test/live?X-Amz-Security-Token=SECRET")
        self.service = self.module.BrowserSessionService(
            self.table, self.dp, "user-1", "bot-1", control=self.cp,
            catalog=self.catalog, signer=self.signer, clock=lambda: self.now,
        )
        self.enqueue = MagicMock(return_value={"turnId": "turn-1", "status": "awaiting_approval"})

    def assert_error(self, status, callback):
        with self.assertRaises(self.module.BrowserSessionError) as caught:
            callback()
        self.assertEqual(caught.exception.status_code, status)

    def record(self):
        return self.service.store.read()

    def test_get_closed_does_not_launch_or_sign(self):
        self.assertEqual(self.service.get()["status"], "closed")
        self.dp.assert_not_called()
        self.dp.start_browser_session.assert_not_called()
        self.signer.assert_not_called()

    def test_open_only_stores_references_and_disables_automation(self):
        view = self.service.open()
        self.assertEqual(view["status"], "human_control")
        self.assertIn("liveViewUrl", view)
        self.dp.update_browser_stream.assert_called_once_with(
            browserIdentifier="aws.browser.v1", sessionId="session1",
            streamUpdate={"automationStreamUpdate": {"streamStatus": "DISABLED"}},
        )
        saved = json.dumps(self.table.writes)
        for secret in ("SECRET", "X-Amz", "liveViewUrl", "cookies", "password"):
            self.assertNotIn(secret, saved)
        self.assertEqual(self.record()["sessionExpiresAt"], self.now + 3600)

    def test_open_refresh_reuses_session_without_extending_its_lifetime(self):
        self.service.open()
        expiry = self.record()["sessionExpiresAt"]
        self.now += 240
        self.service.open()
        self.assertEqual(self.dp.start_browser_session.call_count, 1)
        self.assertEqual(self.signer.call_count, 2)
        self.assertEqual(self.record()["sessionExpiresAt"], expiry)
        self.assertNotIn("liveViewUrl", self.service.get())

    def test_unknown_or_shared_bot_does_not_inherit_credentials(self):
        del self.table.items[("USER#user-1", "BOT#bot-1")]
        self.table.put_item(Item={"pk": "USER#someone-else", "sk": "BOT#bot-1", "entity": "BOT"})
        self.assert_error(404, self.service.open)
        self.dp.start_browser_session.assert_not_called()

    def test_browser_capability_is_required(self):
        self.catalog.resolve_tools_for_runtime.return_value = [{"runtime": {"kind": "local", "name": "browser"}}]
        self.assert_error(409, self.service.open)

    def test_skill_required_browser_is_an_authorized_capability(self):
        self.catalog.resolve_for_runtime.return_value = [{"requiredToolIds": ["skill_browser"]}]
        self.service.open()
        self.catalog.resolve_tools_for_runtime.assert_called_with("user-1", ["browser", "skill_browser"])

    def test_unpinned_legacy_skills_use_same_read_only_resolution_as_worker(self):
        self.catalog.validate_and_pin.return_value = {"web-skill": 2}
        self.service.open()
        self.catalog.validate_and_pin.assert_called_with("user-1", [])
        self.catalog.resolve_for_runtime.assert_called_with({"web-skill": 2})

    def test_removed_tool_still_allows_owned_close_and_forget(self):
        self.service.open()
        self.service.resume(True, self.enqueue)
        self.catalog.resolve_tools_for_runtime.return_value = []
        self.assert_error(409, self.service.open)
        self.assertTrue(self.service.close()["hasSavedLogin"])
        self.assertFalse(self.service.close(forget=True)["hasSavedLogin"])

    def test_all_group_contexts_are_rejected_without_creating_a_record(self):
        for group in ("work-group", "", False):
            self.assert_error(409, lambda group=group: self.module.BrowserSessionService(
                self.table, self.dp, "user-1", "bot-1", group))
            self.assertIsNone(self.module.runtime_browser_session(
                self.table, self.dp, "user-1", "bot-1", group))
        self.dp.start_browser_session.assert_not_called()

    def test_private_keys_and_session_names_are_bound_to_user_and_bot(self):
        self.assertNotEqual(self.store_module.context_key("user-1", "bot-1"),
                            self.store_module.context_key("user-2", "bot-1"))
        self.assertNotEqual(self.store_module.context_key("user-1", "bot-1"),
                            self.store_module.context_key("user-1", "bot-2"))
        actor = hashlib.sha256(b"user:user-1").hexdigest()
        expected = "frogbot-browser-" + hashlib.sha256(f"{actor}:bot:bot-1".encode()).hexdigest()[:48]
        self.service.open()
        self.assertEqual(self.dp.start_browser_session.call_args.kwargs["name"], expected)
        self.assertLessEqual(len(expected), 100)

    def test_active_turn_even_on_later_page_blocks_open(self):
        for state in ("PENDING", "RUNNING", "WAITING", "NEEDS_INPUT", "AWAITING_APPROVAL"):
            self.table.put_item(Item={"pk": "CHAT#user-1#bot-1", "sk": "TURN#old", "status": state})
            self.assert_error(409, self.service.open)
        self.dp.start_browser_session.assert_not_called()

    def test_runtime_without_managed_record_does_not_launch(self):
        self.assertIsNone(self.module.runtime_browser_session(self.table, self.dp, "user-1", "bot-1"))
        self.dp.start_browser_session.assert_not_called()

    def test_send_preflight_is_database_only_and_allows_resume_enqueue(self):
        check = lambda: self.module.ensure_browser_send_allowed(self.table, "user-1", "bot-1")
        check()
        self.service.open()
        self.dp.reset_mock()
        self.assert_error(409, check)
        self.service.store.write(self.record(), status="READY", resumeState="ENQUEUEING")
        check()
        self.service.store.write(self.record(), resumeState="UNCERTAIN")
        self.assert_error(409, check)
        self.dp.get_browser_session.assert_not_called()
        self.dp.start_browser_session.assert_not_called()

    def test_runtime_rejects_human_control_and_intermediate_states(self):
        self.service.open()
        for status in ("HUMAN_CONTROL", "OPENING", "RESUMING"):
            self.service.store.write(self.record(), status=status)
            self.assert_error(409, self.service.runtime_session)

    def test_runtime_returns_only_binding_after_resume_and_keeps_approval(self):
        self.service.open()
        view = self.service.resume(False, self.enqueue)
        self.assertEqual(view["resumedTurnId"], "turn-1")
        self.assertFalse(view["hasSavedLogin"])
        self.cp.create_browser_profile.assert_not_called()
        self.dp.save_browser_session_profile.assert_not_called()
        binding = self.service.runtime_session()
        self.assertEqual(set(binding), {"browserIdentifier", "sessionId", "sessionName"})
        self.assertIn("not new authorization", self.enqueue.call_args.args[0])
        self.assertIn("verify completed external actions", self.enqueue.call_args.args[0])

    def test_remember_true_saves_profile_and_tag(self):
        self.service.open()
        self.service.resume(True, self.enqueue)
        self.assertTrue(self.service.get()["hasSavedLogin"])
        self.assertEqual(self.record()["profileVersion"], 1)
        self.assertEqual(self.cp.create_browser_profile.call_args.kwargs["tags"], {"frogbot:managed-by": "FrogBot"})
        self.assertEqual(self.dp.save_browser_session_profile.call_args.kwargs["profileIdentifier"],
                         "frogbot_test-0123456789")

    def test_async_profile_save_can_be_polled_without_resaving_or_double_enqueue(self):
        self.service.open()
        self.cp.get_browser_profile.return_value = {"status": "SAVING"}
        self.assertEqual(self.service.resume(True, self.enqueue)["status"], "resuming")
        self.enqueue.assert_not_called()
        self.assert_error(409, lambda: self.service.resume(False, self.enqueue))
        self.cp.get_browser_profile.return_value = {"status": "READY", "lastSavedBrowserSessionId": "session1"}
        self.assertEqual(self.service.resume(True, self.enqueue)["status"], "ready")
        self.assertEqual(self.dp.save_browser_session_profile.call_count, 1)
        self.assertEqual(self.enqueue.call_count, 1)

    def test_live_aws_save_ack_without_timestamp_uses_get_profile_completion(self):
        self.service.open()
        # Observed from two real AWS saves: HTTP 200 omits lastUpdatedAt.
        self.dp.save_browser_session_profile.return_value = {
            "browserIdentifier": "aws.browser.v1", "sessionId": "session1",
            "profileIdentifier": "frogbot_test-0123456789",
        }
        self.assertEqual(self.service.resume(True, self.enqueue)["status"], "ready")
        self.enqueue.assert_called_once()

    def test_duplicate_resume_returns_same_turn_without_repeating_actions(self):
        self.service.open()
        first = self.service.resume(True, self.enqueue)
        self.assertEqual(self.service.resume(True, self.enqueue), first)
        self.assertEqual(self.enqueue.call_count, 1)
        self.assertEqual(self.dp.save_browser_session_profile.call_count, 1)

    def test_concurrent_resume_and_open_cannot_repeat_side_effects(self):
        self.service.open()
        entered, finish = threading.Event(), threading.Event()
        def enqueue(_text):
            entered.set()
            self.assertTrue(finish.wait(2))
            return {"turnId": "once"}
        with __import__("concurrent.futures").futures.ThreadPoolExecutor() as pool:
            future = pool.submit(self.service.resume, False, enqueue)
            self.assertTrue(entered.wait(2))
            self.assert_error(409, lambda: self.service.resume(False, self.enqueue))
            self.assert_error(409, self.service.open)
            self.assert_error(409, self.service.close)
            finish.set()
            self.assertEqual(future.result()["resumedTurnId"], "once")
        self.enqueue.assert_not_called()

    def test_uncertain_queue_result_is_not_retried(self):
        self.service.open()
        self.enqueue.side_effect = TimeoutError("secret response lost")
        self.assert_error(503, lambda: self.service.resume(False, self.enqueue))
        self.assertEqual(self.record()["resumeState"], "UNCERTAIN")
        self.assertEqual(self.service.get()["status"], "resuming")
        self.assertNotIn("secret", json.dumps(self.record()))
        self.assert_error(409, lambda: self.service.resume(False, self.enqueue))
        self.assert_error(409, self.service.runtime_session)
        self.assertEqual(self.enqueue.call_count, 1)

    def test_profile_save_failure_never_enables_automation_or_enqueues(self):
        self.service.open()
        self.dp.update_browser_stream.reset_mock()
        self.dp.save_browser_session_profile.side_effect = TimeoutError("cookies=secret")
        self.assert_error(503, lambda: self.service.resume(True, self.enqueue))
        self.enqueue.assert_not_called()
        self.dp.update_browser_stream.assert_not_called()
        self.assertNotIn("cookies", json.dumps(self.record()))

    def test_stale_profile_ready_state_does_not_claim_login_was_saved(self):
        self.service.open()
        self.cp.get_browser_profile.return_value = {"status": "READY", "lastSavedBrowserSessionId": "old-session"}
        view = self.service.resume(True, self.enqueue)
        self.assertEqual(view["status"], "resuming")
        self.assertFalse(view["hasSavedLogin"])
        self.enqueue.assert_not_called()

    def test_close_keeps_profile_and_next_runtime_turn_restores_it(self):
        self.service.open()
        self.service.resume(True, self.enqueue)
        self.assertTrue(self.service.close()["hasSavedLogin"])
        self.service.runtime_session()
        self.assertEqual(self.dp.start_browser_session.call_count, 2)
        self.assertEqual(self.dp.start_browser_session.call_args.kwargs["profileConfiguration"],
                         {"profileIdentifier": "frogbot_test-0123456789"})
        self.cp.delete_browser_profile.assert_not_called()

    def test_expired_profile_session_restores_with_new_idempotency_token(self):
        self.service.open()
        self.service.resume(True, self.enqueue)
        original = self.record()["startToken"]
        self.now += 3601
        self.assertEqual(self.service.get()["status"], "expired")
        self.service.runtime_session()
        self.assertNotEqual(self.record()["startToken"], original)

    def test_expired_or_closed_without_saved_login_uses_legacy_browser(self):
        self.service.open()
        self.service.resume(False, self.enqueue)
        self.now += 3601
        self.assertIsNone(self.service.runtime_session())
        self.assertEqual(self.dp.start_browser_session.call_count, 1)

    def test_forget_stops_session_then_deletes_profile_and_removes_references(self):
        self.service.open()
        self.service.resume(True, self.enqueue)
        order = []
        self.dp.stop_browser_session.side_effect = lambda **_kw: order.append("stop")
        self.cp.delete_browser_profile.side_effect = lambda **_kw: order.append("delete")
        view = self.service.close(forget=True)
        self.assertEqual(order, ["stop", "delete"])
        self.assertEqual(view["status"], "closed")
        self.assertFalse(view["hasSavedLogin"])
        self.assertIsNone(self.record()["profileId"])
        self.assertIsNone(self.record()["sessionId"])
        self.assertIsNone(self.service.runtime_session())

    def test_delete_failure_keeps_reference_and_blocks_runtime_until_retry(self):
        self.service.open()
        self.service.resume(True, self.enqueue)
        self.cp.delete_browser_profile.side_effect = TimeoutError()
        self.assert_error(503, lambda: self.service.close(forget=True))
        self.assertEqual(self.record()["profileId"], "frogbot_test-0123456789")
        self.assert_error(409, self.service.runtime_session)
        self.cp.delete_browser_profile.side_effect = None
        self.assertFalse(self.service.close(forget=True)["hasSavedLogin"])

    def test_unknown_start_can_be_recovered_for_cleanup_with_same_token(self):
        self.dp.start_browser_session.side_effect = TimeoutError()
        self.assert_error(503, self.service.open)
        token = self.record()["startToken"]
        self.dp.start_browser_session.side_effect = None
        self.service.close()
        self.assertEqual(self.dp.start_browser_session.call_args.kwargs["clientToken"], token)
        self.dp.stop_browser_session.assert_called_once()

    def test_session_name_mismatch_fails_closed(self):
        self.service.open()
        self.service.resume(False, self.enqueue)
        self.dp.get_browser_session.return_value["name"] = "another-user-session"
        self.assert_error(403, self.service.runtime_session)

    def test_conditional_write_rejects_stale_revision(self):
        stale = self.record()
        self.service.store.write(stale, status="OPENING")
        self.assert_error(409, lambda: self.service.store.write(stale, status="READY"))

    def test_cleanup_works_without_bot_or_capability_and_revokes_context(self):
        self.service.open()
        self.service.resume(True, self.enqueue)
        del self.table.items[("USER#user-1", "BOT#bot-1")]
        with patch.object(self.module.time, "time", return_value=self.now):
            self.module.delete_browser_context(self.table, "user-1", "bot-1", agentcore=self.dp, control=self.cp)
        self.assertTrue(self.record()["revoked"])
        self.assertIsNone(self.record()["profileId"])

    def route(self, method, suffix, body=None, query=None, params=None):
        return self.routes.browser_session_route(
            "user-1", "Name", method, f"/bots/bot-1/browser{suffix}",
            params or {"botId": "bot-1"},
            {"body": json.dumps(body or {}), "queryStringParameters": query},
        )

    def test_route_rejects_untrusted_fields_ids_and_boolean_coercion(self):
        for body in ({"rememberLogin": "true"}, {"rememberLogin": 1}, {},
                     {"rememberLogin": True, "sessionId": "forged"}):
            with self.assertRaises(self.support.ApiError) as error:
                self.route("POST", "/resume", body)
            self.assertEqual(error.exception.status_code, 400)
        for params in ({"botId": "../../other"}, {"botId": "bot-1", "sessionId": "x"}):
            with self.assertRaises(self.support.ApiError):
                self.route("GET", "", params=params)
        with self.assertRaises(self.support.ApiError):
            self.route("GET", "", query={"profileId": "forged"})

    def test_group_routes_reject_before_any_client_creation(self):
        with patch.object(self.routes, "browser_clients") as clients:
            for method, suffix in (("GET", ""), ("POST", "/open"), ("POST", "/resume"),
                                   ("POST", "/close"), ("DELETE", "/profile")):
                with self.assertRaises(self.support.ApiError) as error:
                    self.route(method, suffix, {"groupId": "work", "rememberLogin": True}
                               if suffix == "/resume" else {"groupId": "work"} if method == "POST" else None,
                               {"groupId": "work"} if method != "POST" else None)
                self.assertEqual(error.exception.status_code, 409)
            clients.assert_not_called()

    def test_route_holds_send_lease_during_open_and_sets_no_store(self):
        order = []
        service = MagicMock()
        service.open.side_effect = lambda: order.append("open") or {"status": "human_control"}
        with (patch.object(self.routes, "browser_clients", return_value=(self.dp, self.cp)),
              patch.object(self.routes, "BrowserSessionService", return_value=service),
              patch.object(self.routes, "_claim_send_lease", side_effect=lambda *_a: order.append("claim") or "lease"),
              patch.object(self.routes, "_release_send_lease", side_effect=lambda *_a: order.append("release"))):
            response = self.route("POST", "/open")
        self.assertEqual(order, ["claim", "open", "release"])
        self.assertEqual(response["headers"]["cache-control"], "no-store")

    def test_route_releases_lease_if_open_fails(self):
        service = MagicMock()
        service.open.side_effect = self.routes.BrowserSessionError(409, "Busy")
        with (patch.object(self.routes, "browser_clients", return_value=(self.dp, self.cp)),
              patch.object(self.routes, "BrowserSessionService", return_value=service),
              patch.object(self.routes, "_claim_send_lease", return_value="lease"),
              patch.object(self.routes, "_release_send_lease") as release,
              self.assertRaises(self.support.ApiError)):
            self.route("POST", "/open")
        release.assert_called_once_with("user-1", "bot-1", "lease")

    def test_new_routes_are_authenticated_and_not_the_bot_delete_route(self):
        handlers = self.handler.authenticated_routes.ROUTE_HANDLERS
        for key in ("GET /bots/{botId}/browser", "POST /bots/{botId}/browser/open",
                    "POST /bots/{botId}/browser/resume", "POST /bots/{botId}/browser/close",
                    "DELETE /bots/{botId}/browser/profile"):
            self.assertIs(handlers[key], self.routes.browser_session_route)

    def test_resume_route_uses_existing_send_message_without_approval_override(self):
        service = MagicMock()
        service.resume.side_effect = lambda remember, enqueue: enqueue("safe continuation")
        with (patch.object(self.routes, "browser_clients", return_value=(self.dp, self.cp)),
              patch.object(self.routes, "BrowserSessionService", return_value=service),
              patch.object(self.routes, "_send_message", return_value={"turnId": "approval-needed"}) as send):
            self.route("POST", "/resume", {"rememberLogin": False})
        send.assert_called_once_with("user-1", "bot-1", {"text": "safe continuation"})

    def _send_integration(self, status, resume_state=None, approval_tools=None):
        bot = {"id": "bot-1", "toolIds": ["browser"], "alwaysAllowedToolIds": []}
        record = {**self.record(), "status": status, "resumeState": resume_state, "revision": 1}
        self.data_table.put_item(Item=record)
        self.data_table.put.clear()
        direct = self.direct_chat
        self.enterContext(patch.object(direct, "table", self.data_table))
        self.enterContext(patch.object(direct, "_get_bot", return_value=bot))
        self.enterContext(patch.object(direct, "_resolve_attachments", return_value=[]))
        self.enterContext(patch.object(direct, "_partition_items", return_value=[]))
        self.enterContext(patch.object(direct.catalog, "unapproved_tools", return_value=approval_tools or []))
        claimed = self.enterContext(patch.object(direct, "_claim_send_lease", wraps=direct._claim_send_lease))
        released = self.enterContext(patch.object(direct, "_release_send_lease", wraps=direct._release_send_lease))
        original_guard = self.module.ensure_browser_send_allowed

        def guarded(*args):
            claimed.assert_called_once_with("user-1", "bot-1")
            released.assert_not_called()
            self.assertIn("SET sendLeaseOwner", self.data_table.updated[-1]["UpdateExpression"])
            return original_guard(*args)

        checked = self.enterContext(patch.object(self.module, "ensure_browser_send_allowed", side_effect=guarded))
        return direct, checked, released

    def test_send_message_human_control_guard_holds_lease_and_never_queues(self):
        direct, checked, released = self._send_integration("HUMAN_CONTROL")
        with (patch.object(direct, "_steer_active_turns") as steer,
              patch.object(direct, "_start_bot_turn", wraps=direct._start_bot_turn) as start,
              self.assertRaises(self.support.ApiError) as error):
            direct._send_message("user-1", "bot-1", {"text": "Continue"})
        self.assertEqual(error.exception.status_code, 409)
        checked.assert_called_once_with(self.data_table, "user-1", "bot-1")
        released.assert_called_once()
        steer.assert_not_called()
        start.assert_not_called()
        self.sqs.send_message.assert_not_called()
        self.assertFalse(any(item.get("entity") == "TURN" for item in self.data_table.put))

    def test_send_message_resume_enqueueing_is_allowed_and_queues_once(self):
        direct, checked, released = self._send_integration("READY", "ENQUEUEING")
        result = direct._send_message("user-1", "bot-1", {"text": self.module.RESUME_PROMPT})
        self.assertEqual(result["status"], "pending")
        checked.assert_called_once()
        released.assert_called_once()
        self.sqs.send_message.assert_called_once()
        queued = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(queued["type"], "AGENT_REPLY")
        self.assertEqual(queued["botId"], "bot-1")
        direct.catalog.unapproved_tools.assert_called_once_with("user-1", ["browser"], [])

    def test_send_message_resume_enqueueing_does_not_bypass_required_approval(self):
        direct, checked, released = self._send_integration(
            "READY", "ENQUEUEING", [{"id": "browser", "name": "Browser"}],
        )
        result = direct._send_message("user-1", "bot-1", {"text": self.module.RESUME_PROMPT})
        self.assertEqual(result["status"], "awaiting_approval")
        checked.assert_called_once()
        released.assert_called_once()
        self.sqs.send_message.assert_not_called()
        turn = next(item for item in self.data_table.put if item.get("entity") == "TURN")
        self.assertEqual(turn["approvalToolIds"], ["browser"])


class BrowserSdkTests(unittest.TestCase):
    def test_aws_shapes_signing_and_bounds_with_real_sdk(self):
        try:
            import boto3
            from botocore.credentials import Credentials
            from botocore.validate import validate_parameters
        except ImportError:
            self.skipTest("Run with services/agent-runtime/.venv/bin/python for real SDK contract checks")
        from urllib.parse import parse_qs, urlsplit

        from shared.browser_session_aws import live_view_url
        from shared.browser_sessions import managed_session_name
        client = boto3.client("bedrock-agentcore", region_name="us-east-1",
                              aws_access_key_id="TEST", aws_secret_access_key="TEST")
        request = {"browserIdentifier": "aws.browser.v1", "sessionTimeoutSeconds": 3600,
                   "name": managed_session_name("user-1", "bot-1"), "clientToken": "a" * 36,
                   "profileConfiguration": {"profileIdentifier": "frogbot_test-0123456789"}}
        validate_parameters(request, client.meta.service_model.operation_model("StartBrowserSession").input_shape)
        validate_parameters({"browserIdentifier": "aws.browser.v1", "sessionId": "session1",
                             "streamUpdate": {"automationStreamUpdate": {"streamStatus": "DISABLED"}}},
                            client.meta.service_model.operation_model("UpdateBrowserStream").input_shape)
        validate_parameters({"browserIdentifier": "aws.browser.v1", "sessionId": "session1",
                             "profileIdentifier": "frogbot_test-0123456789", "clientToken": "a" * 36},
                            client.meta.service_model.operation_model("SaveBrowserSessionProfile").input_shape)
        control = boto3.client("bedrock-agentcore-control", region_name="us-east-1",
                               aws_access_key_id="TEST", aws_secret_access_key="TEST")
        validate_parameters({"name": "frogbot_test", "tags": {"frogbot:managed-by": "FrogBot"},
                             "clientToken": "a" * 36},
                            control.meta.service_model.operation_model("CreateBrowserProfile").input_shape)
        with patch.object(boto3, "Session") as session:
            session.return_value.get_credentials.return_value = Credentials("TEST", "TEST", "TESTTOKEN")
            url = live_view_url(client, "session1")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["X-Amz-Expires"], ["300"])
        self.assertEqual(query["X-Amz-SignedHeaders"], ["host"])
        self.assertEqual(query["X-Amz-Security-Token"], ["TESTTOKEN"])
        self.assertEqual(urlsplit(url).path, "/browser-streams/aws.browser.v1/sessions/session1/live-view")
        self.assertIn("/us-east-1/bedrock-agentcore/aws4_request", query["X-Amz-Credential"][0])
