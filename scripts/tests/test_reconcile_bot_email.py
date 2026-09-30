from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bot_email_replay_apply import apply_group
from _bot_email_replay_aws import read_private, write_private
from _bot_email_replay_dispatch import (
    acknowledge_message,
    dispatch_group,
    dispatch_import,
)
from _bot_email_replay_imported import apply_import
from _bot_email_replay_plan import (
    DESTINATION_ACCOUNT,
    SOURCE_ACCOUNT,
    ReplayError,
    digest,
    parse_capture,
    reviewed_plan,
)
from reconcile_bot_email import main
from shared.bot_inbox import mail_address


def missing() -> ClientError:
    return ClientError({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")


class FakeTransactionCanceled(Exception):
    pass


class FakeClient:
    exceptions = SimpleNamespace(
        ConditionalCheckFailedException=FakeTransactionCanceled,
    )

    def __init__(self, table) -> None:
        self.table = table
        self.transactions = []
        self.fail_after_commit = False

    def transact_write_items(self, **kwargs) -> None:
        self.transactions.append(kwargs)
        operations = kwargs["TransactItems"]
        staged = dict(self.table.items)
        for operation in operations:
            if "ConditionCheck" in operation:
                check = operation["ConditionCheck"]
                key = check["Key"]["pk"], check["Key"]["sk"]
                if key[1].startswith("BOT#"):
                    bot = staged.get(key)
                    values = check["ExpressionAttributeValues"]
                    if not bot or bot.get("emailToken") != values[":token"]:
                        raise ClientError({"Error": {"Code": "TransactionCanceledException"}}, "TransactWriteItems")
                continue
            item = operation["Put"]["Item"]
            key = item["pk"], item["sk"]
            if key in staged:
                raise ClientError({"Error": {"Code": "TransactionCanceledException"}}, "TransactWriteItems")
            staged[key] = item
        self.table.items = staged
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise ClientError({"Error": {"Code": "InternalServerError"}}, "TransactWriteItems")


class FakeTable:
    def __init__(self) -> None:
        self.name = "destination-table"
        self.items: dict[tuple[str, str], dict] = {}
        self.client = FakeClient(self)
        self.meta = SimpleNamespace(client=self.client)

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, *, Item: dict, **_kwargs) -> None:
        key = Item["pk"], Item["sk"]
        if key in self.items:
            raise FakeTransactionCanceled
        self.items[key] = Item

    def query(self, *, ExpressionAttributeValues: dict, **_kwargs) -> dict:
        return {"Items": [dict(value) for (pk, sk), value in self.items.items()
                          if pk == ExpressionAttributeValues[":pk"] and sk.startswith("BOT#")]}

    def update_item(self, *, Key: dict, UpdateExpression: str,
                    ExpressionAttributeValues: dict, **_kwargs) -> None:
        key = Key["pk"], Key["sk"]
        item = self.items[key]
        if "dispatchLeaseOwner = :owner" in UpdateExpression:
            now = ExpressionAttributeValues[":now"]
            if item.get("dispatchLeaseUntil", -1) >= now:
                raise FakeTransactionCanceled
            item["dispatchLeaseOwner"] = ExpressionAttributeValues[":owner"]
            item["dispatchLeaseUntil"] = ExpressionAttributeValues[":until"]
            item["dispatchAttempts"] += 1
        elif "lastQueuedEpoch" in UpdateExpression:
            if item.get("dispatchLeaseOwner") != ExpressionAttributeValues[":owner"]:
                raise FakeTransactionCanceled
            item["lastQueuedEpoch"] = ExpressionAttributeValues[":now"]
            item.pop("dispatchLeaseOwner", None)
            item.pop("dispatchLeaseUntil", None)
        elif "observedAt" in UpdateExpression:
            item["state"] = "observed"
        elif "deletedAt" in UpdateExpression:
            item["state"] = "deleted"


class FakeS3:
    def __init__(self, objects: dict[tuple[str, str], bytes]) -> None:
        self.objects = objects
        self.puts = []

    def put_object(self, **kwargs) -> None:
        self.puts.append(kwargs)
        key = kwargs["Bucket"], kwargs["Key"]
        if key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[key] = kwargs["Body"]


class FakeAccount:
    def __init__(self, account: str, objects: dict[tuple[str, str], bytes], table=None) -> None:
        self.account = account
        self.raw_bucket = f"raw-{account}"
        self.quarantine_bucket = f"quarantine-{account}"
        self.objects = objects
        self.s3 = FakeS3(objects)
        self.table = table or FakeTable()
        self.sqs = SimpleNamespace(delete_message=MagicMock())
        self.queue_url = f"queue-{account}"
        self.job_queue_url = f"jobs-{account}"

    def read_mime(self, bucket: str, key: str) -> bytes:
        if (bucket, key) not in self.objects:
            raise missing()
        return self.objects[bucket, key]


class ReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = str(uuid.uuid4())
        self.token = "abcdefghijklmnop"
        self.address = mail_address(self.owner, "bot-1", self.token)
        self.raw = (
            b"From: Owner <owner@example.com>\r\n"
            b"Subject: Status\r\n"
            b"Message-ID: <one@example.com>\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            b"What changed?\r\n"
        )
        self.topic = {
            SOURCE_ACCOUNT: f"arn:aws:sns:us-east-1:{SOURCE_ACCOUNT}:mail",
            DESTINATION_ACCOUNT: f"arn:aws:sns:us-east-1:{DESTINATION_ACCOUNT}:mail",
        }

    def _entry(self, account: str, ses_id: str, queue_id: str, minute: int) -> dict:
        bucket = f"quarantine-{account}"
        notification = {
            "notificationType": "Received",
            "mail": {"messageId": ses_id, "timestamp": f"2026-09-30T04:{minute:02d}:00Z",
                     "source": "owner@example.com"},
            "receipt": {
                "action": {"type": "S3", "bucketName": bucket,
                           "objectKey": f"received/{ses_id}"},
                "recipients": [self.address],
                "spamVerdict": {"status": "PASS"},
                "virusVerdict": {"status": "PASS"},
                "dmarcVerdict": {"status": "PASS"},
            },
        }
        body = json.dumps({
            "Type": "Notification", "TopicArn": self.topic[account],
            "MessageId": str(uuid.uuid4()), "Message": json.dumps(notification),
        })
        parsed = parse_capture(body, account, queue_id, self.topic[account], {bucket})
        return {
            "account": account, "sqsMessageId": queue_id, "body": body,
            "observations": [{
                **item, "mimeSha256": hashlib.sha256(self.raw).hexdigest(),
                "mimeBytes": len(self.raw), "headerMessageId": "<one@example.com>",
            } for item in parsed],
        }

    def _snapshot(self, entries: list[dict]) -> dict:
        accounts = {
            account: {
                "account": account, "region": "us-east-1",
                "appStack": "app", "captureStack": "capture", "table": "table",
                "rawBucket": f"raw-{account}",
                "quarantineBucket": f"quarantine-{account}",
                "topicArn": self.topic[account], "queueArn": f"arn:aws:sqs:us-east-1:{account}:capture",
                "queueUrl": f"queue-{account}", "jobQueueUrl": f"jobs-{account}",
            } for account in (SOURCE_ACCOUNT, DESTINATION_ACCOUNT)
        }
        snapshot = {"schemaVersion": 1, "accounts": accounts, "messages": entries,
                    "unclassifiedObjects": []}
        snapshot["snapshotDigest"] = digest(snapshot)
        return snapshot

    def _decisions(self, snapshot: dict, *, delivery: str = "automatic") -> dict:
        canonical = str(uuid.uuid4())
        decisions = {"schemaVersion": 1, "snapshotDigest": snapshot["snapshotDigest"],
                     "observations": {}}
        for index, entry in enumerate(snapshot["messages"]):
            for item in entry["observations"]:
                decisions["observations"][item["id"]] = {
                    "reviewed": True, "action": "replay", "canonicalId": canonical,
                    "primary": index == 0, "delivery": delivery,
                    "note": "Compared the recipient, header, body hash and receipt time.",
                }
        return decisions

    def _accounts(self, entries: list[dict]) -> dict:
        objects = {}
        for entry in entries:
            account = entry["account"]
            ses_id = entry["observations"][0]["sesMessageId"]
            objects[f"quarantine-{account}", f"received/{ses_id}"] = self.raw
        table = FakeTable()
        table.items[f"USER#{self.owner}", "BOT#bot-1"] = {
            "pk": f"USER#{self.owner}", "sk": "BOT#bot-1", "entity": "BOT",
            "id": "bot-1", "emailToken": self.token,
            "emailInboundMode": "automatic", "emailOwnerAddress": "owner@example.com",
        }
        return {
            SOURCE_ACCOUNT: FakeAccount(SOURCE_ACCOUNT, objects),
            DESTINATION_ACCOUNT: FakeAccount(DESTINATION_ACCOUNT, objects, table),
        }

    def test_topic_bucket_and_message_id_checks_fail_closed(self) -> None:
        entry = self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10)
        with self.assertRaises(ReplayError):
            parse_capture(entry["body"], SOURCE_ACCOUNT, "q-1", "wrong-topic",
                          {f"quarantine-{SOURCE_ACCOUNT}"})
        with self.assertRaises(ReplayError):
            parse_capture(entry["body"], SOURCE_ACCOUNT, "q-1", self.topic[SOURCE_ACCOUNT],
                          {"wrong-bucket"})

    def test_cross_account_match_requires_explicit_mapping_and_matching_evidence(self) -> None:
        entries = [self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10),
                   self._entry(DESTINATION_ACCOUNT, "dst-2", "q-2", 11)]
        snapshot = self._snapshot(entries)
        with self.assertRaises(ReplayError):
            reviewed_plan(snapshot, {"schemaVersion": 1,
                                     "snapshotDigest": snapshot["snapshotDigest"],
                                     "observations": {}})
        decisions = self._decisions(snapshot)
        plan = reviewed_plan(snapshot, decisions)
        self.assertEqual(len(plan["groups"]), 1)
        entries[1]["observations"][0]["mimeSha256"] = "0" * 64
        changed = self._snapshot(entries)
        changed_decisions = self._decisions(changed)
        with self.assertRaises(ReplayError):
            reviewed_plan(changed, changed_decisions)

    def test_destination_copy_and_atomic_marker_inbox_outbox_retry_after_uncertain_commit(self) -> None:
        entries = [self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10)]
        snapshot = self._snapshot(entries)
        group = reviewed_plan(snapshot, self._decisions(snapshot))["groups"][0]
        accounts = self._accounts(entries)
        destination = accounts[DESTINATION_ACCOUNT]
        destination.table.client.fail_after_commit = True
        result = apply_group(snapshot, group, accounts)
        self.assertTrue(result["automaticPending"])
        self.assertEqual(len(destination.table.client.transactions), 1)
        self.assertEqual(len(destination.s3.puts), 1)
        transaction = destination.table.client.transactions[0]["TransactItems"]
        entities = [operation["Put"]["Item"]["entity"] for operation in transaction if "Put" in operation]
        self.assertEqual(entities, ["MAIL_REPLAY", "BOT_EMAIL", "MAIL_REPLAY_OUTBOX"])
        self.assertEqual(len(destination.table.items), 4)
        apply_group(snapshot, group, accounts)
        self.assertEqual(len(destination.table.client.transactions), 1)
        self.assertEqual(len(destination.s3.puts), 1)

    def test_divergent_destination_mime_blocks_before_dynamo_write(self) -> None:
        entries = [self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10)]
        snapshot = self._snapshot(entries)
        group = reviewed_plan(snapshot, self._decisions(snapshot))["groups"][0]
        accounts = self._accounts(entries)
        destination = accounts[DESTINATION_ACCOUNT]
        destination.objects[destination.raw_bucket, "received/src-1"] = b"different"
        with self.assertRaises(ReplayError):
            apply_group(snapshot, group, accounts)
        self.assertEqual(len(destination.table.client.transactions), 0)

    def test_dispatch_failure_keeps_durable_outbox_for_recovery(self) -> None:
        entries = [self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10)]
        snapshot = self._snapshot(entries)
        group = reviewed_plan(snapshot, self._decisions(snapshot))["groups"][0]
        accounts = self._accounts(entries)
        destination = accounts[DESTINATION_ACCOUNT]
        apply_group(snapshot, group, accounts)
        with (
            patch("_bot_email_replay_dispatch.send_job", side_effect=RuntimeError("network")),
            self.assertRaisesRegex(RuntimeError, "network"),
        ):
            dispatch_group(snapshot, group, destination)
        outbox = destination.table.items[f"MAIL_REPLAY#{group['canonicalId']}", "OUTBOX"]
        self.assertEqual(outbox["state"], "pending")
        self.assertEqual(outbox["dispatchAttempts"], 1)
        with patch("_bot_email_replay_dispatch.time.time", return_value=outbox["dispatchLeaseUntil"] + 1), \
             patch("_bot_email_replay_dispatch.send_job") as send:
            self.assertEqual(dispatch_group(snapshot, group, destination), "queued")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[2]["turnId"], outbox["turnId"])

    def test_held_recipient_prevents_capture_delete(self) -> None:
        entry = self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10)
        snapshot = self._snapshot([entry])
        observation_id = entry["observations"][0]["id"]
        decisions = {"schemaVersion": 1, "snapshotDigest": snapshot["snapshotDigest"],
                     "observations": {observation_id: {"reviewed": True, "action": "hold",
                                                       "note": "Delivery identity is still ambiguous."}}}
        plan = reviewed_plan(snapshot, decisions)
        accounts = self._accounts([entry])
        with self.assertRaises(ReplayError):
            acknowledge_message(snapshot, plan, entry, accounts)

    def test_reviewed_failed_ses_verdict_records_rejection_before_ack(self) -> None:
        entry = self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10)
        wrapper = json.loads(entry["body"])
        notification = json.loads(wrapper["Message"])
        notification["receipt"]["spamVerdict"]["status"] = "FAIL"
        wrapper["Message"] = json.dumps(notification)
        entry["body"] = json.dumps(wrapper)
        entry["observations"] = [{
            **item,
            "mimeSha256": hashlib.sha256(self.raw).hexdigest(),
            "mimeBytes": len(self.raw),
            "headerMessageId": "<one@example.com>",
        } for item in parse_capture(
            entry["body"], SOURCE_ACCOUNT, "q-1", self.topic[SOURCE_ACCOUNT],
            {f"quarantine-{SOURCE_ACCOUNT}"},
        )]
        snapshot = self._snapshot([entry])
        observation_id = entry["observations"][0]["id"]
        decisions = {"schemaVersion": 1, "snapshotDigest": snapshot["snapshotDigest"],
                     "observations": {observation_id: {
                         "reviewed": True, "action": "reject", "reason": "ses_spam",
                         "note": "The SES spam verdict failed after the reviewed receipt scan.",
                     }}}
        plan = reviewed_plan(snapshot, decisions)
        self.assertEqual(len(plan["rejects"]), 1)
        accounts = self._accounts([entry])
        destination = accounts[DESTINATION_ACCOUNT]
        from _bot_email_replay_apply import apply_rejection

        apply_rejection(snapshot, plan["rejects"][0], accounts)
        self.assertEqual(len(destination.table.client.transactions), 1)
        self.assertEqual(len(destination.s3.puts), 1)
        with patch("_bot_email_replay_dispatch._find_receipt", return_value="receipt"):
            self.assertEqual(acknowledge_message(snapshot, plan, entry, accounts), "deleted")
        accounts[SOURCE_ACCOUNT].sqs.delete_message.assert_called_once()
        ack = next(item for item in destination.table.items.values()
                   if item.get("entity") == "MAIL_REPLAY_ACK")
        self.assertEqual(ack["state"], "deleted")

    def test_imported_source_inbox_recovers_existing_pending_turn_without_duplicate_row(self) -> None:
        entry = self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10)
        snapshot = self._snapshot([entry])
        inbox_key = "INBOX#bot-1#2026-09-30T04:10:00.000Z#imported"
        turn_id = str(uuid.uuid4())
        canonical = str(uuid.uuid4())
        observation_id = entry["observations"][0]["id"]
        decisions = {"schemaVersion": 1, "snapshotDigest": snapshot["snapshotDigest"],
                     "observations": {observation_id: {
                         "reviewed": True, "action": "imported", "canonicalId": canonical,
                         "primary": True, "delivery": "automatic",
                         "userId": self.owner, "botId": "bot-1", "inboxKey": inbox_key,
                         "note": "Matched the already migrated inbox and its pending turn.",
                     }}}
        plan = reviewed_plan(snapshot, decisions)
        self.assertEqual(len(plan["imports"]), 1)
        imported = plan["imports"][0]
        accounts = self._accounts([entry])
        destination = accounts[DESTINATION_ACCOUNT]
        destination.table.items[f"USER#{self.owner}", inbox_key] = {
            "pk": f"USER#{self.owner}", "sk": inbox_key, "entity": "BOT_EMAIL",
            "botId": "bot-1", "recipient": self.address,
            "sesMessageId": "src-1", "rawObjectKey": "received/src-1",
            "receivedAt": "2026-09-30T04:10:00.000Z",
            "disposition": "automatic", "authentication": "verified",
            "from": "owner@example.com", "linkedTurnId": turn_id,
        }
        apply_import(snapshot, imported, accounts)
        self.assertEqual(len([item for item in destination.table.items.values()
                              if item.get("entity") == "BOT_EMAIL"]), 1)
        turn_key = f"TURN#2026-09-30T04:10:00.000Z#{turn_id}"
        destination.table.items[f"CHAT#{self.owner}#bot-1", turn_key] = {
            "pk": f"CHAT#{self.owner}#bot-1", "sk": turn_key,
            "entity": "TURN", "id": turn_id, "status": "PENDING",
            "source": "email", "emailSesMessageId": "src-1",
        }
        with patch("_bot_email_replay_dispatch.send_job") as send:
            self.assertEqual(dispatch_import(snapshot, imported, accounts), "queued")
        self.assertEqual(send.call_args.args[2]["type"], "AGENT_REPLY")
        self.assertEqual(send.call_args.args[2]["turnKey"], turn_key)

    def test_unclassified_raw_mime_blocks_reviewed_plan(self) -> None:
        entry = self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10)
        snapshot = self._snapshot([entry])
        snapshot["unclassifiedObjects"] = [{
            "account": DESTINATION_ACCOUNT, "bucket": f"raw-{DESTINATION_ACCOUNT}",
            "key": "received/unclassified", "mimeBytes": len(self.raw),
            "mimeSha256": hashlib.sha256(self.raw).hexdigest(),
        }]
        snapshot["snapshotDigest"] = digest({key: value for key, value in snapshot.items()
                                             if key != "snapshotDigest"})
        with self.assertRaisesRegex(ReplayError, "Unclassified raw MIME"):
            reviewed_plan(snapshot, self._decisions(snapshot))

    def test_apply_flag_is_checked_before_aws_session(self) -> None:
        entry = self._entry(SOURCE_ACCOUNT, "src-1", "q-1", 10)
        snapshot = self._snapshot([entry])
        decisions = self._decisions(snapshot)
        plan = reviewed_plan(snapshot, decisions)
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "snapshot.json"
            decisions_path = Path(directory) / "decisions.json"
            write_private(snapshot_path, snapshot)
            write_private(decisions_path, decisions)
            with (
                patch.dict("os.environ", {}, clear=True),
                patch("reconcile_bot_email.Account") as account,
                patch("sys.stderr"),
            ):
                self.assertEqual(main([
                    "apply", "--snapshot", str(snapshot_path),
                    "--decisions", str(decisions_path),
                    "--source-profile", "source", "--destination-profile", "destination",
                    "--expected-plan-digest", plan["planDigest"],
                ]), 1)
                account.assert_not_called()

    def test_owner_only_private_files_and_write_flag_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            write_private(path, {"schemaVersion": 1})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_private(path), {"schemaVersion": 1})
            with self.assertRaises(FileExistsError):
                write_private(path, {})
            path.chmod(0o644)
            with self.assertRaises(ReplayError):
                read_private(path)


if __name__ == "__main__":
    unittest.main()
