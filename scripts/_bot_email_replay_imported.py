"""Review and recover source mail already processed before source freeze."""

from __future__ import annotations

import hashlib
import hmac
import sys
from copy import deepcopy
from pathlib import Path

from _bot_email_replay_apply import _destination_mime, _same_mime
from _bot_email_replay_aws import Account
from _bot_email_replay_mime import preview
from _bot_email_replay_plan import (
    DESTINATION_ACCOUNT,
    SOURCE_ACCOUNT,
    ReplayError,
    digest,
    validate_snapshot,
)
from botocore.exceptions import BotoCoreError, ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/API/amplify/functions"))
from shared.bot_inbox import current_mail_address, mail_alias_key, resolve_mail_address


def _primary(snapshot: dict, imported: dict) -> dict:
    observations = {item["id"]: item for item in validate_snapshot(snapshot)}
    primary = observations.get(imported["primary"])
    if not primary or any((
        primary["id"] not in imported["observationIds"],
        primary["account"] != SOURCE_ACCOUNT,
        primary["recipient"] != imported["recipient"],
        primary["mimeSha256"] != imported["mimeSha256"],
    )):
        raise ReplayError("Imported delivery primary evidence changed")
    return primary


def _expected(imported: dict, primary: dict, inbox: dict, bot: dict) -> tuple[dict, dict | None]:
    canonical = imported["canonicalId"]
    delivery = imported["delivery"]
    turn_id = inbox.get("linkedTurnId") if delivery == "automatic" else ""
    if delivery == "automatic" and not isinstance(turn_id, str):
        raise ReplayError("Imported automatic inbox lost its linked turn ID")
    marker = {
        "pk": f"MAIL_REPLAY#{canonical}",
        "sk": "RECEIPT",
        "entity": "MAIL_REPLAY_IMPORTED",
        "canonicalId": canonical,
        "evidenceDigest": digest(imported),
        "observationIds": imported["observationIds"],
        "recipient": imported["recipient"],
        "mimeSha256": imported["mimeSha256"],
        "routeUserId": imported["userId"],
        "routeBotId": imported["botId"],
        "routeEmailToken": bot["emailToken"],
        "inboxKey": imported["inboxKey"],
        "rawObjectKey": primary["key"],
        "delivery": delivery,
        "turnId": turn_id,
    }
    outbox = None
    if delivery == "automatic":
        outbox = {
            "pk": marker["pk"], "sk": "OUTBOX",
            "entity": "MAIL_REPLAY_OUTBOX",
            "canonicalId": canonical,
            "evidenceDigest": marker["evidenceDigest"],
            "state": "pending",
            "userId": imported["userId"],
            "botId": imported["botId"],
            "inboxKey": imported["inboxKey"],
            "turnId": turn_id,
            "receivedAt": inbox["receivedAt"],
            "dispatchAttempts": 0,
        }
    return marker, outbox


def _read_existing(snapshot: dict, imported: dict, accounts: dict[str, Account]) -> tuple[dict, dict, dict, dict, dict | None]:
    primary = _primary(snapshot, imported)
    destination = accounts[DESTINATION_ACCOUNT]
    source = accounts[SOURCE_ACCOUNT]
    raw = source.read_mime(primary["bucket"], primary["key"])
    if not _same_mime(primary, raw):
        raise ReplayError("Already-imported source MIME changed")
    _destination_mime(destination, primary["key"], primary)
    inbox = destination.table.get_item(
        Key={"pk": f"USER#{imported['userId']}", "sk": imported["inboxKey"]},
        ConsistentRead=True,
    ).get("Item")
    if not inbox or any((
        inbox.get("entity") != "BOT_EMAIL",
        inbox.get("botId") != imported["botId"],
        inbox.get("recipient") != imported["recipient"],
        inbox.get("sesMessageId") != primary["sesMessageId"],
        inbox.get("rawObjectKey") != primary["key"],
        inbox.get("receivedAt") != primary["receivedAt"],
        inbox.get("disposition") != imported["delivery"],
    )):
        raise ReplayError("Reviewed imported inbox row is missing or divergent")
    resolved = resolve_mail_address(destination.table, imported["recipient"])
    if not resolved or resolved[0] != imported["userId"] or resolved[1].get("id") != imported["botId"]:
        raise ReplayError("Imported inbox route does not match destination bot")
    bot = resolved[1]
    if current_mail_address(imported["userId"], bot) != imported["recipient"]:
        raise ReplayError("Imported inbox route changed")
    if imported["delivery"] == "automatic":
        mime_preview = preview(raw)
        owner = bot.get("emailOwnerAddress")
        if any((
            inbox.get("authentication") != "verified",
            primary["verdicts"]["dmarc"] != "PASS",
            not isinstance(owner, str),
            not isinstance(inbox.get("linkedTurnId"), str),
            not (bot.get("emailInboundMode") == "automatic" or inbox.get("threadReply") is True),
        )):
            raise ReplayError("Imported automatic mail is no longer trusted")
        if not (hmac.compare_digest(owner.strip().lower(), primary["source"])
                and hmac.compare_digest(owner.strip().lower(), mime_preview["from"].strip().lower())
                and hmac.compare_digest(owner.strip().lower(), inbox.get("from", "").strip().lower())):
            raise ReplayError("Imported automatic sender identity changed")
    marker, outbox = _expected(imported, primary, inbox, bot)
    return primary, bot, inbox, marker, outbox


