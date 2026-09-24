from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser

import boto3
from shared.account_state import (
    AccountInactiveError,
    UserItemConflictError,
    UserItemGuardFailedError,
    put_user_item_while_account_active,
)
from shared.bot_inbox import resolve_mail_address
from shared.keys import user_pk

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
s3 = boto3.client("s3")
sqs = boto3.client("sqs")
MAIL_BUCKET_NAME = os.environ["MAIL_BUCKET_NAME"]
MAIL_TOPIC_ARN = os.environ["MAIL_TOPIC_ARN"]
JOB_QUEUE_URL = os.environ.get("JOB_QUEUE_URL", "")
MAX_PREVIEW_BYTES = 10 * 1024 * 1024
MAX_BODY_CHARS = 7_000
MAX_THREAD_LOOKUP_TURNS = 500


class _TextFromHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip_depth += 1
        elif tag in {"p", "div", "br", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _clean_text(value: str, limit: int) -> str:
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    value = re.sub(r"[ \t]+", " ", value).strip()
    return value[:limit]


def _decoded_header(value: str | None, limit: int) -> str:
    if not value:
        return ""
    try:
        value = str(make_header(decode_header(value)))
    except (UnicodeError, ValueError):
        pass
    return _clean_text(value.replace("\r", " ").replace("\n", " "), limit)


def _preview(raw: bytes, mail: dict) -> dict:
    if len(raw) > MAX_PREVIEW_BYTES:
        return {
            "from": _clean_text(str(mail.get("source", "")), 320),
            "subject": _clean_text(str((mail.get("commonHeaders") or {}).get("subject", "")), 240),
            "body": "This email is too large to preview in HeyTim.",
            "attachmentNames": [],
        }
    message = BytesParser(policy=policy.default).parsebytes(raw)
    sender_header = _decoded_header(str(message.get("From", "")), 320)
    sender = parseaddr(sender_header)[1] or sender_header
    text_part = None
    html_part = None
    attachments: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if filename or part.get_content_disposition() == "attachment":
            if filename and len(attachments) < 8:
                attachments.append(_decoded_header(filename, 120))
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except (UnicodeError, ValueError, LookupError):
            continue
        if not isinstance(content, str):
            continue
        if content_type == "text/plain" and text_part is None:
            text_part = content
        elif content_type == "text/html" and html_part is None:
            html_part = content
    if text_part is None and html_part is not None:
        parser = _TextFromHtml()
        parser.feed(html_part)
        text_part = parser.text()
    return {
        "from": _clean_text(sender, 320),
        "subject": _decoded_header(str(message.get("Subject", "")), 240) or "(No subject)",
        "body": _clean_text(text_part or "(No readable text body)", MAX_BODY_CHARS),
        "attachmentNames": attachments,
        "messageIdHeader": _decoded_header(str(message.get("Message-ID", "")), 320),
        "inReplyTo": _decoded_header(str(message.get("In-Reply-To", "")), 320),
        "references": _decoded_header(str(message.get("References", "")), 640),
        "autoSubmitted": _decoded_header(str(message.get("Auto-Submitted", "")), 80),
    }


def _reply_body(value: str) -> str:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^On .+ wrote:$", stripped, re.IGNORECASE):
            break
        if stripped.lower() in {
            "-----original message-----",
            "________________________________",
        }:
            break
        kept.append(line)
    while kept and (not kept[-1].strip() or kept[-1].lstrip().startswith(">")):
        kept.pop()
    return _clean_text("\n".join(kept), MAX_BODY_CHARS) or value


def _verified_owner_mail(
    bot: dict, preview: dict, mail: dict, authentication: str
) -> bool:
    owner = bot.get("emailOwnerAddress")
    header_sender = preview.get("from")
    envelope_sender = mail.get("source")
    auto_submitted = str(preview.get("autoSubmitted", "")).strip().lower()
    return bool(
        authentication == "verified"
        and isinstance(owner, str)
        and isinstance(header_sender, str)
        and isinstance(envelope_sender, str)
        and hmac.compare_digest(header_sender.strip().lower(), owner.strip().lower())
        and hmac.compare_digest(envelope_sender.strip().lower(), owner.strip().lower())
        and auto_submitted in {"", "no"}
    )


def _message_id_tokens(*values: object) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        for candidate in re.findall(r"<([^<>\s]+)>", value):
            candidate = candidate.strip().lower()
            if not candidate:
                continue
            tokens.add(candidate)
            if "@" in candidate:
                tokens.add(candidate.split("@", 1)[0])
    return tokens


def _existing_email_thread(user_id: str, bot_id: str, preview: dict) -> bool:
    reply_tokens = _message_id_tokens(
        preview.get("inReplyTo"), preview.get("references")
    )
    if not reply_tokens:
        return False
    request = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {
            ":pk": f"CHAT#{user_id}#{bot_id}",
            ":prefix": "TURN#",
        },
        "ProjectionExpression": "emailOutboundMessageId,emailDeliveryStatus",
        "ScanIndexForward": False,
        "Limit": 100,
    }
    checked = 0
    while checked < MAX_THREAD_LOOKUP_TURNS:
        response = table.query(**request)
        items = response.get("Items", [])
        checked += len(items)
        for item in items:
            if item.get("emailDeliveryStatus") != "sent":
                continue
            outbound = item.get("emailOutboundMessageId")
            if not isinstance(outbound, str):
                continue
            candidate = outbound.strip().strip("<>").lower()
            if candidate in reply_tokens or (
                "@" in candidate and candidate.split("@", 1)[0] in reply_tokens
            ):
                return True
        cursor = response.get("LastEvaluatedKey")
        if not cursor or not items:
            return False
        request["ExclusiveStartKey"] = cursor
    return False


