from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from api_test_case import ApiTestCase
from worker_test_case import WorkerTestCase


class EventRoutineWorkerTests(WorkerTestCase):
    def setUp(self):
        super().setUp()
        self.module = self.event_routine_job
        self.addCleanup(patch.stopall)
        patch.object(self.module, "table", self.table).start()
        patch.object(self.module, "_account_is_active", return_value=True).start()
        patch.object(self.module.catalog, "approval_tool_names", return_value=[]).start()
        self.process = patch.object(self.module, "_process_group_agent_round").start()
        for item in [
            {"pk": "GROUP#work", "sk": "META", "ownerId": "owner"},
            {"pk": "GROUP#work", "sk": "USER#owner", "name": "Owner"},
            {"pk": "GROUP#work", "sk": "MESSAGE#now#00#source", "id": "source", "source": "chat"},
            {"pk": "GROUP#work", "sk": "DECISION#decision", "entity": "GROUP_DECISION", "id": "decision", "sourceMessageId": "source", "sourceMessageKey": "MESSAGE#now#00#source", "text": "Choose option A", "createdAt": "2026-09-18T12:00:00Z"},
            {"pk": "GROUP#work", "sk": "ROUTINE#routine", "entity": "GROUP_ROUTINE", "id": "routine", "ownerId": "owner", "enabled": True, "updatedAt": "2026-09-18T11:00:00Z", "prompt": "Summarize the next steps", "trigger": {"eventType": "group.decision.saved"}},
        ]:
            self.table.put_item(Item=item)
        for bot_id, name, role in [("chief", "Chief", "chief"), ("research", "Research", None)]:
            self.table.put_item(Item={"pk": "GROUP#work", "sk": f"BOT#{bot_id}", "entity": "GROUP_BOT", "botId": bot_id, "botOwnerId": "owner", "name": name, "systemRole": role})
            self.table.put_item(Item={"pk": "USER#owner", "sk": f"BOT#{bot_id}", "id": bot_id, "toolIds": []})

    def test_duplicate_decision_delivery_reuses_one_run(self):
        event = {"groupId": "work", "decisionId": "decision"}
        self.module._process_group_decision_event(event)
        queued = json.loads(self.module.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(queued["type"], "EVENT_GROUP_ROUND")
        self.module._process_event_group_round({}, queued)
        first = self.process.call_args.args[1]
        first_count = len(self.table.items)
        self.module._process_event_group_round({}, queued)
        self.assertEqual(len(self.table.items), first_count)
        self.assertEqual(self.process.call_args.args[1]["messageId"], first["messageId"])
        run = self.table.items[("GROUP#work", f"RUN#{first['messageId']}")]
        self.assertEqual(run["occurrenceId"], "decision")
        self.assertEqual(run["source"], "event")

    def test_routine_output_cannot_trigger_another_routine(self):
        self.table.items[("GROUP#work", "MESSAGE#now#00#source")]["source"] = "event"
        self.module._process_group_decision_event({"groupId": "work", "decisionId": "decision"})
        self.module.sqs.send_message.assert_not_called()

    def test_workspace_file_size_from_dynamodb_is_json_serializable(self):
        selected = self.agent._workspace_payload_files([{
            "source": "workspace", "workspaceFileId": "file",
            "name": "notes.txt", "size": Decimal(12), "objectKey": "safe",
        }])
        self.assertEqual(selected[0]["size"], 12)
        json.dumps(selected)

    def test_github_duplicate_delivery_uses_one_stable_run(self):
        trigger = {
            "kind": "event", "eventType": "github.issue.opened",
            "connectionId": "connection_12345678901234567890",
            "connectionUpdatedAt": "2026-09-18T11:00:00Z",
            "installationId": "55", "repositoryId": 77,
            "repositoryName": "acme/project",
        }
        self.table.items[("GROUP#work", "ROUTINE#routine")]["trigger"] = trigger
        connection = {
            "provider": "github", "connectionStatus": "connected",
            "providerAccountId": "55", "repositories": [{"id": 77, "name": "acme/project"}],
            "updatedAt": "2026-09-18T11:00:00Z",
        }
        issue = {
            "installationId": "55", "repositoryId": 77,
            "repositoryName": "acme/project", "number": 2,
            "title": "Bug", "body": "Please inspect", "createdAt": "2026-09-18T12:00:00Z",
        }
        event = {"groupId": "work", "routineId": "routine", "deliveryId": "delivery-1", "githubIssue": issue}
        with patch.object(self.module.catalog, "_get_connection", return_value=connection):
            self.module._process_event_group_round({}, event)
            first_count = len(self.table.items)
            self.module._process_event_group_round({}, event)
        self.assertEqual(len(self.table.items), first_count)
        run_id = self.process.call_args.args[1]["messageId"]
        run = self.table.items[("GROUP#work", f"RUN#{run_id}")]
        self.assertEqual(run["occurrenceId"], "delivery-1")
        self.assertEqual(run["eventType"], "github.issue.opened")
        user_message = next(item for item in self.table.items.values() if item.get("id") == run_id and item.get("authorType") == "user")
        self.assertIn("untrusted data", user_message["text"])

    def test_revoked_github_connection_prevents_event_run(self):
        self.table.items[("GROUP#work", "ROUTINE#routine")]["trigger"] = {
            "eventType": "github.issue.opened", "connectionId": "connection_12345678901234567890",
            "connectionUpdatedAt": "2026-09-18T11:00:00Z",
            "installationId": "55", "repositoryId": 77,
            "repositoryName": "acme/project",
        }
        event = {
            "groupId": "work", "routineId": "routine", "deliveryId": "delivery-2",
            "githubIssue": {"installationId": "55", "repositoryId": 77,
                            "repositoryName": "acme/project", "createdAt": "2026-09-18T12:00:00Z"},
        }
        with patch.object(self.module.catalog, "_get_connection", return_value=None):
            self.module._process_event_group_round({}, event)
        self.process.assert_not_called()
        # Reconnecting the same installation does not revive an old grant.
        reconnected = {
            "provider": "github", "connectionStatus": "connected",
            "providerAccountId": "55", "repositories": [{"id": 77}],
            "updatedAt": "2026-09-18T12:30:00Z",
        }
        with patch.object(self.module.catalog, "_get_connection", return_value=reconnected):
            self.module._process_event_group_round({}, event)
        self.process.assert_not_called()


class GithubWebhookApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(patch.stopall)
        self.module = self.github_webhook
        patch.object(self.module, "_webhook_secret", return_value="x" * 40).start()
        patch.object(self.module, "_partition_items", return_value=[{
            "entity": "GITHUB_ROUTINE_SUBSCRIPTION", "groupId": "work", "routineId": "routine",
        }]).start()

    def _event(self, signature_override=None):
        payload = {
            "action": "opened", "installation": {"id": 55},
            "repository": {"id": 77, "full_name": "acme/project"},
            "issue": {"number": 2, "title": "Bug", "body": "Inspect", "created_at": "2026-09-18T12:00:00Z"},
        }
        raw = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(b"x" * 40, raw, hashlib.sha256).hexdigest()
        return {
            "body": raw.decode(),
            "headers": {
                "X-Hub-Signature-256": signature_override or signature,
                "X-GitHub-Delivery": "delivery-1", "X-GitHub-Event": "issues",
            },
        }

    def test_signed_issue_is_queued_for_selected_repository(self):
        response = self.module.github_issue_webhook(self._event())
        self.assertEqual(response["statusCode"], 202)
        request = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        self.assertEqual(request["deliveryId"], "delivery-1")
        self.assertEqual(request["githubIssue"]["repositoryId"], 77)
        self.module._partition_items.assert_called_once_with("GITHUB_EVENT#55#77", "ROUTINE#")

    def test_changed_payload_and_bad_signature_are_rejected(self):
        event = self._event()
        event["body"] += " "
        with self.assertRaises(self.support.ApiError) as error:
            self.module.github_issue_webhook(event)
        self.assertEqual(error.exception.status_code, 401)
        self.sqs.send_message.assert_not_called()
        with self.assertRaises(self.support.ApiError):
            self.module.github_issue_webhook(self._event("sha256=" + "0" * 64))

    def test_routine_binding_requires_selected_github_repository(self):
        routines = self.group_routines
        connection = {
            "provider": "github", "connectionStatus": "connected",
            "providerAccountId": "55", "repositories": [{"id": 77, "name": "acme/project"}],
            "updatedAt": "2026-09-18T11:00:00Z",
        }
        with patch.object(routines.catalog, "_get_connection", return_value=connection):
            trigger = routines._validated_trigger("owner", {
                "eventType": "github.issue.opened",
                "connectionId": "connection_12345678901234567890", "repositoryId": 77,
            })
            self.assertEqual(trigger["installationId"], "55")
            with self.assertRaises(self.support.ApiError):
                routines._validated_trigger("owner", {
                    "eventType": "github.issue.opened",
                    "connectionId": "connection_12345678901234567890", "repositoryId": 78,
                })

    def test_deleting_routine_removes_github_subscription(self):
        routines = self.group_routines
        trigger = {
            "eventType": "github.issue.opened", "installationId": "55",
            "repositoryId": 77,
        }
        routine = {
            "pk": "GROUP#work", "sk": "ROUTINE#routine", "entity": "GROUP_ROUTINE",
            "id": "routine", "trigger": trigger,
        }
        self.data_table.put_item(Item=routine)
        pointer = {"pk": "GITHUB_EVENT#55#77", "sk": "ROUTINE#work#routine"}
        self.data_table.put_item(Item={**pointer, "entity": "GITHUB_ROUTINE_SUBSCRIPTION"})
        with patch.object(routines, "_get_routine", return_value=routine), patch.object(routines, "table", self.data_table):
            routines._delete_group_routine("owner", "work", "routine")
        self.assertNotIn((pointer["pk"], pointer["sk"]), self.data_table.items)
        self.assertNotIn(("GROUP#work", "ROUTINE#routine"), self.data_table.items)


class WorkspaceApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.module = self.workspaces
        self.addCleanup(patch.stopall)
        patch.object(self.module, "table", self.data_table).start()
        patch.object(self.module, "_get_bot", return_value={"id": "bot-1"}).start()
        patch.object(self.module, "_require_group_member", return_value=({"ownerId": "owner"}, [])).start()
        patch.object(self.module, "_partition_items", side_effect=lambda pk, prefix: [
            item for (item_pk, sk), item in self.data_table.items.items()
            if item_pk == pk and sk.startswith(prefix)
        ]).start()
        patch.object(self.module, "_get_file", return_value={
            "id": "upload", "name": "notes.txt", "size": 12, "kind": "document",
            "format": "txt", "contentType": "text/plain", "objectKey": "users/owner/uploads/upload.txt",
        }).start()
        patch.object(self.module, "memory_actor_id", return_value="a" * 64).start()

    def test_file_survives_as_scoped_reference_for_later_turn(self):
        created = self.module._add_workspace_file("owner", "bot", "bot-1", {"fileId": "upload"})
        listed = self.module._list_workspace_files("owner", "bot", "bot-1")
        refs = self.module._resolve_workspace_files("owner", "bot", "bot-1", [created["id"]])
        self.assertEqual(listed["fileCount"], 1)
        self.assertEqual(refs[0]["workspaceFileId"], created["id"])
        self.assertEqual(refs[0]["botId"], "bot-1")
        self.assertIn("/bots/bot-1/workspace/", refs[0]["objectKey"])
        self.assertNotIn("objectKey", created)

    def test_room_file_delete_requires_uploader_or_owner(self):
        created = self.module._add_workspace_file("owner", "group", "work", {"fileId": "upload"})
        with self.assertRaises(self.support.ApiError) as error:
            self.module._delete_workspace_file("member", "group", "work", created["id"])
        self.assertEqual(error.exception.status_code, 403)