def verify_import(snapshot: dict, imported: dict, accounts: dict[str, Account]) -> tuple[dict, dict, dict | None]:
    _primary_item, _bot, inbox, marker, outbox = _read_existing(snapshot, imported, accounts)
    destination = accounts[DESTINATION_ACCOUNT]
    saved = destination.table.get_item(
        Key={"pk": marker["pk"], "sk": marker["sk"]}, ConsistentRead=True
    ).get("Item")
    if not saved or any(saved.get(key) != value for key, value in marker.items()):
        raise ReplayError("Imported replay marker is missing or divergent")
    if outbox:
        saved_outbox = destination.table.get_item(
            Key={"pk": outbox["pk"], "sk": outbox["sk"]}, ConsistentRead=True
        ).get("Item")
        if not saved_outbox or any(
            saved_outbox.get(key) != outbox[key]
            for key in ("entity", "canonicalId", "evidenceDigest", "userId", "botId", "inboxKey", "turnId")
        ):
            raise ReplayError("Imported automatic mail has no matching outbox")
        outbox = saved_outbox
    return saved, inbox, outbox


def apply_import(snapshot: dict, imported: dict, accounts: dict[str, Account]) -> dict:
    primary = _primary(snapshot, imported)
    source = accounts[SOURCE_ACCOUNT]
    destination = accounts[DESTINATION_ACCOUNT]
    raw = source.read_mime(primary["bucket"], primary["key"])
    if not _same_mime(primary, raw):
        raise ReplayError("Already-imported source MIME changed before copy")
    _destination_mime(destination, primary["key"], primary, raw)
    _primary_item, bot, inbox, marker, outbox = _read_existing(snapshot, imported, accounts)
    saved = destination.table.get_item(
        Key={"pk": marker["pk"], "sk": marker["sk"]}, ConsistentRead=True
    ).get("Item")
    if not saved:
        inbox_condition = (
            "entity = :entity AND botId = :bot AND recipient = :recipient "
            "AND sesMessageId = :ses AND rawObjectKey = :key "
            "AND disposition = :disposition"
        )
        inbox_values = {
            ":entity": "BOT_EMAIL", ":bot": imported["botId"],
            ":recipient": imported["recipient"], ":ses": primary["sesMessageId"],
            ":key": primary["key"], ":disposition": imported["delivery"],
        }
        bot_condition = "id = :bot AND emailToken = :token"
        bot_values = {":bot": imported["botId"], ":token": bot["emailToken"]}
        if imported["delivery"] == "automatic":
            inbox_condition += " AND authentication = :verified AND linkedTurnId = :turnId"
            inbox_values.update({":verified": "verified", ":turnId": inbox["linkedTurnId"]})
            bot_condition += " AND emailOwnerAddress = :owner"
            bot_values[":owner"] = bot["emailOwnerAddress"]
            if inbox.get("threadReply") is not True:
                bot_condition += " AND emailInboundMode = :automatic"
                bot_values[":automatic"] = "automatic"
        if isinstance(bot.get("legacyEmailAddress"), str):
            bot_condition += " AND legacyEmailAddress = :recipient"
            bot_values[":recipient"] = imported["recipient"]
        else:
            bot_condition += " AND attribute_not_exists(legacyEmailAddress)"
        conditions = [
            {"ConditionCheck": {
                "TableName": destination.table.name,
                "Key": {"pk": f"USER#{imported['userId']}", "sk": "STATE"},
                "ConditionExpression": (
                    "attribute_not_exists(accountStatus) OR "
                    "(attribute_type(accountStatus, :type) AND "
                    "accountStatus <> :deleting AND accountStatus <> :deleted)"
                ),
                "ExpressionAttributeValues": {":type": "S", ":deleting": "DELETING", ":deleted": "DELETED"},
            }},
            {"ConditionCheck": {
                "TableName": destination.table.name,
                "Key": {"pk": f"USER#{imported['userId']}", "sk": imported["inboxKey"]},
                "ConditionExpression": inbox_condition,
                "ExpressionAttributeValues": inbox_values,
            }},
            {"ConditionCheck": {
                "TableName": destination.table.name,
                "Key": {"pk": f"USER#{imported['userId']}", "sk": f"BOT#{imported['botId']}"},
                "ConditionExpression": bot_condition,
                "ExpressionAttributeValues": bot_values,
            }},
        ]
        if isinstance(bot.get("legacyEmailAddress"), str):
            conditions.append({"ConditionCheck": {
                "TableName": destination.table.name,
                "Key": mail_alias_key(imported["recipient"]),
                "ConditionExpression": (
                    "entity = :entity AND targetUserId = :user AND "
                    "targetBotId = :bot AND address = :address"
                ),
                "ExpressionAttributeValues": {
                    ":entity": "MAIL_ALIAS", ":user": imported["userId"],
                    ":bot": imported["botId"], ":address": imported["recipient"],
                },
            }})
        for item in (marker, outbox):
            if item:
                conditions.append({"Put": {
                    "TableName": destination.table.name, "Item": item,
                    "ConditionExpression": "attribute_not_exists(pk)",
                }})
        try:
            destination.table.meta.client.transact_write_items(
                ClientRequestToken=hashlib.sha256(marker["evidenceDigest"].encode()).hexdigest()[:32],
                TransactItems=deepcopy(conditions),
            )
        except (BotoCoreError, ClientError):
            verify_import(snapshot, imported, accounts)
    verify_import(snapshot, imported, accounts)
    return {"canonicalId": imported["canonicalId"], "automaticPending": outbox is not None}
