from __future__ import annotations

import os
import re
from typing import Any

import boto3
from botocore.config import Config

MAX_HISTORY_MESSAGES = 100
MAX_MESSAGE_CHARS = 12_000
MAX_CONTENT_BLOCKS_PER_MESSAGE = 24
MAX_HISTORY_TEXT_CHARS = 240_000
MAX_ATTACHMENTS = 5
MAX_IMAGE_REFERENCES = 5
MAX_ATTACHMENT_BYTES = 4_500_000
DOCUMENT_FORMATS = {"pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"}
IMAGE_FORMATS = {"png", "jpeg", "gif", "webp"}
FILES_BUCKET_NAME = os.environ.get("HEYTIM_FILES_BUCKET", "")
_ACTOR_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_GROUP_ATTACHMENT_PREFIX_PATTERN = re.compile(r"^groups/[a-f0-9-]{36}/uploads/$")
_s3 = None


def _s3_source(
    value: Any, actor_id: str | None, group_prefix: str | None = None
) -> dict:
    global _s3
    if not FILES_BUCKET_NAME:
        raise ValueError("attachment source is invalid")
    if group_prefix is None and (
        not isinstance(actor_id, str) or not _ACTOR_ID_PATTERN.fullmatch(actor_id)
    ):
        raise ValueError("attachment identity is invalid")
    if not isinstance(value, dict):
        raise TypeError("attachment source must be an object")
    location = value.get("s3Location")
    if not isinstance(location, dict):
        raise TypeError("attachment S3 location must be an object")
    uri = location.get("uri")
    prefix = f"s3://{FILES_BUCKET_NAME}/{group_prefix or f'users/{actor_id}/'}"
    workspace_prefix = (
        f"s3://{FILES_BUCKET_NAME}/{group_prefix[:-len('uploads/')]}workspace/"
        if group_prefix else None
    )
    if not isinstance(uri, str) or len(uri) > 1024 or not (
        uri.startswith(prefix)
        or (workspace_prefix is not None and uri.startswith(workspace_prefix))
    ):
        raise ValueError("attachment source is outside the HeyTim file store")
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
        response["Body"].close()
        raise ValueError("attachment is too large")
    stream = response["Body"]
    try:
        body = stream.read(MAX_ATTACHMENT_BYTES + 1)
    finally:
        stream.close()
    if not body or len(body) > MAX_ATTACHMENT_BYTES:
        raise ValueError("attachment is empty or too large")
    # Claude accepts inline attachment bytes but not S3 document locations.
    return {"bytes": body}


def _attachment_block(
    block: dict,
    index: int,
    actor_id: str | None,
    group_prefix: str | None = None,
) -> dict:
    if "image" in block:
        image = block["image"]
        if not isinstance(image, dict) or image.get("format") not in IMAGE_FORMATS:
            raise ValueError("image attachment format is invalid")
        return {
            "image": {
                "format": image["format"],
                "source": _s3_source(image.get("source"), actor_id, group_prefix),
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
                "source": _s3_source(document.get("source"), actor_id, group_prefix),
            }
        }
    raise TypeError("only text and reviewed attachment content blocks are accepted")


def image_references_from_payload(
    payload: dict, actor_id: str | None = None
) -> list[dict]:
    """Load recent, user-owned image references without adding them to model history."""
    raw_references = payload.get("imageReferences", [])
    if (
        not isinstance(raw_references, list)
        or len(raw_references) > MAX_IMAGE_REFERENCES
    ):
        raise ValueError(
            f"imageReferences must be a list of at most {MAX_IMAGE_REFERENCES} images"
        )
    group_prefix = payload.get("attachmentPrefix")
    if group_prefix is not None and (
        not isinstance(payload.get("group"), dict)
        or not isinstance(group_prefix, str)
        or not _GROUP_ATTACHMENT_PREFIX_PATTERN.fullmatch(group_prefix)
    ):
        raise ValueError("group attachment scope is invalid")

    references = []
    for index, raw in enumerate(raw_references, start=1):
        if not isinstance(raw, dict):
            raise TypeError("each image reference must be an object")
        raw_name = raw.get("name", f"Image {index}")
        if not isinstance(raw_name, str):
            raise TypeError("image reference name must be text")
        name = re.sub(
            r"[\x00-\x1f\x7f]", " ", raw_name.replace("\\", "/").rsplit("/", 1)[-1]
        )
        name = " ".join(name.split()).strip()[:120] or f"Image {index}"
        block = _attachment_block(
            {"image": raw.get("image")}, index, actor_id, group_prefix
        )
        references.append({"name": name, "body": block["image"]["source"]["bytes"]})
    return references


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

    group_prefix = payload.get("attachmentPrefix")
    if group_prefix is not None and (
        not isinstance(payload.get("group"), dict)
        or not isinstance(group_prefix, str)
        or not _GROUP_ATTACHMENT_PREFIX_PATTERN.fullmatch(group_prefix)
    ):
        raise ValueError("group attachment scope is invalid")

    raw_messages = payload.get("messages")
    if raw_messages is None:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        raw_messages = [{"role": "user", "content": [{"text": prompt.strip()}]}]
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ValueError("messages must be a non-empty list")

    normalized_messages = strip_trailing_tool_use(raw_messages)[-MAX_HISTORY_MESSAGES:]
    if not normalized_messages:
        raise ValueError("messages must contain a user message after normalization")
    if (
        not isinstance(normalized_messages[-1], dict)
        or normalized_messages[-1].get("role") != "user"
    ):
        raise ValueError("latest message must be a user message")
    messages: list[dict] = []
    history_text_chars = 0
    for message_index, message in enumerate(normalized_messages):
        if not isinstance(message, dict) or message.get("role") not in {
            "user",
            "assistant",
        }:
            raise ValueError("each message must have a user or assistant role")
        content = message.get("content")
        if not isinstance(content, list) or not content:
            raise ValueError("each message must contain at least one content block")
        if len(content) > MAX_CONTENT_BLOCKS_PER_MESSAGE:
            raise ValueError(
                f"each message can contain at most {MAX_CONTENT_BLOCKS_PER_MESSAGE} content blocks"
            )
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
                history_text_chars += len(text)
                if history_text_chars > MAX_HISTORY_TEXT_CHARS:
                    raise ValueError("message history text is too large")
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
            content_blocks.append(
                _attachment_block(block, attachment_count, actor_id, group_prefix)
            )
        if not has_text:
            raise ValueError("each message must contain a text content block")
        messages.append({"role": message["role"], "content": content_blocks})
    return messages
