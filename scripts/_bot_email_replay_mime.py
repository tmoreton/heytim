"""Bounded MIME preview for a reviewed, replayed inbound bot email."""

from __future__ import annotations

import re
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser

MAX_MIME_BYTES = 64 * 1024 * 1024
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


def _clean(value: str, limit: int) -> str:
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return re.sub(r"[ \t]+", " ", value).strip()[:limit]


def _header(value: str | None, limit: int) -> str:
    if not value:
        return ""
    try:
        value = str(make_header(decode_header(value)))
    except (UnicodeError, ValueError):
        pass
    return _clean(value.replace("\r", " ").replace("\n", " "), limit)


def preview(raw: bytes) -> dict:
    message = BytesParser(policy=policy.default).parsebytes(raw[:MAX_PREVIEW_BYTES + 1])
    sender_header = _header(str(message.get("From", "")), 320)
    sender = parseaddr(sender_header)[1] or sender_header
    result = {
        "from": _clean(sender, 320),
        "subject": _header(str(message.get("Subject", "")), 240) or "(No subject)",
        "body": "This email is too large to preview in HeyTim.",
        "attachmentNames": [],
        "messageIdHeader": _header(str(message.get("Message-ID", "")), 320),
        "inReplyTo": _header(str(message.get("In-Reply-To", "")), 320),
        "references": _header(str(message.get("References", "")), 640),
        "autoSubmitted": _header(str(message.get("Auto-Submitted", "")), 80),
    }
    if len(raw) > MAX_PREVIEW_BYTES:
        return result
    text_part: str | None = None
    html_part: str | None = None
    attachments: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if filename or part.get_content_disposition() == "attachment":
            if filename and len(attachments) < 8:
                attachments.append(_header(filename, 120))
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except (UnicodeError, ValueError, LookupError):
            continue
        if not isinstance(content, str):
            continue
        if part.get_content_type() == "text/plain" and text_part is None:
            text_part = content
        elif part.get_content_type() == "text/html" and html_part is None:
            html_part = content
    if text_part is None and html_part is not None:
        parser = _TextFromHtml()
        parser.feed(html_part)
        text_part = parser.text()
    result["body"] = _clean(text_part or "(No readable text body)", MAX_BODY_CHARS)
    result["attachmentNames"] = attachments
    return result


def reply_body(value: str) -> str:
    kept: list[str] = []
    for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if re.match(r"^On .+ wrote:$", stripped, re.IGNORECASE):
            break
        if stripped.lower() in {"-----original message-----", "________________________________"}:
            break
        kept.append(line)
    while kept and (not kept[-1].strip() or kept[-1].lstrip().startswith(">")):
        kept.pop()
    return _clean("\n".join(kept), MAX_BODY_CHARS) or value
