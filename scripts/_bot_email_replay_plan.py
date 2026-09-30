"""Pure, fail-closed reconciliation of private SES capture snapshots.

No SES IDs or MIME hashes are used as a canonical delivery ID. An operator
must review each recipient observation and explicitly assign a UUID.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any

SOURCE_ACCOUNT = "188757775631"
DESTINATION_ACCOUNT = "820323452649"
REGION = "us-east-1"
MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")


class ReplayError(RuntimeError):
    """A receipt, review decision, or live precondition is unsafe."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()


def _string(value: Any, label: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ReplayError(f"Invalid {label}")
    return value


def _timestamp(value: Any) -> str:
    text = _string(value, "SES timestamp", 80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReplayError("Invalid SES timestamp") from exc
    if parsed.tzinfo is None:
        raise ReplayError("SES timestamp is missing a timezone")
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_capture(body: str, account: str, queue_message_id: str, topic_arn: str,
                  permitted_buckets: set[str]) -> list[dict]:
    """Parse a wrapped SNS SQS body into one observation per envelope recipient."""
    if account not in {SOURCE_ACCOUNT, DESTINATION_ACCOUNT}:
        raise ReplayError("Unexpected capture account")
    _string(queue_message_id, "SQS message ID", 128)
    try:
        envelope = json.loads(body)
        notification = json.loads(envelope["Message"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReplayError("Malformed wrapped SNS notification") from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("Type") != "Notification"
        or envelope.get("TopicArn") != topic_arn
        or not isinstance(notification, dict)
        or notification.get("notificationType") != "Received"
    ):
        raise ReplayError("Unexpected SNS topic or SES notification type")
    sns_id = _string(envelope.get("MessageId"), "SNS message ID", 128)
    mail = notification.get("mail")
    receipt = notification.get("receipt")
    if not isinstance(mail, dict) or not isinstance(receipt, dict):
        raise ReplayError("SES mail or receipt is missing")
    ses_id = _string(mail.get("messageId"), "SES message ID", 200)
    if not MESSAGE_ID.fullmatch(ses_id):
        raise ReplayError("Invalid SES message ID")
    source = _string(mail.get("source"), "SES envelope sender", 320).strip().lower()
    received_at = _timestamp(mail.get("timestamp"))
    action = receipt.get("action")
    if not isinstance(action, dict) or action.get("type") != "S3":
        raise ReplayError("SES receipt was not stored in S3")
    bucket = _string(action.get("bucketName"), "SES bucket", 255)
    key = f"received/{ses_id}"
    if bucket not in permitted_buckets or action.get("objectKey") not in (None, ses_id, key):
        raise ReplayError("SES receipt bucket or object key changed")
    recipients = receipt.get("recipients")
    if not isinstance(recipients, list) or not recipients or len(recipients) > 50:
        raise ReplayError("SES receipt recipients are invalid")
    if any(not isinstance(value, str) or not value.strip() for value in recipients):
        raise ReplayError("SES receipt contains an invalid recipient")
    if len({value.strip().lower() for value in recipients}) != len(recipients):
        raise ReplayError("SES receipt has duplicate recipients")
    verdicts = {
        name: (receipt.get(f"{name}Verdict") or {}).get("status")
        for name in ("spam", "virus", "dmarc")
    }
    observations = []
    for value in recipients:
        recipient = value.strip().lower()
        if not recipient.endswith("@bots.heytim.ai") or len(recipient) > 320:
            raise ReplayError("SES recipient is outside the reviewed bot domain")
        identity = {
            "account": account,
            "sqsMessageId": queue_message_id,
            "snsMessageId": sns_id,
            "sesMessageId": ses_id,
            "recipient": recipient,
        }
        observations.append({
            "id": digest(identity),
            **identity,
            "source": source,
            "receivedAt": received_at,
            "bucket": bucket,
            "key": key,
            "verdicts": verdicts,
        })
    return observations


def snapshot_digest(snapshot: dict) -> str:
    if snapshot.get("schemaVersion") != 1:
        raise ReplayError("Unsupported capture snapshot version")
    return digest({key: value for key, value in snapshot.items() if key != "snapshotDigest"})


def validate_snapshot(snapshot: dict) -> list[dict]:
    if snapshot.get("schemaVersion") != 1 or snapshot.get("snapshotDigest") != snapshot_digest(snapshot):
        raise ReplayError("Private capture snapshot was altered")
    messages = snapshot.get("messages")
    if not isinstance(messages, list):
        raise ReplayError("Capture snapshot messages are invalid")
    orphans = snapshot.get("unclassifiedObjects")
    if not isinstance(orphans, list):
        raise ReplayError("Capture snapshot lacks unclassified-object inventory")
    for item in orphans:
        if (
            not isinstance(item, dict)
            or item.get("account") not in {SOURCE_ACCOUNT, DESTINATION_ACCOUNT}
            or not isinstance(item.get("bucket"), str)
            or not isinstance(item.get("key"), str)
            or not SHA256.fullmatch(str(item.get("mimeSha256", "")))
            or not isinstance(item.get("mimeBytes"), int)
        ):
            raise ReplayError("Malformed unclassified MIME evidence")
    observed: list[dict] = []
    message_keys: set[tuple[str, str]] = set()
    observation_ids: set[str] = set()
    accounts = snapshot.get("accounts")
    if not isinstance(accounts, dict) or set(accounts) != {SOURCE_ACCOUNT, DESTINATION_ACCOUNT}:
        raise ReplayError("Capture snapshot accounts changed")
    for account, resources in accounts.items():
        if resources.get("account") != account or resources.get("region") != REGION:
            raise ReplayError("Capture snapshot account or region changed")
        for field in ("appStack", "captureStack", "topicArn", "queueArn", "queueUrl",
                      "jobQueueUrl", "table", "rawBucket", "quarantineBucket"):
            _string(resources.get(field), field, 500)
    for entry in messages:
        if not isinstance(entry, dict):
            raise ReplayError("Malformed captured SQS message")
        account = entry.get("account")
        if account not in accounts:
            raise ReplayError("Captured SQS message has an unexpected account")
        queue_id = _string(entry.get("sqsMessageId"), "SQS message ID", 128)
        if (account, queue_id) in message_keys:
            raise ReplayError("Duplicate SQS message in snapshot")
        message_keys.add((account, queue_id))
        body = _string(entry.get("body"), "wrapped SNS body", 262144)
        resources = accounts[account]
        parsed = parse_capture(body, account, queue_id, resources["topicArn"],
                               {resources["rawBucket"], resources["quarantineBucket"]})
        evidence = entry.get("observations")
        if not isinstance(evidence, list) or len(evidence) != len(parsed):
            raise ReplayError("Captured MIME evidence is incomplete")
        by_id = {item["id"]: item for item in evidence if isinstance(item, dict)}
        if len(by_id) != len(parsed):
            raise ReplayError("Captured MIME evidence has duplicate observations")
        for item in parsed:
            saved = by_id.get(item["id"])
            if not isinstance(saved, dict) or any(saved.get(k) != v for k, v in item.items()):
                raise ReplayError("Captured SES evidence changed")
            if not SHA256.fullmatch(str(saved.get("mimeSha256", ""))):
                raise ReplayError("Captured MIME hash is invalid")
            if not isinstance(saved.get("mimeBytes"), int) or saved["mimeBytes"] < 1:
                raise ReplayError("Captured MIME size is invalid")
            if saved["id"] in observation_ids:
                raise ReplayError("Duplicate recipient observation")
            observation_ids.add(saved["id"])
            observed.append(saved)
    return sorted(observed, key=lambda item: item["id"])


def reviewed_plan(snapshot: dict, decisions: dict) -> dict:
    observations = validate_snapshot(snapshot)
    if snapshot["unclassifiedObjects"]:
        raise ReplayError("Unclassified raw MIME blocks reviewed replay planning")
    if decisions.get("schemaVersion") != 1 or decisions.get("snapshotDigest") != snapshot["snapshotDigest"]:
        raise ReplayError("Review decisions do not match the capture snapshot")
    review = decisions.get("observations")
    by_id = {item["id"]: item for item in observations}
    if not isinstance(review, dict) or set(review) != set(by_id):
        raise ReplayError("Every recipient observation needs exactly one review decision")
    groups: dict[str, list[tuple[dict, dict]]] = {}
    imports: dict[str, list[tuple[dict, dict]]] = {}
    holds = 0
    rejects = []
    for observation_id, choice in review.items():
        if not isinstance(choice, dict) or choice.get("reviewed") is not True:
            raise ReplayError("An observation has not been explicitly reviewed")
        note = choice.get("note")
        if not isinstance(note, str) or len(note.strip()) < 8 or len(note) > 500:
            raise ReplayError("Review note is missing or too long")
        if choice.get("action") == "hold":
            holds += 1
            continue
        if choice.get("action") == "reject":
            reason = choice.get("reason")
            item = by_id[observation_id]
            if reason == "ses_spam" and item["verdicts"]["spam"] == "PASS":
                raise ReplayError("SES spam rejection lacks a failed spam verdict")
            if reason == "ses_virus" and item["verdicts"]["virus"] == "PASS":
                raise ReplayError("SES virus rejection lacks a failed virus verdict")
            if reason not in {"ses_spam", "ses_virus", "no_route"}:
                raise ReplayError("Reviewed rejection reason is unsupported")
            rejects.append({
                "observationId": observation_id,
                "reason": reason,
                "account": item["account"],
                "mimeSha256": item["mimeSha256"],
                "recipient": item["recipient"],
            })
            continue
        if choice.get("action") == "imported":
            item = by_id[observation_id]
            if item["account"] != SOURCE_ACCOUNT:
                raise ReplayError("Only a source notification can match an imported inbox")
            if choice.get("delivery") not in {"review", "automatic"}:
                raise ReplayError("Imported delivery needs its reviewed disposition")
            bot_id = _string(choice.get("botId"), "imported bot ID", 400)
            _string(choice.get("userId"), "imported destination user ID", 255)
            inbox_key = _string(choice.get("inboxKey"), "imported inbox key", 900)
            if not inbox_key.startswith(f"INBOX#{bot_id}#"):
                raise ReplayError("Imported inbox key is outside its reviewed bot")
            try:
                canonical = str(uuid.UUID(choice.get("canonicalId")))
            except (TypeError, ValueError) as exc:
                raise ReplayError("Imported delivery needs a canonical UUID") from exc
            if choice.get("canonicalId") != canonical:
                raise ReplayError("Imported canonical UUID must use normalized spelling")
            imports.setdefault(canonical, []).append((item, choice))
            continue
        if choice.get("action") != "replay" or choice.get("delivery") not in {"review", "automatic"}:
            raise ReplayError("Invalid reviewed mail disposition")
        canonical = choice.get("canonicalId")
        try:
            canonical = str(uuid.UUID(canonical))
        except (TypeError, ValueError) as exc:
            raise ReplayError("A replay decision needs a canonical UUID") from exc
        if choice.get("canonicalId") != canonical:
            raise ReplayError("Canonical UUID must use normalized spelling")
        groups.setdefault(canonical, []).append((by_id[observation_id], choice))
    planned = []
    for canonical, members in sorted(groups.items()):
        primaries = [item for item, choice in members if choice.get("primary") is True]
        if len(primaries) != 1:
            raise ReplayError("A canonical delivery needs exactly one reviewed primary")
        primary = primaries[0]
        recipient = primary["recipient"]
        delivery = members[0][1]["delivery"]
        per_account: dict[str, set[str]] = {}
        for item, choice in members:
            if item["recipient"] != recipient or choice["delivery"] != delivery:
                raise ReplayError("Canonical delivery merges recipients or dispositions")
            if item["verdicts"]["spam"] != "PASS" or item["verdicts"]["virus"] != "PASS":
                raise ReplayError("Failed SES safety verdict cannot be replayed")
            per_account.setdefault(item["account"], set()).add(item["sesMessageId"])
            if item["mimeSha256"] != primary["mimeSha256"] or item.get("headerMessageId") != primary.get("headerMessageId"):
                raise ReplayError("Canonical delivery merges different MIME or Message-ID evidence")
            if item["source"] != primary["source"]:
                raise ReplayError("Canonical delivery merges different envelope senders")
            delta = abs((datetime.fromisoformat(item["receivedAt"].replace("Z", "+00:00"))
                         - datetime.fromisoformat(primary["receivedAt"].replace("Z", "+00:00"))).total_seconds())
            if delta > 600:
                raise ReplayError("Canonical delivery merges receipts more than ten minutes apart")
        if any(len(ids) != 1 for ids in per_account.values()):
            raise ReplayError("Canonical delivery merges distinct SES receipts in one account")
        if len(per_account) > 1 and not primary.get("headerMessageId"):
            raise ReplayError("Cross-account match lacks an RFC Message-ID")
        planned.append({
            "canonicalId": canonical,
            "primary": primary["id"],
            "observationIds": sorted(item["id"] for item, _ in members),
            "recipient": recipient,
            "mimeSha256": primary["mimeSha256"],
            "delivery": delivery,
        })
    planned_imports = []
    for canonical, members in sorted(imports.items()):
        if canonical in groups:
            raise ReplayError("Canonical UUID cannot mix new and imported delivery")
        primaries = [item for item, choice in members if choice.get("primary") is True]
        if len(primaries) != 1:
            raise ReplayError("Imported delivery needs exactly one primary notification")
        primary = primaries[0]
        expected = members[0][1]
        for item, choice in members:
            if any((
                item["account"] != SOURCE_ACCOUNT,
                item["sesMessageId"] != primary["sesMessageId"],
                item["recipient"] != primary["recipient"],
                item["mimeSha256"] != primary["mimeSha256"],
                item.get("headerMessageId") != primary.get("headerMessageId"),
                item["source"] != primary["source"],
                any(choice.get(key) != expected.get(key)
                    for key in ("userId", "botId", "inboxKey", "delivery")),
            )):
                raise ReplayError("Imported group merges different deliveries or rows")
        planned_imports.append({
            "canonicalId": canonical,
            "primary": primary["id"],
            "observationIds": sorted(item["id"] for item, _ in members),
            "recipient": primary["recipient"],
            "mimeSha256": primary["mimeSha256"],
            "userId": expected["userId"],
            "botId": expected["botId"],
            "inboxKey": expected["inboxKey"],
            "delivery": expected["delivery"],
        })
    result = {
        "schemaVersion": 1,
        "snapshotDigest": snapshot["snapshotDigest"],
        "reviewDigest": digest(decisions),
        "holds": holds,
        "groups": planned,
        "imports": planned_imports,
        "rejects": sorted(rejects, key=lambda item: item["observationId"]),
    }
    result["planDigest"] = digest(result)
    return result
