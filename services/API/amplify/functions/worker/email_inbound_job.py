from __future__ import annotations

import time

from shared.account_state import (
    AccountInactiveError,
    UserItemConflictError,
    UserItemGuardFailedError,
    put_user_item_while_account_active,
)
from shared.bot_inbox import mail_address
from shared.browser_session_store import BrowserSessionError
from shared.browser_sessions import ensure_browser_send_allowed
from shared.job_envelope import send_job
from shared.work_state import is_in_flight

from .support import QUEUE_URL, _bot_key, _turn_pk, sqs, table

SEND_LEASE_SECONDS = 60
MAX_WAIT_ATTEMPTS = 20


def _request_string(request: dict, field: str, maximum: int = 400) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"Email inbound request has an invalid {field}")
    return value


def _mark_for_review(user_id: str, inbox_key: str, reason: str) -> None:
    try:
        table.update_item(
            Key={"pk": f"USER#{user_id}", "sk": inbox_key},
            UpdateExpression=(
                "SET disposition = :review, reviewReason = :reason REMOVE linkedTurnId"
            ),
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={":review": "review", ":reason": reason},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def _requeue(request: dict) -> None:
    attempt = int(request.get("waitAttempt", 0))
    if attempt >= MAX_WAIT_ATTEMPTS:
        _mark_for_review(request["userId"], request["inboxKey"], "bot_busy")
        return
    send_job(
        sqs,
        QUEUE_URL,
        {**request, "waitAttempt": attempt + 1},
        delay_seconds=15,
    )


def _claim_send_lease(user_id: str, bot_id: str, owner: str) -> bool:
    now = int(time.time())
    try:
        table.update_item(
            Key=_bot_key(user_id, bot_id),
            UpdateExpression="SET sendLeaseOwner = :owner, sendLeaseExpiresAt = :expires",
            ConditionExpression=(
                "attribute_exists(pk) AND (attribute_not_exists(sendLeaseExpiresAt) "
                "OR sendLeaseExpiresAt < :now)"
            ),
            ExpressionAttributeValues={
                ":owner": owner,
                ":now": now,
                ":expires": now + SEND_LEASE_SECONDS,
            },
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def _release_send_lease(user_id: str, bot_id: str, owner: str) -> None:
    try:
        table.update_item(
            Key=_bot_key(user_id, bot_id),
            UpdateExpression="REMOVE sendLeaseOwner, sendLeaseExpiresAt",
            ConditionExpression="sendLeaseOwner = :owner",
            ExpressionAttributeValues={":owner": owner},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def _active_turn_exists(user_id: str, bot_id: str, ignored_turn_id: str) -> bool:
    response = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": _turn_pk(user_id, bot_id),
            ":prefix": "TURN#",
        },
        ConsistentRead=True,
    )
    return any(
        item.get("id") != ignored_turn_id and is_in_flight(item.get("status"))
        for item in response.get("Items", [])
    )


def _process_email_inbound(record: dict, request: dict) -> None:
    user_id = _request_string(request, "userId", 255)
    bot_id = _request_string(request, "botId")
    inbox_key = _request_string(request, "inboxKey", 900)
    turn_id = _request_string(request, "turnId", 64)
    if not inbox_key.startswith(f"INBOX#{bot_id}#"):
        raise ValueError("Email inbound request is not scoped to its bot")
    inbox = table.get_item(
        Key={"pk": f"USER#{user_id}", "sk": inbox_key}, ConsistentRead=True
    ).get("Item")
    bot = table.get_item(Key=_bot_key(user_id, bot_id), ConsistentRead=True).get("Item")
    if not inbox or not bot:
        return
    sender = inbox.get("from")
    owner = bot.get("emailOwnerAddress")
    token = bot.get("emailToken")
    try:
        current_address = mail_address(user_id, bot_id, token)
    except (TypeError, ValueError):
        current_address = ""
    thread_reply = inbox.get("threadReply") is True
    if not (
        inbox.get("entity") == "BOT_EMAIL"
        and inbox.get("botId") == bot_id
        and inbox.get("disposition") == "automatic"
        and inbox.get("linkedTurnId") == turn_id
        and inbox.get("authentication") == "verified"
        and (bot.get("emailInboundMode") == "automatic" or thread_reply)
        and isinstance(sender, str)
        and isinstance(owner, str)
        and sender.strip().lower() == owner.strip().lower()
        and inbox.get("recipient") == current_address
    ):
        _mark_for_review(user_id, inbox_key, "settings_changed")
        return
    owner_id = record.get("messageId")
    if not isinstance(owner_id, str) or not owner_id or len(owner_id) > 128:
        raise ValueError("Email inbound queue message has no valid messageId")
    if not _claim_send_lease(user_id, bot_id, owner_id):
        _requeue(request)
        return
    try:
        try:
            ensure_browser_send_allowed(table, user_id, bot_id)
        except BrowserSessionError:
            _mark_for_review(user_id, inbox_key, "browser_active")
            return
        if _active_turn_exists(user_id, bot_id, turn_id):
            _requeue(request)
            return
        received_at = _request_string(inbox, "receivedAt", 64)
        subject = _request_string(inbox, "subject", 240)
        body = inbox.get("conversationBody", inbox.get("body", ""))
        if not isinstance(body, str) or not body.strip():
            body = "(No readable text body)"
        attachments = inbox.get("attachmentNames", [])
        attachment_note = (
            "\n\nAttachments were present but were not included: "
            + ", ".join(name for name in attachments if isinstance(name, str))
            if isinstance(attachments, list) and attachments
            else ""
        )
        text = f"Email subject: {subject}\n\n{body}{attachment_note}"
        turn = {
            "pk": _turn_pk(user_id, bot_id),
            "sk": f"TURN#{received_at}#{turn_id}",
            "entity": "TURN",
            "id": turn_id,
            "botId": bot_id,
            "userId": user_id,
            "userText": text,
            "createdAt": received_at,
            "status": "PENDING",
            "source": "email",
            "emailSender": sender,
            "emailRecipient": inbox["recipient"],
            "emailSubject": subject,
            "emailSesMessageId": inbox.get("sesMessageId", ""),
            "emailMessageIdHeader": inbox.get("messageIdHeader", ""),
            "emailInReplyTo": inbox.get("inReplyTo", ""),
            "emailReferences": inbox.get("references", ""),
        }
        try:
            bot_guard = "emailToken = :expectedEmailToken AND emailOwnerAddress = :owner"
            bot_guard_values = {
                ":expectedEmailToken": token,
                ":owner": owner,
            }
            if not thread_reply:
                bot_guard += " AND emailInboundMode = :automatic"
                bot_guard_values[":automatic"] = "automatic"
            put_user_item_while_account_active(
                table,
                user_id,
                turn,
                require_absent=True,
                required_item_condition={
                    "Key": _bot_key(user_id, bot_id),
                    "ConditionExpression": bot_guard,
                    "ExpressionAttributeValues": bot_guard_values,
                },
            )
        except UserItemConflictError:
            existing = table.get_item(
                Key={"pk": turn["pk"], "sk": turn["sk"]}, ConsistentRead=True
            ).get("Item")
            if not existing or existing.get("emailSesMessageId") != inbox.get(
                "sesMessageId"
            ):
                return
        except AccountInactiveError:
            return
        except UserItemGuardFailedError:
            _mark_for_review(user_id, inbox_key, "settings_changed")
            return
        try:
            table.update_item(
                Key=_bot_key(user_id, bot_id),
                UpdateExpression=(
                    "SET lastMessage = :message, lastMessageAt = :now, updatedAt = :now"
                ),
                ConditionExpression=(
                    "attribute_exists(pk) AND emailToken = :expectedEmailToken"
                ),
                ExpressionAttributeValues={
                    ":message": text[:280],
                    ":now": received_at,
                    ":expectedEmailToken": token,
                },
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            return
        send_job(
            sqs,
            QUEUE_URL,
            {
                "type": "AGENT_REPLY",
                "userId": user_id,
                "botId": bot_id,
                "turnKey": turn["sk"],
            },
        )
        try:
            table.update_item(
                Key={"pk": f"USER#{user_id}", "sk": inbox_key},
                UpdateExpression="SET turnQueuedAt = :now",
                ConditionExpression="attribute_exists(pk)",
                ExpressionAttributeValues={":now": received_at},
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            pass
    finally:
        _release_send_lease(user_id, bot_id, owner_id)
