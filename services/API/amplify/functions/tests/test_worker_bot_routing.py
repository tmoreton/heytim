from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from worker_test_case import WorkerTestCase


class WorkerBotRoutingTests(WorkerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.routing = self.bot_routing
        self.mutations = self.bot_mutations
        self.chief = {"id": "chief", "systemRole": "chief"}
        self.parent = {
            "pk": "CHAT#user-1#chief", "sk": "TURN#parent", "id": "parent",
            "userId": "user-1", "botId": "chief", "createdAt": "2026-10-15T16:00:00Z", "status": "RUNNING",
        }
        self.table.items[(self.parent["pk"], self.parent["sk"])] = dict(self.parent)
        self.mutation_id = str(uuid.uuid4())
        self.value = {"botId": "research", "task": "Compare the two supplied options."}
        self.direct = SimpleNamespace(
            require_request_consent=MagicMock(),
            _get_bot=MagicMock(side_effect=lambda _user, bot_id: (
                self.chief if bot_id == "chief" else {"id": bot_id, "name": "Research"}
            )),
            _claim_send_lease=MagicMock(return_value="send-lease"),
            _release_send_lease=MagicMock(),
            _partition_items=MagicMock(return_value=[]),
            _now=MagicMock(return_value="2026-10-15T16:01:00Z"),
        )
        self.enterContext(patch.object(self.routing, "table", self.table))
        self.enterContext(patch.object(self.routing, "_direct_chat_api", return_value=self.direct))
        self.send = self.enterContext(patch.object(self.routing, "send_job"))
        self.browser_guard = self.enterContext(patch.object(self.routing, "ensure_browser_send_allowed"))
        original_update = self.table.update_item

        def update(**kwargs):
            original_update(**kwargs)
            key = kwargs["Key"]
            item = self.table.items.get((key["pk"], key["sk"]))
            if kwargs["UpdateExpression"] == "SET handoffQueuedAt = :now":
                item["handoffQueuedAt"] = kwargs["ExpressionAttributeValues"][":now"]
            elif kwargs["UpdateExpression"].startswith("SET #status = :error"):
                values = kwargs["ExpressionAttributeValues"]
                item.update(status="ERROR", assistantText=values[":text"], completedAt=values[":now"], handoffDispatchFailed=True)
            elif kwargs["UpdateExpression"].startswith("SET #status = :pending"):
                item["status"] = "PENDING"
                for field in ("assistantText", "completedAt", "handoffDispatchFailed"):
                    item.pop(field, None)

        self.enterContext(patch.object(self.table, "update_item", side_effect=update))

    def route(self, *, value=None, parent=None, chief=None) -> None:
        self.routing.route_bot_task(
            "user-1", chief or self.chief, parent or self.parent,
            self.mutation_id, value or self.value,
        )

    def child_turns(self) -> list[dict]:
        return [item for item in self.table.items.values() if item.get("entity") == "TURN"]

    def test_canceled_chief_request_cannot_dispatch_a_new_task(self) -> None:
        self.table.items[(self.parent["pk"], self.parent["sk"])]["status"] = "CANCELLED"
        with self.assertRaisesRegex(ValueError, "no longer running"):
            self.route()
        self.send.assert_not_called()

    def test_handoff_uses_owned_bot_and_normal_dispatch_without_copying_private_context(self) -> None:
        self.route()
        child, = self.child_turns()
        self.assertEqual(child["id"], self.mutation_id)
        self.assertEqual(child["botId"], "research")
        self.assertEqual(child["userText"], self.value["task"])
        self.assertEqual(child["source"], "bot_route")
        self.assertEqual(child["routedFromBotId"], "chief")
        self.assertEqual(child["routedFromTurnId"], "parent")
        self.assertEqual(child["status"], "PENDING")
        for absent in ("attachments", "history", "toolIds", "alwaysAllowedToolIds", "emailContext"):
            self.assertNotIn(absent, child)
        self.direct.require_request_consent.assert_called_once_with("user-1")
        self.direct._get_bot.assert_any_call("user-1", "research")
        self.browser_guard.assert_called_once_with(self.table, "user-1", "research")
        self.send.assert_called_once_with(self.routing.sqs, self.routing.QUEUE_URL, {
            "type": "AGENT_REPLY", "userId": "user-1", "botId": "research", "turnKey": child["sk"],
        })
        self.direct._release_send_lease.assert_called_once_with("user-1", "research", "send-lease")

    def test_replay_does_not_create_or_queue_another_turn_and_identity_binds_target_and_task(self) -> None:
        self.route()
        self.route()
        self.assertEqual(len(self.child_turns()), 1)
        self.send.assert_called_once()
        for changed in (
            {**self.value, "task": "A different task"},
            {**self.value, "botId": "writer"},
        ):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "reused"):
                self.route(value=changed)
        self.assertEqual(len(self.child_turns()), 1)
        self.send.assert_called_once()

    def test_queue_failure_is_visible_and_retries_the_same_turn(self) -> None:
        self.send.side_effect = [RuntimeError("Queue unavailable"), None]
        with self.assertRaisesRegex(RuntimeError, "Queue unavailable"):
            self.route()
        child, = self.child_turns()
        self.assertEqual(child["status"], "ERROR")
        self.assertTrue(child["handoffDispatchFailed"])
        self.assertIn("could not queue", child["assistantText"])
        self.assertNotIn("handoffQueuedAt", child)
        self.route()
        retried, = self.child_turns()
        self.assertEqual(retried["id"], child["id"])
        self.assertEqual(retried["status"], "PENDING")
        self.assertNotIn("handoffDispatchFailed", retried)
        self.assertIn("handoffQueuedAt", retried)
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.send.call_args_list[0], self.send.call_args_list[1])

    def test_busy_target_is_preserved_instead_of_steered_or_cancelled(self) -> None:
        self.direct._partition_items.return_value = [{"id": "active", "status": "AWAITING_APPROVAL"}]
        with self.assertRaisesRegex(ValueError, "already working"):
            self.route()
        self.assertEqual(self.child_turns(), [])
        self.send.assert_not_called()
        self.direct._release_send_lease.assert_called_once()

    def test_browser_permission_and_owner_lookup_fail_before_dispatch(self) -> None:
        self.browser_guard.side_effect = RuntimeError("Browser needs input")
        with self.assertRaisesRegex(RuntimeError, "Browser needs input"):
            self.route()
        self.send.assert_not_called()
        self.assertEqual(self.child_turns(), [])
        self.browser_guard.side_effect = None
        self.direct._get_bot.side_effect = RuntimeError("Bot not found")
        with self.assertRaisesRegex(RuntimeError, "Bot not found"):
            self.route()
        self.send.assert_not_called()

    def test_routing_rejects_self_nonchief_external_sources_and_recursion(self) -> None:
        with self.assertRaisesRegex(ValueError, "other than Chief"):
            self.route(value={**self.value, "botId": "chief"})
        for source in ("schedule", "webhook", "email", "bot_route"):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "direct Chief"):
                self.route(parent={**self.parent, "source": source})
        with self.assertRaisesRegex(ValueError, "direct Chief"):
            self.route(chief={"id": "chief", "systemRole": "specialist"})
        self.send.assert_not_called()

    def test_routed_turn_cannot_mutate_bots_or_route_again(self) -> None:
        mutation = {"mutationId": self.mutation_id, "action": "route_bot", "value": self.value}
        with self.assertRaisesRegex(ValueError, "routed tasks"):
            self.mutations.apply_bot_mutations("user-1", self.chief, {"source": "bot_route"}, [mutation])
        with self.assertRaisesRegex(ValueError, "direct Chief"):
            self.mutations.apply_bot_mutations("user-1", {"id": "writer"}, self.parent, [mutation])
        self.send.assert_not_called()

    def test_task_bounds_and_unrecognized_context_fields_fail_before_dispatch(self) -> None:
        for invalid in (
            {**self.value, "task": ""}, {**self.value, "task": "x" * 8_001},
            {**self.value, "history": [{"role": "user", "content": "private"}]},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.route(value=invalid)
        self.send.assert_not_called()
