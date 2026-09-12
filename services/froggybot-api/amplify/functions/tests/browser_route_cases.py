from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class BrowserRouteCases:
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
        service.open.side_effect = lambda **_kwargs: order.append("open") or {"status": "human_control"}
        with (patch.object(self.routes, "browser_clients", return_value=(self.dp, self.cp)),
              patch.object(self.routes, "BrowserSessionService", return_value=service),
              patch.object(self.routes, "_claim_send_lease", side_effect=lambda *_a: order.append("claim") or "lease"),
              patch.object(self.routes, "_release_send_lease", side_effect=lambda *_a: order.append("release"))):
            response = self.route("POST", "/open")
        self.assertEqual(order, ["claim", "open", "release"])
        self.assertEqual(response["headers"]["cache-control"], "no-store")

    def test_browser_route_admission_uses_authenticated_user(self):
        allowed = SimpleNamespace(
            allowed=True,
            reason="admitted",
            user_message="",
        )
        with patch.object(self.routes, "admit_run", return_value=allowed) as admit:
            self.routes._authorize_browser_start(
                "user-1", "bot-1", "stable-start-id"
            )

        admit.assert_called_once_with(
            "user-1",
            "browser:bot-1:stable-start-id",
            allow_duplicate_during_circuit=True,
        )

    def test_browser_route_denial_never_starts_provider_session(self):
        denied = SimpleNamespace(
            allowed=False,
            reason="monthly_limit",
            user_message="Usage limit reached",
        )
        with (
            patch.object(self.routes, "admit_run", return_value=denied),
            self.assertRaises(self.routes.BrowserSessionError) as caught,
        ):
            self.routes._authorize_browser_start(
                "user-1", "bot-1", "stable-start-id"
            )

        self.assertEqual(caught.exception.status_code, 429)
        self.dp.start_browser_session.assert_not_called()

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
