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


def _inbox_prefix(bot_id: str) -> str:
    return f"INBOX#{bot_id}#"


def _inbox_state(user_id: str, bot: dict) -> dict:
    token = bot.get("emailToken")
    return {
        "available": INBOX_AVAILABLE,
        "enabled": isinstance(token, str) and bool(token),
        "address": mail_address(user_id, bot["id"], token) if token else None,
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
        })
    return {
        **_inbox_state(user_id, bot),
        "messages": messages,
        **({"nextToken": _encode_page_cursor(result.get("LastEvaluatedKey"))}
           if result.get("LastEvaluatedKey") else {}),
    }


def enable_bot_inbox(user_id: str, bot_id: str) -> dict:
    if not INBOX_AVAILABLE:
        raise ApiError(503, "Bot email is not available yet")
    bot = _get_bot(user_id, bot_id)
    if not bot.get("emailToken"):
        try:
            result = table.update_item(
                Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
                UpdateExpression="SET emailToken = if_not_exists(emailToken, :token)",
                ConditionExpression="attribute_exists(pk) AND attribute_not_exists(emailInboxClosing)",
                ExpressionAttributeValues={":token": new_mail_token()},
                ReturnValues="ALL_NEW",
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise ApiError(409, "This bot is being deleted") from exc
        bot = result["Attributes"]
    return _inbox_state(user_id, bot)


def disable_bot_inbox(user_id: str, bot_id: str) -> dict:
    _get_bot(user_id, bot_id)
    try:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
            UpdateExpression="REMOVE emailToken",
            ConditionExpression="attribute_exists(pk)",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(404, "Bot not found") from exc
    return {"available": INBOX_AVAILABLE, "enabled": False, "address": None}


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
    table.delete_item(Key={"pk": _user_pk(user_id), "sk": raw})
    return {"deleted": True}
