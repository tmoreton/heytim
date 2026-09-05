from __future__ import annotations

import os
import re
from typing import Any

import boto3
from botocore.config import Config

MAX_HISTORY_MESSAGES = 40
MAX_MESSAGE_CHARS = 12_000
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 4_500_000
DOCUMENT_FORMATS = {"pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"}
IMAGE_FORMATS = {"png", "jpeg", "gif", "webp"}
FILES_BUCKET_NAME = os.environ.get("FROGBOT_FILES_BUCKET", "")
_ACTOR_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_s3 = None


def _s3_source(value: Any, actor_id: str | None) -> dict:
    global _s3
    if not FILES_BUCKET_NAME:
        raise ValueError("attachment source is invalid")
    if not isinstance(actor_id, str) or not _ACTOR_ID_PATTERN.fullmatch(actor_id):
        raise ValueError("attachment identity is invalid")
    if not isinstance(value, dict):
        raise TypeError("attachment source must be an object")
    location = value.get("s3Location")
    if not isinstance(location, dict):
        raise TypeError("attachment S3 location must be an object")
    uri = location.get("uri")
    prefix = f"s3://{FILES_BUCKET_NAME}/users/{actor_id}/"
    if not isinstance(uri, str) or not uri.startswith(prefix) or len(uri) > 1024:
        raise ValueError("attachment source is outside the FroggyBot file store")
    key = uri[len(f"s3://{FILES_BUCKET_NAME}/") :]
    if _s3 is None:
        _s3 = boto3.client(
            "s3",
            config=Config(
                retries={"total_max_attempts": 4, "mode": "adaptive"},
                connect_timeout=3,
                read_timeout=20,
            ),
        )
    response = _s3.get_object(Bucket=FILES_BUCKET_NAME, Key=key)
    if int(response.get("ContentLength", 0)) > MAX_ATTACHMENT_BYTES:
        raise ValueError("attachment is too large")
    body = response["Body"].read(MAX_ATTACHMENT_BYTES + 1)
    if not body or len(body) > MAX_ATTACHMENT_BYTES:
        raise ValueError("attachment is empty or too large")
    # Claude accepts inline attachment bytes but not S3 document locations.
    return {"bytes": body}


def _attachment_block(block: dict, index: int, actor_id: str | None) -> dict:
    if "image" in block:
        image = block["image"]
        if not isinstance(image, dict) or image.get("format") not in IMAGE_FORMATS:
            raise ValueError("image attachment format is invalid")
        return {
            "image": {
                "format": image["format"],
                "source": _s3_source(image.get("source"), actor_id),
            }
        }
    if "document" in block:
        document = block["document"]
        if (
            not isinstance(document, dict)
            or document.get("format") not in DOCUMENT_FORMATS
        ):
            raise ValueError("document attachment format is invalid")
        return {
            "document": {
                "format": document["format"],
                "name": f"Attachment {index}",
                "source": _s3_source(document.get("source"), actor_id),
            }
        }
    raise TypeError("only text and reviewed attachment content blocks are accepted")


def strip_trailing_tool_use(messages: Any) -> list[dict]:
    """Strip toolUse blocks from the tail until the final message is safe to resume."""
    if not isinstance(messages, list):
        raise TypeError("messages must be a list")

    cleaned = list(messages)
    while cleaned:
        last = cleaned[-1]
        if not isinstance(last, dict):
            raise TypeError("each message must be an object")
        original_content = last.get("content", [])
        if not isinstance(original_content, list) or not all(
            isinstance(block, dict) for block in original_content
        ):
            raise TypeError(
                "each message content value must be a list of content blocks"
            )
        content = [block for block in original_content if "toolUse" not in block]
        if len(content) == len(original_content):
            break
        if content:
            cleaned[-1] = {**last, "content": content}
            break
        cleaned.pop()
    return cleaned


def messages_from_payload(payload: dict, actor_id: str | None = None) -> list[dict]:
    """Validate and normalize the caller-supplied conversation."""
    if not isinstance(payload, dict):
        raise TypeError("payload must be a JSON object")

    raw_messages = payload.get("messages")
    if raw_messages is None:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        raw_messages = [{"role": "user", "content": [{"text": prompt.strip()}]}]
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ValueError("messages must be a non-empty list")

    normalized_messages = strip_trailing_tool_use(raw_messages)[-MAX_HISTORY_MESSAGES:]
    messages: list[dict] = []
    for message_index, message in enumerate(normalized_messages):
        if not isinstance(message, dict) or message.get("role") not in {
            "user",
            "assistant",
        }:
            raise ValueError("each message must have a user or assistant role")
        content = message.get("content")
        if not isinstance(content, list) or not content:
            raise ValueError("each message must contain at least one content block")
        content_blocks = []
        attachment_count = 0
        has_text = False
        for block in content:
            if not isinstance(block, dict):
                raise TypeError("each content block must be an object")
            if isinstance(block.get("text"), str):
                text = block["text"].strip()
                if not text or len(text) > MAX_MESSAGE_CHARS:
                    raise ValueError(
                        f"message text must be between 1 and {MAX_MESSAGE_CHARS} characters"
                    )
                content_blocks.append({"text": text})
                has_text = True
                continue
            if (
                message.get("role") != "user"
                or message_index != len(normalized_messages) - 1
            ):
                raise ValueError(
                    "attachments are accepted only on the latest user message"
                )
            attachment_count += 1
            if attachment_count > MAX_ATTACHMENTS:
                raise ValueError(
                    f"a message can contain at most {MAX_ATTACHMENTS} attachments"
                )
            content_blocks.append(_attachment_block(block, attachment_count, actor_id))
        if not has_text:
            raise ValueError("each message must contain a text content block")
        messages.append({"role": message["role"], "content": content_blocks})
    return messages
