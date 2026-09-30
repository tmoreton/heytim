"""Destination-only MIME copy and atomic replay marker/inbox/outbox writes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import sys
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from _bot_email_replay_aws import Account
from _bot_email_replay_mime import MAX_PREVIEW_BYTES, preview, reply_body
from _bot_email_replay_plan import (
    DESTINATION_ACCOUNT,
    ReplayError,
    digest,
    validate_snapshot,
)
from botocore.exceptions import BotoCoreError, ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/API/amplify/functions"))
from shared.bot_inbox import current_mail_address, mail_alias_key, resolve_mail_address


def _observation_map(snapshot: dict) -> dict[str, dict]:
    return {item["id"]: item for item in validate_snapshot(snapshot)}


def _same_mime(item: dict, raw: bytes) -> bool:
    return (
        len(raw) == item["mimeBytes"]
        and hmac.compare_digest(hashlib.sha256(raw).hexdigest(), item["mimeSha256"])
    )


def _destination_mime(destination: Account, key: str, expected: dict,
                      original: bytes | None = None) -> bytes:
    try:
        current = destination.read_mime(destination.raw_bucket, key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404"}:
            raise
        if original is None:
            raise ReplayError("Destination MIME is missing") from error
        if not _same_mime(expected, original):
            raise ReplayError("Source MIME changed before destination copy")
        checksum = base64.b64encode(hashlib.sha256(original).digest()).decode("ascii")
        try:
            destination.s3.put_object(
                Bucket=destination.raw_bucket,
                Key=key,
                Body=original,
                IfNoneMatch="*",
                ChecksumSHA256=checksum,
                ServerSideEncryption="AES256",
                ExpectedBucketOwner=DESTINATION_ACCOUNT,
            )
        except ClientError as put_error:
            if put_error.response.get("Error", {}).get("Code") not in {"PreconditionFailed", "412"}:
                raise
        current = destination.read_mime(destination.raw_bucket, key)
    if not _same_mime(expected, current):
        raise ReplayError("Destination MIME has divergent bytes")
    return current


def _route(destination: Account, primary: dict, delivery: str, mime_preview: dict) -> tuple[str, dict]:
    address = primary["recipient"]
    resolved = resolve_mail_address(destination.table, address)
    if not resolved:
        raise ReplayError("Destination has no current route for the reviewed recipient")
    user_id, bot = resolved
    if (
        bot.get("entity") != "BOT"
        or not isinstance(bot.get("id"), str)
        or not isinstance(bot.get("emailToken"), str)
        or current_mail_address(user_id, bot) != address
    ):
        raise ReplayError("Destination bot route changed")
    if delivery == "automatic":
        owner = bot.get("emailOwnerAddress")
        if (
            bot.get("emailInboundMode") != "automatic"
            or primary["verdicts"]["dmarc"] != "PASS"
            or not isinstance(owner, str)
            or not hmac.compare_digest(owner.strip().lower(), primary["source"])
            or not hmac.compare_digest(owner.strip().lower(), mime_preview["from"].strip().lower())
            or mime_preview["autoSubmitted"].strip().lower() not in {"", "no"}
            or primary["mimeBytes"] > MAX_PREVIEW_BYTES
        ):
            raise ReplayError("Automatic replay failed owner, DMARC, or bot-mode checks")
    return user_id, bot


def _receipt_items(group: dict, primary: dict, user_id: str, bot: dict,
                   mime_preview: dict, raw_key: str) -> tuple[dict, dict, dict | None]:
    canonical = group["canonicalId"]
    delivery = group["delivery"]
    bot_id = bot["id"]
    recipient = group["recipient"]
    received_at = primary["receivedAt"]
    row_digest = hashlib.sha256(f"{canonical}\0{recipient}".encode()).hexdigest()[:24]
    inbox_key = f"INBOX#{bot_id}#{received_at}#{row_digest}"
    turn_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"heytim-email-replay:{canonical}"))
    evidence_digest = digest(group)
    marker = {
        "pk": f"MAIL_REPLAY#{canonical}",
        "sk": "RECEIPT",
        "entity": "MAIL_REPLAY",
        "canonicalId": canonical,
        "evidenceDigest": evidence_digest,
        "observationIds": group["observationIds"],
        "recipient": recipient,
        "mimeSha256": group["mimeSha256"],
        "routeUserId": user_id,
        "routeBotId": bot_id,
        "routeEmailToken": bot["emailToken"],
        "inboxKey": inbox_key,
        "rawObjectKey": raw_key,
        "delivery": delivery,
        "turnId": turn_id if delivery == "automatic" else "",
        "recordedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    inbox = {
        "pk": f"USER#{user_id}",
        "sk": inbox_key,
        "entity": "BOT_EMAIL",
        "botId": bot_id,
        "receivedAt": received_at,
        "recipient": recipient,
        "sesMessageId": primary["sesMessageId"],
        "rawObjectKey": raw_key,
        "rawSha256": group["mimeSha256"],
        "replayCanonicalId": canonical,
        "authentication": "verified" if primary["verdicts"]["dmarc"] == "PASS" else "unverified",
        "disposition": delivery,
        **({"linkedTurnId": turn_id, "conversationBody": reply_body(mime_preview["body"])}
           if delivery == "automatic" else {}),
        **mime_preview,
    }
    outbox = None
    if delivery == "automatic":
        outbox = {
            "pk": f"MAIL_REPLAY#{canonical}",
            "sk": "OUTBOX",
            "entity": "MAIL_REPLAY_OUTBOX",
            "canonicalId": canonical,
            "evidenceDigest": evidence_digest,
            "state": "pending",
            "userId": user_id,
            "botId": bot_id,
            "inboxKey": inbox_key,
            "turnId": turn_id,
            "receivedAt": received_at,
            "dispatchAttempts": 0,
        }
    return marker, inbox, outbox


def _verify_recorded(destination: Account, marker: dict, inbox: dict,
                     outbox: dict | None) -> bool:
    table = destination.table
    saved_marker = table.get_item(
        Key={"pk": marker["pk"], "sk": marker["sk"]}, ConsistentRead=True
    ).get("Item")
    if not saved_marker:
        return False
    immutable = (
        "canonicalId", "evidenceDigest", "observationIds", "recipient",
        "mimeSha256", "routeUserId", "routeBotId", "routeEmailToken",
        "inboxKey", "rawObjectKey", "delivery", "turnId",
    )
    if any(saved_marker.get(key) != marker[key] for key in immutable):
        raise ReplayError("Existing replay marker conflicts with reviewed delivery")
    saved_inbox = table.get_item(
        Key={"pk": inbox["pk"], "sk": inbox["sk"]}, ConsistentRead=True
    ).get("Item")
    if not saved_inbox or any(
        saved_inbox.get(key) != inbox[key]
        for key in ("replayCanonicalId", "recipient", "rawSha256", "rawObjectKey",
                    "botId", "sesMessageId", "receivedAt", "authentication",
                    "disposition")
    ):
        raise ReplayError("Recorded replay marker has no matching inbox row")
    if outbox is not None:
        if saved_inbox.get("linkedTurnId") != outbox["turnId"]:
            raise ReplayError("Recorded inbox lost its automatic turn identity")
        saved_outbox = table.get_item(
            Key={"pk": outbox["pk"], "sk": outbox["sk"]}, ConsistentRead=True
        ).get("Item")
        if not saved_outbox or any(
            saved_outbox.get(key) != outbox[key]
            for key in ("canonicalId", "evidenceDigest", "userId", "botId", "inboxKey", "turnId")
        ):
            raise ReplayError("Recorded automatic mail has no matching durable outbox")
    return True


def _transaction(destination: Account, user_id: str, bot: dict, recipient: str,
                 marker: dict, inbox: dict, outbox: dict | None) -> None:
    table = destination.table
    token = hashlib.sha256((marker["canonicalId"] + marker["evidenceDigest"]).encode()).hexdigest()[:32]
    bot_conditions = "attribute_exists(pk) AND id = :botId AND emailToken = :token"
    bot_values = {":botId": bot["id"], ":token": bot["emailToken"]}
    if isinstance(bot.get("legacyEmailAddress"), str):
        bot_conditions += " AND legacyEmailAddress = :recipient"
        bot_values[":recipient"] = recipient
    else:
        bot_conditions += " AND attribute_not_exists(legacyEmailAddress)"
    if marker["delivery"] == "automatic":
        bot_conditions += " AND emailInboundMode = :automatic AND emailOwnerAddress = :owner"
        bot_values.update({":automatic": "automatic", ":owner": bot["emailOwnerAddress"]})
    operations = [
        {"ConditionCheck": {
            "TableName": table.name,
            "Key": {"pk": f"USER#{user_id}", "sk": "STATE"},
            "ConditionExpression": (
                "attribute_not_exists(accountStatus) OR "
                "(attribute_type(accountStatus, :type) AND "
                "accountStatus <> :deleting AND accountStatus <> :deleted)"
            ),
            "ExpressionAttributeValues": {":type": "S", ":deleting": "DELETING", ":deleted": "DELETED"},
        }},
        {"ConditionCheck": {
            "TableName": table.name,
            "Key": {"pk": f"USER#{user_id}", "sk": f"BOT#{bot['id']}"},
            "ConditionExpression": bot_conditions,
            "ExpressionAttributeValues": bot_values,
        }},
    ]
    if isinstance(bot.get("legacyEmailAddress"), str):
        operations.append({"ConditionCheck": {
            "TableName": table.name,
            "Key": mail_alias_key(recipient),
            "ConditionExpression": (
                "entity = :entity AND address = :address AND "
                "targetUserId = :user AND targetBotId = :bot"
            ),
            "ExpressionAttributeValues": {
                ":entity": "MAIL_ALIAS", ":address": recipient,
                ":user": user_id, ":bot": bot["id"],
            },
        }})
    for item in (marker, inbox, outbox):
        if item is not None:
            operations.append({"Put": {
                "TableName": table.name,
                "Item": item,
                "ConditionExpression": "attribute_not_exists(pk)",
            }})
    try:
        table.meta.client.transact_write_items(
            ClientRequestToken=token, TransactItems=deepcopy(operations)
        )
    except (BotoCoreError, ClientError):
        if not _verify_recorded(destination, marker, inbox, outbox):
            raise


def apply_group(snapshot: dict, group: dict, accounts: dict[str, Account]) -> dict:
    if set(accounts) != {"188757775631", DESTINATION_ACCOUNT}:
        raise ReplayError("Both exact accounts are required")
    observed = _observation_map(snapshot)
    primary = observed.get(group["primary"])
    if not primary or primary["id"] not in group["observationIds"]:
        raise ReplayError("Canonical primary is absent from the reviewed snapshot")
    destination = accounts[DESTINATION_ACCOUNT]
    for observation_id in group["observationIds"]:
        item = observed.get(observation_id)
        if not item:
            raise ReplayError("Reviewed observation is absent from private snapshot")
        evidence = accounts[item["account"]].read_mime(item["bucket"], item["key"])
        if not _same_mime(item, evidence):
            raise ReplayError("One account's captured MIME changed before replay")
    origin = accounts[primary["account"]]
    raw = origin.read_mime(primary["bucket"], primary["key"])
    if not _same_mime(primary, raw):
        raise ReplayError("Captured MIME changed before replay")
    mime_preview = preview(raw)
    if mime_preview["messageIdHeader"].lower() != primary.get("headerMessageId"):
        raise ReplayError("MIME Message-ID changed since private snapshot")
    user_id, bot = _route(destination, primary, group["delivery"], mime_preview)
    raw_key = primary["key"]
    _destination_mime(destination, raw_key, primary, raw)
    marker, inbox, outbox = _receipt_items(
        group, primary, user_id, bot, mime_preview, raw_key
    )
    if not _verify_recorded(destination, marker, inbox, outbox):
        _transaction(destination, user_id, bot, group["recipient"], marker, inbox, outbox)
    if not _verify_recorded(destination, marker, inbox, outbox):
        raise ReplayError("Replay transaction was not visible after write")
    _destination_mime(destination, raw_key, primary)
    return {"canonicalId": group["canonicalId"], "recorded": True,
            "automaticPending": outbox is not None}


def rejection_marker(snapshot: dict, rejection: dict, accounts: dict[str, Account]) -> dict:
    observed = _observation_map(snapshot)
    item = observed.get(rejection["observationId"])
    if not item or any((
        item["account"] != rejection["account"],
        item["mimeSha256"] != rejection["mimeSha256"],
        item["recipient"] != rejection["recipient"],
    )):
        raise ReplayError("Reviewed rejection no longer matches its observation")
    reason = rejection["reason"]
    if reason == "ses_spam" and item["verdicts"]["spam"] == "PASS":
        raise ReplayError("SES spam rejection lacks a failed verdict")
    if reason == "ses_virus" and item["verdicts"]["virus"] == "PASS":
        raise ReplayError("SES virus rejection lacks a failed verdict")
    if reason == "no_route" and any(
        resolve_mail_address(account.table, item["recipient"])
        for account in accounts.values()
    ):
        raise ReplayError("No-route rejection has a bot route in one account")
    if reason not in {"ses_spam", "ses_virus", "no_route"}:
        raise ReplayError("Unsupported reviewed rejection reason")
    return {
        "pk": f"MAIL_REPLAY_REJECT#{item['id']}",
        "sk": "RECEIPT",
        "entity": "MAIL_REPLAY_REJECT",
        "observationId": item["id"],
        "evidenceDigest": digest(rejection),
        "account": item["account"],
        "recipient": item["recipient"],
        "mimeSha256": item["mimeSha256"],
        "rawObjectKey": item["key"],
        "reason": reason,
    }


def verify_rejection(snapshot: dict, rejection: dict, accounts: dict[str, Account]) -> dict:
    marker = rejection_marker(snapshot, rejection, accounts)
    item = _observation_map(snapshot)[rejection["observationId"]]
    raw = accounts[item["account"]].read_mime(item["bucket"], item["key"])
    if not _same_mime(item, raw):
        raise ReplayError("Rejected same-account MIME changed")
    _destination_mime(accounts[DESTINATION_ACCOUNT], item["key"], item)
    destination = accounts[DESTINATION_ACCOUNT]
    saved = destination.table.get_item(
        Key={"pk": marker["pk"], "sk": marker["sk"]}, ConsistentRead=True
    ).get("Item")
    if not saved or any(saved.get(key) != value for key, value in marker.items()):
        raise ReplayError("Reviewed rejection marker is missing or divergent")
    return saved


def apply_rejection(snapshot: dict, rejection: dict, accounts: dict[str, Account]) -> dict:
    marker = rejection_marker(snapshot, rejection, accounts)
    item = _observation_map(snapshot)[rejection["observationId"]]
    origin = accounts[item["account"]]
    raw = origin.read_mime(item["bucket"], item["key"])
    if not _same_mime(item, raw):
        raise ReplayError("Rejected same-account MIME changed before copy")
    destination = accounts[DESTINATION_ACCOUNT]
    _destination_mime(destination, item["key"], item, raw)
    existing = destination.table.get_item(
        Key={"pk": marker["pk"], "sk": marker["sk"]}, ConsistentRead=True
    ).get("Item")
    if not existing:
        try:
            destination.table.meta.client.transact_write_items(
                ClientRequestToken=hashlib.sha256(marker["evidenceDigest"].encode()).hexdigest()[:32],
                TransactItems=[{"Put": {
                    "TableName": destination.table.name,
                    "Item": deepcopy(marker),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }}],
            )
        except (BotoCoreError, ClientError):
            verify_rejection(snapshot, rejection, accounts)
    return verify_rejection(snapshot, rejection, accounts)
