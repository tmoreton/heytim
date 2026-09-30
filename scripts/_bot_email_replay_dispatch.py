"""Resumable reviewed outbox dispatch and capture-message acknowledgement."""

from __future__ import annotations

import hashlib
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from _bot_email_replay_apply import _destination_mime, _same_mime, verify_rejection
from _bot_email_replay_aws import Account
from _bot_email_replay_imported import verify_import
from _bot_email_replay_plan import (
    DESTINATION_ACCOUNT,
    ReplayError,
    digest,
    validate_snapshot,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/API/amplify/functions"))
from shared.bot_inbox import current_mail_address
from shared.job_envelope import send_job

DISPATCH_LEASE_SECONDS = 120
DISPATCH_RETRY_SECONDS = 300
MAX_DISPATCH_ATTEMPTS = 20


def verify_persisted(snapshot: dict, group: dict, destination: Account) -> tuple[dict, dict, dict | None]:
    if destination.account != DESTINATION_ACCOUNT:
        raise ReplayError("Only the destination account may hold replay state")
    observations = {item["id"]: item for item in validate_snapshot(snapshot)}
    primary = observations.get(group["primary"])
    if not primary or primary["id"] not in group["observationIds"]:
        raise ReplayError("Reviewed primary observation is missing")
    marker_key = {"pk": f"MAIL_REPLAY#{group['canonicalId']}", "sk": "RECEIPT"}
    marker = destination.table.get_item(Key=marker_key, ConsistentRead=True).get("Item")
    if not marker or any((
        marker.get("canonicalId") != group["canonicalId"],
        marker.get("evidenceDigest") != digest(group),
        marker.get("recipient") != group["recipient"],
        marker.get("mimeSha256") != group["mimeSha256"],
        marker.get("delivery") != group["delivery"],
        marker.get("rawObjectKey") != primary["key"],
    )):
        raise ReplayError("Destination replay marker is missing or divergent")
    inbox = destination.table.get_item(
        Key={"pk": f"USER#{marker['routeUserId']}", "sk": marker["inboxKey"]},
        ConsistentRead=True,
    ).get("Item")
    if not inbox or any((
        inbox.get("replayCanonicalId") != group["canonicalId"],
        inbox.get("recipient") != group["recipient"],
        inbox.get("rawSha256") != group["mimeSha256"],
        inbox.get("rawObjectKey") != marker["rawObjectKey"],
        inbox.get("botId") != marker["routeBotId"],
    )):
        raise ReplayError("Destination inbox row is missing or divergent")
    bot = destination.table.get_item(
        Key={"pk": f"USER#{marker['routeUserId']}", "sk": f"BOT#{marker['routeBotId']}"},
        ConsistentRead=True,
    ).get("Item")
    if (
        not bot or bot.get("id") != marker["routeBotId"]
        or bot.get("emailToken") != marker["routeEmailToken"]
        or current_mail_address(marker["routeUserId"], bot) != group["recipient"]
    ):
        raise ReplayError("Destination bot route changed after replay")
    _destination_mime(destination, primary["key"], primary)
    outbox = None
    if group["delivery"] == "automatic":
        outbox = destination.table.get_item(
            Key={"pk": marker["pk"], "sk": "OUTBOX"}, ConsistentRead=True
        ).get("Item")
        if not outbox or any((
            outbox.get("canonicalId") != group["canonicalId"],
            outbox.get("evidenceDigest") != digest(group),
            outbox.get("inboxKey") != marker["inboxKey"],
            outbox.get("userId") != marker["routeUserId"],
            outbox.get("botId") != marker["routeBotId"],
            outbox.get("turnId") != marker["turnId"],
            inbox.get("linkedTurnId") != marker["turnId"],
            inbox.get("disposition") != "automatic",
        )):
            raise ReplayError("Automatic replay outbox is missing or divergent")
    return marker, inbox, outbox


def _turn(destination: Account, marker: dict, outbox: dict) -> dict | None:
    return destination.table.get_item(
        Key={
            "pk": f"CHAT#{outbox['userId']}#{outbox['botId']}",
            "sk": f"TURN#{outbox['receivedAt']}#{outbox['turnId']}",
        },
        ConsistentRead=True,
    ).get("Item")


def dispatch_group(snapshot: dict, group: dict, destination: Account) -> str:
    marker, inbox, outbox = verify_persisted(snapshot, group, destination)
    return _dispatch_outbox(marker, inbox, outbox, destination)


def dispatch_import(snapshot: dict, imported: dict, accounts: dict[str, Account]) -> str:
    marker, inbox, outbox = verify_import(snapshot, imported, accounts)
    return _dispatch_outbox(marker, inbox, outbox, accounts[DESTINATION_ACCOUNT])


def _dispatch_outbox(marker: dict, inbox: dict, outbox: dict | None,
                     destination: Account) -> str:
    if outbox is None:
        return "review_only"
    if outbox.get("state") == "observed":
        return "observed"
    if outbox.get("state") != "pending":
        raise ReplayError("Replay outbox has an unknown state")
    turn = _turn(destination, marker, outbox)
    if turn and (
        turn.get("source") != "email"
        or turn.get("id") != outbox["turnId"]
        or turn.get("emailSesMessageId") != inbox.get("sesMessageId")
    ):
        raise ReplayError("Existing turn conflicts with reviewed replay outbox")
    status = turn.get("status") if turn else None
    if status in {"COMPLETE", "ERROR", "WAITING", "NEEDS_INPUT", "AWAITING_APPROVAL", "AWAITING_DEVICE"}:
        destination.table.update_item(
            Key={"pk": outbox["pk"], "sk": outbox["sk"]},
            UpdateExpression="SET #state = :observed, turnStatus = :status, observedAt = :now",
            ConditionExpression="#state = :pending",
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={
                ":observed": "observed", ":pending": "pending", ":status": status,
                ":now": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        return "observed"
    if status == "RUNNING":
        return "running"
    if status not in {None, "PENDING"}:
        raise ReplayError("Existing turn has an unknown state")
    now = int(time.time())
    last_queued = outbox.get("lastQueuedEpoch", 0)
    if isinstance(last_queued, int) and last_queued + DISPATCH_RETRY_SECONDS > now:
        return "waiting"
    owner = str(uuid.uuid4())
    try:
        destination.table.update_item(
            Key={"pk": outbox["pk"], "sk": outbox["sk"]},
            UpdateExpression=(
                "SET dispatchLeaseOwner = :owner, dispatchLeaseUntil = :until "
                "ADD dispatchAttempts :one"
            ),
            ConditionExpression=(
                "#state = :pending AND dispatchAttempts < :maximum AND "
                "(attribute_not_exists(dispatchLeaseUntil) OR dispatchLeaseUntil < :now)"
            ),
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={
                ":owner": owner, ":until": now + DISPATCH_LEASE_SECONDS,
                ":one": 1, ":pending": "pending", ":maximum": MAX_DISPATCH_ATTEMPTS,
                ":now": now,
            },
        )
    except destination.table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ReplayError("Replay outbox is leased, exhausted, or changed") from None
    if turn:
        request = {
            "type": "AGENT_REPLY",
            "userId": outbox["userId"],
            "botId": outbox["botId"],
            "turnKey": turn["sk"],
            "correlationId": outbox["turnId"],
        }
    else:
        request = {
            "type": "EMAIL_INBOUND",
            "userId": outbox["userId"],
            "botId": outbox["botId"],
            "inboxKey": outbox["inboxKey"],
            "turnId": outbox["turnId"],
            "correlationId": outbox["turnId"],
        }
    # The transaction created the outbox before this send. A crash here is
    # recoverable: the lease expires and a retry sends the same stable turn.
    send_job(destination.sqs, destination.job_queue_url, request)
    destination.table.update_item(
        Key={"pk": outbox["pk"], "sk": outbox["sk"]},
        UpdateExpression=(
            "SET lastQueuedEpoch = :now, lastQueuedAt = :iso, lastQueuedType = :kind "
            "REMOVE dispatchLeaseOwner, dispatchLeaseUntil"
        ),
        ConditionExpression="#state = :pending AND dispatchLeaseOwner = :owner",
        ExpressionAttributeNames={"#state": "state"},
        ExpressionAttributeValues={
            ":now": now, ":iso": datetime.now(UTC).isoformat(timespec="seconds"),
            ":kind": request["type"], ":pending": "pending", ":owner": owner,
        },
    )
    return "queued"


def _ack_ledger_key(account: str, sqs_message_id: str) -> dict[str, str]:
    return {
        "pk": f"MAIL_REPLAY_ACK#{hashlib.sha256((account + ':' + sqs_message_id).encode()).hexdigest()}",
        "sk": "RECEIPT",
    }


def _find_receipt(account: Account, message_id: str, body: str, max_messages: int) -> str:
    handles: list[str] = []
    found: str | None = None
    inspected: set[str] = set()
    empty = 0
    try:
        while empty < 3 and len(inspected) < max_messages:
            response = account.sqs.receive_message(
                QueueUrl=account.queue_url, MaxNumberOfMessages=10,
                VisibilityTimeout=30, WaitTimeSeconds=1,
            )
            messages = response.get("Messages", [])
            empty = empty + 1 if not messages else 0
            for item in messages:
                handles.append(item["ReceiptHandle"])
                inspected.add(item["MessageId"])
                if item["MessageId"] == message_id:
                    if item["Body"] != body:
                        raise ReplayError("Captured SQS message body changed")
                    found = item["ReceiptHandle"]
                    return found
        raise ReplayError("Reviewed SQS notification is not currently visible")
    finally:
        for handle in handles:
            if handle != found:
                account.sqs.change_message_visibility(
                    QueueUrl=account.queue_url,
                    ReceiptHandle=handle,
                    VisibilityTimeout=0,
                )


def acknowledge_message(snapshot: dict, plan: dict, entry: dict,
                        accounts: dict[str, Account], max_messages: int = 10000) -> str:
    account = accounts[entry["account"]]
    destination = accounts[DESTINATION_ACCOUNT]
    observation_ids = {item["id"] for item in entry["observations"]}
    associated = [
        group for group in plan["groups"]
        if observation_ids.intersection(group["observationIds"])
    ]
    imported = [
        item for item in plan["imports"]
        if observation_ids.intersection(item["observationIds"])
    ]
    rejected = [item for item in plan["rejects"]
                if item["observationId"] in observation_ids]
    covered = ({identifier for group in associated for identifier in group["observationIds"]}
               | {identifier for group in imported for identifier in group["observationIds"]}
               | {item["observationId"] for item in rejected})
    if observation_ids - covered:
        raise ReplayError("Held or unreviewed recipient keeps its SQS message in capture")
    for observation in entry["observations"]:
        raw = account.read_mime(observation["bucket"], observation["key"])
        if not _same_mime(observation, raw):
            raise ReplayError("Captured same-account MIME changed before acknowledgement")
    for group in associated:
        verify_persisted(snapshot, group, destination)
    for group in imported:
        verify_import(snapshot, group, accounts)
    for rejection in rejected:
        verify_rejection(snapshot, rejection, accounts)
    key = _ack_ledger_key(account.account, entry["sqsMessageId"])
    expected = {
        **key,
        "entity": "MAIL_REPLAY_ACK",
        "account": account.account,
        "sqsMessageId": entry["sqsMessageId"],
        "bodySha256": hashlib.sha256(entry["body"].encode()).hexdigest(),
        "canonicalIds": sorted(group["canonicalId"] for group in associated + imported),
        "rejectionIds": sorted(item["observationId"] for item in rejected),
        "state": "intent",
    }
    existing = destination.table.get_item(Key=key, ConsistentRead=True).get("Item")
    if existing:
        for field in ("account", "sqsMessageId", "bodySha256", "canonicalIds", "rejectionIds"):
            if existing.get(field) != expected[field]:
                raise ReplayError("Capture acknowledgement ledger conflicts with review")
    else:
        destination.table.put_item(Item=expected, ConditionExpression="attribute_not_exists(pk)")
    receipt = _find_receipt(account, entry["sqsMessageId"], entry["body"], max_messages)
    account.sqs.delete_message(QueueUrl=account.queue_url, ReceiptHandle=receipt)
    destination.table.update_item(
        Key=key,
        UpdateExpression="SET #state = :deleted, deletedAt = :now",
        ConditionExpression="bodySha256 = :hash AND #state = :intent",
        ExpressionAttributeNames={"#state": "state"},
        ExpressionAttributeValues={
            ":deleted": "deleted", ":intent": "intent", ":hash": expected["bodySha256"],
            ":now": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    return "deleted"
