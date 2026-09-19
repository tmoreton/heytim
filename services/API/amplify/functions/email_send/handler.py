from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
from datetime import UTC, datetime
from email.headerregistry import Address
from email.message import EmailMessage

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from shared.bot_inbox import mail_address
from shared.keys import bot_key, turn_pk, user_state_key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
ses = boto3.client(
    "sesv2",
    config=Config(
        retries={"total_max_attempts": 3, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=15,
    ),
)
MAIL_QUEUE_ARN = os.environ["MAIL_QUEUE_ARN"]
PUBLIC_WEB_BASE_URL = os.environ.get("PUBLIC_WEB_BASE_URL", "https://heytim.ai")
DELIVERY_TTL_SECONDS = 14 * 24 * 60 * 60
MAX_EMAIL_ANSWER_CHARS = 100_000


def _clean_header(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\r\n\x00]+", " ", value).strip()[:maximum]


def _delivery_key(request: dict) -> dict[str, str]:
    identity = ":".join(
        str(request.get(field, "")) for field in ("userId", "botId", "turnId", "event")
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return {"pk": f"EMAIL_DELIVERY#{digest}", "sk": "DELIVERY"}


def _account_is_active(user_id: str) -> bool:
    state = table.get_item(Key=user_state_key(user_id), ConsistentRead=True).get("Item")
    return not state or state.get("accountStatus") not in {"DELETING", "DELETED"}


def _claim_delivery(request: dict) -> dict[str, str] | None:
    key = _delivery_key(request)
    now = int(datetime.now(UTC).timestamp())
    try:
        table.put_item(
            Item={
                **key,
                "entity": "BOT_EMAIL_DELIVERY",
                "status": "CLAIMED",
                "userId": request["userId"],
                "botId": request["botId"],
                "turnId": request["turnId"],
                "event": request.get("event", "reply"),
                "claimedAt": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "expiresAt": now + DELIVERY_TTL_SECONDS,
            },
            ConditionExpression=Attr("pk").not_exists(),
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None
    return key


def _finish_delivery(key: dict, status: str, **values: str) -> None:
    names = {"#status": "status"}
    expression_values: dict[str, object] = {
        ":status": status,
        ":completed": datetime.now(UTC).isoformat(timespec="milliseconds"),
    }
    update = "SET #status = :status, completedAt = :completed"
    for field, value in values.items():
        placeholder = f":{field}"
        update += f", {field} = {placeholder}"
        expression_values[placeholder] = value
    table.update_item(
        Key=key,
        UpdateExpression=update,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=expression_values,
    )


def _eligible(bot: dict, turn: dict) -> bool:
    mode = bot.get("emailDeliveryMode", "appOnly")
    return mode == "allResponses" or (
        mode == "emailReplies" and turn.get("source") == "email"
    )


def _thread_header(value: object) -> str | None:
    clean = _clean_header(value, 640)
    if not clean or "<" not in clean or ">" not in clean:
        return None
    return clean


def _message(bot: dict, turn: dict, route: str, event: str) -> EmailMessage:
    bot_name = _clean_header(bot.get("name"), 80) or "Your bot"
    original_subject = _clean_header(turn.get("emailSubject"), 180)
    if event == "approval":
        subject = f"Action needed: {bot_name} is waiting for approval"
        answer = (
            f"{bot_name} needs your approval before continuing. "
            "Open Hey Tim to review the exact action. Email replies cannot approve actions."
        )
    else:
        subject = (
            original_subject
            if original_subject.lower().startswith("re:")
            else f"Re: {original_subject}"
            if original_subject
            else f"{bot_name} replied"
        )
        answer = str(turn.get("assistantText", "")).strip()
    answer = answer[:MAX_EMAIL_ANSWER_CHARS]
    footer = "Open Hey Tim to see the complete conversation and approve any actions."
    message = EmailMessage()
    message["From"] = Address(display_name=f"{bot_name} via Hey Tim", addr_spec=route)
    message["To"] = bot["emailOwnerAddress"]
    message["Reply-To"] = route
    message["Subject"] = subject
    message["Auto-Submitted"] = "auto-generated"
    message["X-Auto-Response-Suppress"] = "All"
    in_reply_to = _thread_header(turn.get("emailMessageIdHeader"))
    references = _thread_header(turn.get("emailReferences"))
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references or in_reply_to:
        message["References"] = " ".join(
            value for value in (references, in_reply_to) if value
        )
    message.set_content(f"{answer}\n\n---\n{footer}\n{PUBLIC_WEB_BASE_URL}")
    message.add_alternative(
        (
            '<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;'
            'line-height:1.55;color:#171714">'
            f'<div style="white-space:pre-wrap">{html.escape(answer)}</div>'
            '<hr style="border:0;border-top:1px solid #e7e3da;margin:24px 0">'
            f'<p style="color:#77736b">{html.escape(footer)} '
            f'<a href="{html.escape(PUBLIC_WEB_BASE_URL, quote=True)}">Open Hey Tim</a>.</p>'
            "</div>"
        ),
        subtype="html",
    )
    return message


def _process(request: dict) -> None:
    user_id = request.get("userId")
    bot_id = request.get("botId")
    turn_id = request.get("turnId")
    turn_key = request.get("turnKey")
    event = request.get("event", "reply")
    if not all(
        isinstance(value, str) and value
        for value in (user_id, bot_id, turn_id, turn_key)
    ):
        raise ValueError("Email delivery request is incomplete")
    if event not in {"reply", "approval"} or not turn_key.startswith("TURN#"):
        raise ValueError("Email delivery request is invalid")
    if not _account_is_active(user_id):
        return
    bot = table.get_item(Key=bot_key(user_id, bot_id), ConsistentRead=True).get("Item")
    turn = table.get_item(
        Key={"pk": turn_pk(user_id, bot_id), "sk": turn_key}, ConsistentRead=True
    ).get("Item")
    if not bot or not turn or turn.get("id") != turn_id or not _eligible(bot, turn):
        return
    owner = bot.get("emailOwnerAddress")
    token = bot.get("emailToken")
    if (
        not isinstance(owner, str)
        or owner.count("@") != 1
        or any(character in owner for character in "\r\n\x00")
        or not isinstance(token, str)
        or not re.fullmatch(r"[a-z2-7]{16}", token)
    ):
        return
    if event == "reply" and turn.get("status") not in {"COMPLETE", "ERROR"}:
        return
    if event == "approval" and turn.get("status") != "AWAITING_APPROVAL":
        return
    delivery_key = _claim_delivery(request)
    if delivery_key is None:
        return
    try:
        route = mail_address(user_id, bot_id, token)
        message = _message(bot, turn, route, event)
        response = ses.send_email(
            FromEmailAddress=route,
            Destination={"ToAddresses": [owner]},
            ReplyToAddresses=[route],
            Content={"Raw": {"Data": message.as_bytes()}},
        )
        provider_id = response.get("MessageId")
        if not isinstance(provider_id, str) or not provider_id:
            raise TypeError("SES did not return a message ID")
    except ClientError:
        table.delete_item(Key=delivery_key)
        raise
    except BotoCoreError:
        logger.warning("SES delivery outcome is unknown", exc_info=True)
        _finish_delivery(delivery_key, "UNKNOWN")
        return
    except Exception:
        table.delete_item(Key=delivery_key)
        raise
    _finish_delivery(delivery_key, "SENT", providerMessageId=provider_id)
    try:
        table.update_item(
            Key={"pk": turn_pk(user_id, bot_id), "sk": turn_key},
            UpdateExpression=(
                "SET emailDeliveryStatus = :status, emailOutboundMessageId = :messageId"
            ),
            ConditionExpression="attribute_exists(pk) AND #id = :turnId",
            ExpressionAttributeNames={"#id": "id"},
            ExpressionAttributeValues={
                ":status": "sent",
                ":messageId": provider_id,
                ":turnId": turn_id,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def handler(event: dict, _context: object) -> dict:
    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            if (
                record.get("eventSource") != "aws:sqs"
                or record.get("eventSourceARN") != MAIL_QUEUE_ARN
            ):
                raise ValueError("Unexpected email delivery event source")
            _process(json.loads(record["body"]))
        except Exception:
            logger.exception("Bot email delivery failed")
            if isinstance(message_id, str) and message_id:
                failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
