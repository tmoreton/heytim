from __future__ import annotations

import base64
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import Any

from strands import tool

from . import artifacts
from .mcp_connections import _bounded_tool_name, _google_access_token

GMAIL_API_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_BODY_CHARS = 50_000
MAX_THREAD_CHARS = 120_000
RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
ALLOWED_NEWSLETTER_TAGS = {
    "html",
    "head",
    "title",
    "body",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "div",
    "p",
    "span",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "a",
    "img",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "small",
    "hr",
}
FORBIDDEN_NEWSLETTER_TAGS = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "video",
    "audio",
    "meta",
    "link",
}
CID_PATTERN = re.compile(
    r"^cid:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif tag in {"br", "div", "p", "li", "tr"} and not self.hidden_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif tag in {"div", "p", "li", "tr"} and not self.hidden_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


class _NewsletterHTMLValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in FORBIDDEN_NEWSLETTER_TAGS:
            raise ValueError(
                f"htmlBody contains unsupported <{normalized_tag}> content"
            )
        if normalized_tag not in ALLOWED_NEWSLETTER_TAGS:
            raise ValueError(
                f"htmlBody contains unsupported <{normalized_tag}> content"
            )
        for raw_name, raw_value in attrs:
            name = raw_name.casefold()
            value = (raw_value or "").strip()
            lowered = value.casefold()
            if name.startswith("on"):
                raise ValueError("htmlBody contains event-handler attributes")
            if name in {"srcset", "background", "poster", "action", "formaction"}:
                raise ValueError("htmlBody contains external-resource attributes")
            if name == "style" and any(
                marker in lowered for marker in ("url(", "expression(", "javascript:")
            ):
                raise ValueError("htmlBody contains unsafe CSS")
            if name == "href" and value:
                if normalized_tag != "a":
                    raise ValueError("htmlBody links are only allowed on anchors")
                parsed = urllib.parse.urlsplit(value)
                if parsed.scheme not in {"https", "mailto"}:
                    raise ValueError("htmlBody links must use HTTPS or mailto")
            if name == "src":
                if normalized_tag != "img":
                    raise ValueError(
                        "htmlBody contains an unsupported source attribute"
                    )
                match = CID_PATTERN.fullmatch(lowered)
                if not match:
                    raise ValueError("htmlBody images must use cid:<artifactId>")
                self.image_ids.append(match.group(1))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _newsletter_image_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if (
        not isinstance(value, list)
        or len(value) > 10
        or any(not isinstance(item, str) for item in value)
    ):
        raise ValueError("inlineImageIds must be a list of at most 10 artifact IDs")
    if len(set(value)) != len(value):
        raise ValueError("inlineImageIds must not contain duplicates")
    return value


def _validated_newsletter_html(value: Any, image_ids: list[str]) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200_000:
        raise ValueError("htmlBody is invalid")
    parser = _NewsletterHTMLValidator()
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, AssertionError) as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("htmlBody is invalid") from exc
    if parser.image_ids != image_ids:
        raise ValueError(
            "Every inlineImageId must appear exactly once in htmlBody as cid:<artifactId>"
        )
    return value.strip()


def _html_to_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    return "\n".join(
        line.strip()
        for line in html.unescape("".join(parser.parts)).splitlines()
        if line.strip()
    )


def _resource_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not RESOURCE_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    return value


def _bounded_text(value: str, field: str, maximum: int, *, required: bool) -> str:
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        raise ValueError(f"{field} is invalid")
    normalized = value.strip()
    if (required and not normalized) or len(normalized) > maximum:
        raise ValueError(f"{field} is invalid")
    return normalized


def _page_size(value: int, maximum: int = 50) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= maximum
    ):
        raise ValueError(f"pageSize must be between 1 and {maximum}")
    return value


