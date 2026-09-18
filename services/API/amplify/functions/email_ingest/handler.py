from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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
MAIL_BUCKET_NAME = os.environ["MAIL_BUCKET_NAME"]
MAIL_TOPIC_ARN = os.environ["MAIL_TOPIC_ARN"]
MAX_PREVIEW_BYTES = 10 * 1024 * 1024
MAX_BODY_CHARS = 7_000


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
    }


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
        except (AccountInactiveError, UserItemConflictError, UserItemGuardFailedError):
            continue


def handler(event: dict, _context: object) -> dict:
    if os.environ.get("MAIL_PROCESSING_ENABLED") != "true":
        return {"processed": False}
    for record in event.get("Records", []):
        sns_record = record.get("Sns") or {}
        if record.get("EventSource") != "aws:sns" or sns_record.get("TopicArn") != MAIL_TOPIC_ARN:
            raise ValueError("Unexpected email event source")
        _process_notification(json.loads(sns_record["Message"]))
    return {"processed": True}
