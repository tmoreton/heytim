from __future__ import annotations

import base64
import binascii
import os

from shared.bot_inbox import mail_address, new_mail_token

from .bots import _get_bot
from .support import (
    ApiError,
    _bot_sk,
    _decode_page_cursor,
    _encode_page_cursor,
    _user_pk,
    table,
)

INBOX_AVAILABLE = os.environ.get("BOT_EMAIL_AVAILABLE") == "true"
INCOMING_MODES = {"review", "automatic"}
RESPONSE_MODES = {"appOnly", "emailReplies", "allResponses"}
PUBLIC_REVIEW_REASONS = {"settings_changed", "bot_busy", "browser_active"}


def _inbox_prefix(bot_id: str) -> str:
    return f"INBOX#{bot_id}#"


def _inbox_state(user_id: str, bot: dict) -> dict:
    token = bot.get("emailToken")
    return {
        "available": INBOX_AVAILABLE,
        "enabled": isinstance(token, str) and bool(token),
        "address": mail_address(user_id, bot["id"], token) if token else None,
        "incomingMode": bot.get("emailInboundMode", "review"),
        "responseMode": bot.get("emailDeliveryMode", "appOnly"),
        "allowedSender": bot.get("emailOwnerAddress"),
    }


def list_bot_inbox(user_id: str, bot_id: str, cursor: object = None) -> dict:
    bot = _get_bot(user_id, bot_id)
    partition_key = _user_pk(user_id)
    prefix = _inbox_prefix(bot_id)
    request = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {":pk": partition_key, ":prefix": prefix},
        "ScanIndexForward": False,
        "Limit": 20,
        "ConsistentRead": True,
    }
    start_key = _decode_page_cursor(cursor, partition_key, prefix)
    if start_key:
        request["ExclusiveStartKey"] = start_key
    result = table.query(**request)
    messages = []
    for item in result.get("Items", []):
        messages.append({
            "id": base64.urlsafe_b64encode(item["sk"].encode("utf-8")).decode("ascii").rstrip("="),
            "from": item.get("from", "Unknown sender"),
            "subject": item.get("subject", "(No subject)"),
            "body": item.get("body", ""),
            "receivedAt": item["receivedAt"],
            "attachmentNames": item.get("attachmentNames", []),
            "authentication": item.get("authentication", "unknown"),
            "disposition": item.get("disposition", "review"),
            **(
                {"reviewReason": item["reviewReason"]}
                if item.get("reviewReason") in PUBLIC_REVIEW_REASONS
                else {}
            ),
            **(
                {"linkedTurnId": item["linkedTurnId"]}
                if isinstance(item.get("linkedTurnId"), str)
                else {}
            ),
        })
    return {
        **_inbox_state(user_id, bot),
        "messages": messages,
        **({"nextToken": _encode_page_cursor(result.get("LastEvaluatedKey"))}
           if result.get("LastEvaluatedKey") else {}),
    }


def enable_bot_inbox(
    user_id: str, bot_id: str, verified_email: str | None = None
) -> dict:
    if not INBOX_AVAILABLE:
        raise ApiError(503, "Bot email is not available yet")
    if not verified_email:
        raise ApiError(409, "Verify your account email before turning on bot email")
    bot = _get_bot(user_id, bot_id)
    if not bot.get("emailToken"):
        try:
            result = table.update_item(
                Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
                UpdateExpression=(
                    "SET emailToken = if_not_exists(emailToken, :token), "
                    "emailInboundMode = if_not_exists(emailInboundMode, :incoming), "
                    "emailDeliveryMode = if_not_exists(emailDeliveryMode, :response), "
                    "emailOwnerAddress = :email"
                ),
                ConditionExpression="attribute_exists(pk) AND attribute_not_exists(emailInboxClosing)",
                ExpressionAttributeValues={
                    ":token": new_mail_token(),
                    ":incoming": "review",
                    ":response": "appOnly",
                    ":email": verified_email,
                },
                ReturnValues="ALL_NEW",
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise ApiError(409, "This bot is being deleted") from exc
        bot = result["Attributes"]
    elif bot.get("emailOwnerAddress") != verified_email:
        result = table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
            UpdateExpression="SET emailOwnerAddress = :email",
            ConditionExpression="attribute_exists(pk) AND attribute_exists(emailToken)",
            ExpressionAttributeValues={":email": verified_email},
            ReturnValues="ALL_NEW",
        )
        bot = result["Attributes"]
    return _inbox_state(user_id, bot)