def _api_json(
    access_token: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict:
    url = f"{GMAIL_API_URL}/{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    data = None
    method = "GET"
    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {access_token}",
        "user-agent": "HeyTim/1.0",
    }
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        headers["content-type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(  # nosec B310 - the Gmail API host is fixed.
            request, timeout=20
        ) as response:
            value = json.loads(response.read(2_000_001).decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("Gmail data is unavailable") from exc
    if not isinstance(value, dict):
        raise TypeError("Gmail returned an invalid response")
    return value


def _headers(payload: dict) -> dict[str, str]:
    values = payload.get("headers", [])
    return {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in values
        if isinstance(item, dict) and item.get("name")
    }


def _decode_data(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _body_parts(payload: dict) -> tuple[list[str], list[str]]:
    plain: list[str] = []
    rich: list[str] = []

    def visit(part: dict) -> None:
        mime_type = str(part.get("mimeType", "")).lower()
        body = part.get("body")
        content = _decode_data(body.get("data")) if isinstance(body, dict) else ""
        if content and mime_type == "text/plain":
            plain.append(content)
        elif content and mime_type == "text/html":
            rich.append(_html_to_text(content))
        children = part.get("parts")
        for child in children if isinstance(children, list) else []:
            if isinstance(child, dict):
                visit(child)

    visit(payload)
    return plain, rich


def _message(value: dict, *, include_body: bool) -> dict:
    payload = value.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    headers = _headers(payload)
    result = {
        "id": value.get("id"),
        "threadId": value.get("threadId"),
        "subject": headers.get("subject"),
        "sender": headers.get("from"),
        "toRecipients": headers.get("to"),
        "ccRecipients": headers.get("cc"),
        "date": headers.get("date"),
        "snippet": value.get("snippet"),
        "labelIds": value.get("labelIds", []),
    }
    if include_body:
        plain, rich = _body_parts(payload)
        body = "\n\n".join(item.strip() for item in (plain or rich) if item.strip())
        result["plaintextBody"] = body[:MAX_BODY_CHARS]
        result["bodyTruncated"] = len(body) > MAX_BODY_CHARS
    return result


def _thread(value: dict, *, include_body: bool) -> dict:
    messages = value.get("messages")
    messages = messages if isinstance(messages, list) else []
    result = {
        "id": value.get("id"),
        "historyId": value.get("historyId"),
        "messages": [
            _message(item, include_body=include_body)
            for item in messages
            if isinstance(item, dict)
        ],
    }
    encoded = json.dumps(result, separators=(",", ":"))
    if len(encoded) <= MAX_THREAD_CHARS:
        return result
    for message in result["messages"]:
        if isinstance(message, dict) and isinstance(message.get("plaintextBody"), str):
            message["plaintextBody"] = message["plaintextBody"][:10_000]
            message["bodyTruncated"] = True
    result["threadTruncated"] = True
    return result


def gmail_api_tools(
    binding: dict, artifact_prefix: str | None = None, *, storage_client=None
) -> list[Any]:
    """Expose the reviewed Gmail surface through the generally available REST API."""

    name = lambda remote: _bounded_tool_name(binding["id"], remote)

    @tool(name=name("search_threads"))
    def search_threads(
        query: str = "",
        pageSize: int = 20,
        pageToken: str = "",
        includeTrash: bool = False,
    ) -> str:
        """Search email threads using Gmail search syntax and return message metadata."""
        count = _page_size(pageSize)
        if not isinstance(query, str) or len(query) > 1_000:
            raise ValueError("query is invalid")
        if not isinstance(pageToken, str) or len(pageToken) > 2_000:
            raise ValueError("pageToken is invalid")
        access_token = _google_access_token(binding)
        listing = _api_json(
            access_token,
            "threads",
            query={
                "q": query.strip(),
                "maxResults": count,
                "pageToken": pageToken,
                "includeSpamTrash": str(bool(includeTrash)).lower(),
            },
        )
        threads = []
        for item in listing.get("threads", []):
            thread_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(thread_id, str):
                continue
            detail = _api_json(
                access_token,
                f"threads/{urllib.parse.quote(thread_id, safe='')}",
                query={
                    "format": "metadata",
                    "metadataHeaders": ["Subject", "From", "To", "Cc", "Date"],
                },
            )
            threads.append(_thread(detail, include_body=False))
        return json.dumps(
            {
                "threads": threads,
                "nextPageToken": listing.get("nextPageToken"),
                "resultCountEstimate": listing.get("resultSizeEstimate", 0),
            },
            separators=(",", ":"),
        )

    @tool(name=name("get_thread"))
    def get_thread(threadId: str) -> str:
        """Read the messages and plain-text content in one Gmail thread by thread ID."""
        resource_id = _resource_id(threadId, "threadId")
        value = _api_json(
            _google_access_token(binding),
            f"threads/{urllib.parse.quote(resource_id, safe='')}",
            query={"format": "full"},
        )
        return json.dumps(_thread(value, include_body=True), separators=(",", ":"))

    @tool(name=name("get_message"))
    def get_message(messageId: str) -> str:
        """Read one Gmail message and its plain-text content by message ID."""
        resource_id = _resource_id(messageId, "messageId")
        value = _api_json(
            _google_access_token(binding),
            f"messages/{urllib.parse.quote(resource_id, safe='')}",
            query={"format": "full"},
        )
        return json.dumps(_message(value, include_body=True), separators=(",", ":"))

    @tool(name=name("list_labels"))
    def list_labels() -> str:
        """List Gmail system and user labels for the connected account."""
        value = _api_json(_google_access_token(binding), "labels")
        labels = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
            }
            for item in value.get("labels", [])
            if isinstance(item, dict)
        ]
        return json.dumps({"labels": labels}, separators=(",", ":"))

    @tool(name=name("list_drafts"))
    def list_drafts(pageSize: int = 20, pageToken: str = "") -> str:
        """List Gmail draft IDs and message IDs without sending anything."""
        count = _page_size(pageSize)
        if not isinstance(pageToken, str) or len(pageToken) > 2_000:
            raise ValueError("pageToken is invalid")
        value = _api_json(
            _google_access_token(binding),
            "drafts",
            query={"maxResults": count, "pageToken": pageToken},
        )
        return json.dumps(
            {
                "drafts": value.get("drafts", []),
                "nextPageToken": value.get("nextPageToken"),
                "resultCountEstimate": value.get("resultSizeEstimate", 0),
            },
            separators=(",", ":"),
        )

    @tool(name=name("get_draft"))
    def get_draft(draftId: str) -> str:
        """Read one existing Gmail draft by draft ID without sending it."""
        resource_id = _resource_id(draftId, "draftId")
        value = _api_json(
            _google_access_token(binding),
            f"drafts/{urllib.parse.quote(resource_id, safe='')}",
            query={"format": "full"},
        )
        message = value.get("message")
        return json.dumps(
            {
                "id": value.get("id"),
                "message": (
                    _message(message, include_body=True)
                    if isinstance(message, dict)
                    else None
                ),
            },
            separators=(",", ":"),
        )

    @tool(name=name("create_draft"))
    def create_draft(
        subject: str,
        body: str,
        to: str = "",
        cc: str = "",
        bcc: str = "",
        htmlBody: str = "",
        inlineImageIds: list[str] | None = None,
    ) -> str:
        """Create a Gmail draft for review; this tool cannot send email.

        For a rich newsletter, supply htmlBody plus inlineImageIds returned by the
        first-party points screenshot tool. Reference each image exactly once as
        cid:<artifactId> in an img src. External images, scripts, forms, trackers,
        and unsafe links are rejected. `body` is the required plain-text fallback.
        """
        clean_subject = _bounded_text(subject, "subject", 998, required=True)
        if not isinstance(body, str) or not body.strip() or len(body) > 100_000:
            raise ValueError("body is invalid")
        recipients = {
            "To": _bounded_text(to, "to", 4_000, required=False),
            "Cc": _bounded_text(cc, "cc", 4_000, required=False),
            "Bcc": _bounded_text(bcc, "bcc", 4_000, required=False),
        }
        message = EmailMessage()
        message["Subject"] = clean_subject
        for header, value in recipients.items():
            if value:
                message[header] = value
        message.set_content(body)
        image_ids = _newsletter_image_ids(inlineImageIds)
        if htmlBody or image_ids:
            rich_body = _validated_newsletter_html(htmlBody, image_ids)
            if image_ids and not artifact_prefix:
                raise ValueError("Inline image artifacts are unavailable")
            inline_images = [
                artifacts.load_png_artifact(
                    artifact_prefix or "", image_id, client=storage_client
                )
                for image_id in image_ids
            ]
            message.add_alternative(rich_body, subtype="html")
            html_part = message.get_payload()[-1]
            for image in inline_images:
                html_part.add_related(
                    image["body"],
                    maintype="image",
                    subtype="png",
                    cid=f"<{image['artifactId']}>",
                    filename=image["filename"],
                    disposition="inline",
                )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        value = _api_json(
            _google_access_token(binding),
            "drafts",
            payload={"message": {"raw": raw}},
        )
        saved_message = value.get("message")
        return json.dumps(
            {
                "draftId": value.get("id"),
                "messageId": (
                    saved_message.get("id") if isinstance(saved_message, dict) else None
                ),
                "threadId": (
                    saved_message.get("threadId")
                    if isinstance(saved_message, dict)
                    else None
                ),
                "status": "draft_created_not_sent",
            },
            separators=(",", ":"),
        )

    account_label = binding.get("accountLabel")
    tools = [
        create_draft,
        list_drafts,
        get_draft,
        get_thread,
        get_message,
        search_threads,
        list_labels,
    ]
    if not account_label:
        return tools
    return [
        tool(
            name=item.tool_name,
            description=f"{item.tool_spec['description']} Connected account: {account_label}.",
        )(item.__wrapped__)
        for item in tools
    ]


__all__ = ["gmail_api_tools"]