def _automatic_delivery(bot: dict, *, trusted_owner: bool, thread_reply: bool) -> bool:
    return bool(
        JOB_QUEUE_URL
        and trusted_owner
        and (bot.get("emailInboundMode") == "automatic" or thread_reply)
    )


def _queue_automatic_turn(
    user_id: str,
    bot: dict,
    inbox_key: str,
    turn_id: str,
) -> None:
    sqs.send_message(
        QueueUrl=JOB_QUEUE_URL,
        MessageBody=json.dumps(
            {
                "type": "EMAIL_INBOUND",
                "userId": user_id,
                "botId": bot["id"],
                "inboxKey": inbox_key,
                "turnId": turn_id,
            }
        ),
    )


def _received_time(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("SES notification has no timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("SES notification timestamp has no timezone")
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _process_notification(notification: dict) -> None:
    if notification.get("notificationType") != "Received":
        return
    receipt = notification.get("receipt") or {}
    mail = notification.get("mail") or {}
    if any(
        receipt.get(f"{kind}Verdict", {}).get("status") != "PASS"
        for kind in ("spam", "virus")
    ):
        logger.info("Rejected email after SES content checks")
        return
    action = receipt.get("action") or {}
    if action.get("type") != "S3" or action.get("bucketName") != MAIL_BUCKET_NAME:
        raise ValueError("Unexpected SES receipt action")
    message_id = mail.get("messageId")
    if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", message_id):
        raise ValueError("Invalid SES message ID")
    received_at = _received_time(mail.get("timestamp"))
    recipients = receipt.get("recipients") or []
    if not isinstance(recipients, list):
        raise TypeError("Invalid SES recipients")
    candidates = []
    for address in {value for value in recipients if isinstance(value, str)}:
        resolved = resolve_mail_address(table, address)
        if resolved:
            candidates.append((address.lower(), *resolved))
    if not candidates:
        return
    key = f"received/{message_id}"
    if action.get("objectKey") not in (None, message_id, key):
        raise ValueError("Unexpected mail object key")
    response = s3.get_object(Bucket=MAIL_BUCKET_NAME, Key=key, Range=f"bytes=0-{MAX_PREVIEW_BYTES}")
    with response["Body"] as stream:
        raw = stream.read(MAX_PREVIEW_BYTES + 1)
    preview = _preview(raw, mail)
    authentication = (
        "verified" if receipt.get("dmarcVerdict", {}).get("status") == "PASS"
        else "unverified"
    )
    for address, user_id, bot in candidates:
        digest = hashlib.sha256(f"{message_id}\0{address}".encode()).hexdigest()[:24]
        trusted_owner = _verified_owner_mail(bot, preview, mail, authentication)
        thread_reply = bool(
            trusted_owner
            and bot.get("emailInboundMode") != "automatic"
            and _existing_email_thread(user_id, bot["id"], preview)
        )
        automatic = _automatic_delivery(
            bot, trusted_owner=trusted_owner, thread_reply=thread_reply
        )
        linked_turn_id = (
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"heytim-email:{message_id}:{address}"))
            if automatic
            else None
        )
        item = {
            "pk": user_pk(user_id),
            "sk": f"INBOX#{bot['id']}#{received_at}#{digest}",
            "entity": "BOT_EMAIL",
            "botId": bot["id"],
            "receivedAt": received_at,
            "recipient": address,
            "sesMessageId": message_id,
            "rawObjectKey": key,
            "authentication": authentication,
            "disposition": "automatic" if automatic else "review",
            **({"linkedTurnId": linked_turn_id} if linked_turn_id else {}),
            **({"threadReply": True} if thread_reply else {}),
            **(
                {"conversationBody": _reply_body(preview["body"])}
                if automatic
                else {}
            ),
            **preview,
        }
        try:
            put_user_item_while_account_active(
                table, user_id, item, require_absent=True,
                required_item_condition={
                    "Key": {"pk": user_pk(user_id), "sk": f"BOT#{bot['id']}"},
                    "ConditionExpression": "emailToken = :expectedEmailToken",
                    "ExpressionAttributeValues": {
                        ":expectedEmailToken": bot["emailToken"]
                    },
                },
            )
        except UserItemConflictError:
            existing = table.get_item(
                Key={"pk": item["pk"], "sk": item["sk"]}, ConsistentRead=True
            ).get("Item")
            if not existing or existing.get("sesMessageId") != message_id:
                continue
        except (AccountInactiveError, UserItemGuardFailedError):
            continue
        if automatic:
            _queue_automatic_turn(user_id, bot, item["sk"], linked_turn_id)


def handler(event: dict, _context: object) -> dict:
    if os.environ.get("MAIL_PROCESSING_ENABLED") != "true":
        return {"processed": False}
    for record in event.get("Records", []):
        sns_record = record.get("Sns") or {}
        if record.get("EventSource") != "aws:sns" or sns_record.get("TopicArn") != MAIL_TOPIC_ARN:
            raise ValueError("Unexpected email event source")
        _process_notification(json.loads(sns_record["Message"]))
    return {"processed": True}