def update_bot_email_preferences(
    user_id: str,
    bot_id: str,
    value: dict,
    verified_email: str | None,
) -> dict:
    if not INBOX_AVAILABLE:
        raise ApiError(503, "Bot email is not available yet")
    incoming_mode = value.get("incomingMode")
    response_mode = value.get("responseMode")
    if incoming_mode not in INCOMING_MODES:
        raise ApiError(400, "incomingMode must be review or automatic")
    if response_mode not in RESPONSE_MODES:
        raise ApiError(
            400, "responseMode must be appOnly, emailReplies, or allResponses"
        )
    if not verified_email:
        raise ApiError(409, "Verify your account email before using bot email")
    _get_bot(user_id, bot_id)
    try:
        result = table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
            UpdateExpression=(
                "SET emailInboundMode = :incoming, emailDeliveryMode = :response, "
                "emailOwnerAddress = :email"
            ),
            ConditionExpression=(
                "attribute_exists(pk) AND attribute_exists(emailToken) "
                "AND attribute_not_exists(emailInboxClosing)"
            ),
            ExpressionAttributeValues={
                ":incoming": incoming_mode,
                ":response": response_mode,
                ":email": verified_email,
            },
            ReturnValues="ALL_NEW",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(409, "Turn on this inbox before changing email preferences") from exc
    return _inbox_state(user_id, result["Attributes"])


def disable_bot_inbox(user_id: str, bot_id: str) -> dict:
    _get_bot(user_id, bot_id)
    try:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
            UpdateExpression=(
                "REMOVE emailToken, emailInboundMode, emailDeliveryMode, "
                "emailOwnerAddress"
            ),
            ConditionExpression="attribute_exists(pk)",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(404, "Bot not found") from exc
    return {
        "available": INBOX_AVAILABLE,
        "enabled": False,
        "address": None,
        "incomingMode": "review",
        "responseMode": "appOnly",
        "allowedSender": None,
    }


def rotate_bot_inbox(user_id: str, bot_id: str) -> dict:
    if not INBOX_AVAILABLE:
        raise ApiError(503, "Bot email is not available yet")
    _get_bot(user_id, bot_id)
    try:
        result = table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
            UpdateExpression="SET emailToken = :token",
            ConditionExpression=(
                "attribute_exists(pk) AND attribute_exists(emailToken) "
                "AND attribute_not_exists(emailInboxClosing)"
            ),
            ExpressionAttributeValues={":token": new_mail_token()},
            ReturnValues="ALL_NEW",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(409, "Turn on this inbox before replacing its address") from exc
    return _inbox_state(user_id, result["Attributes"])


def delete_inbox_message(user_id: str, bot_id: str, message_id: str) -> dict:
    _get_bot(user_id, bot_id)
    raw = _decode_inbox_message_key(bot_id, message_id)
    table.delete_item(Key={"pk": _user_pk(user_id), "sk": raw})
    return {"deleted": True}


def inbox_message(user_id: str, bot_id: str, message_id: object) -> dict:
    if not isinstance(message_id, str):
        raise ApiError(400, "Invalid inbox message")
    raw = _decode_inbox_message_key(bot_id, message_id)
    item = table.get_item(
        Key={"pk": _user_pk(user_id), "sk": raw}, ConsistentRead=True
    ).get("Item")
    if not item or item.get("entity") != "BOT_EMAIL" or item.get("botId") != bot_id:
        raise ApiError(404, "Inbox message not found")
    if item.get("linkedTurnId"):
        raise ApiError(409, "This email is already in the bot conversation")
    return item


def _decode_inbox_message_key(bot_id: str, message_id: str) -> str:
    if not isinstance(message_id, str) or len(message_id) > 400:
        raise ApiError(400, "Invalid inbox message")
    try:
        raw = base64.b64decode(
            message_id + "=" * (-len(message_id) % 4), altchars=b"-_", validate=True
        ).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise ApiError(400, "Invalid inbox message") from exc
    if not raw.startswith(_inbox_prefix(bot_id)):
        raise ApiError(404, "Inbox message not found")
    return raw
