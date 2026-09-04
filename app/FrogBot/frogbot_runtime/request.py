from __future__ import annotations

from typing import Any

MAX_HISTORY_MESSAGES = 40
MAX_MESSAGE_CHARS = 12_000


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


def messages_from_payload(payload: dict) -> list[dict]:
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

    messages: list[dict] = []
    for message in strip_trailing_tool_use(raw_messages)[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(message, dict) or message.get("role") not in {
            "user",
            "assistant",
        }:
            raise ValueError("each message must have a user or assistant role")
        content = message.get("content")
        if not isinstance(content, list) or not content:
            raise ValueError("each message must contain at least one content block")
        text_blocks = []
        for block in content:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                raise TypeError("only text content blocks are accepted")
            text = block["text"].strip()
            if not text or len(text) > MAX_MESSAGE_CHARS:
                raise ValueError(
                    f"message text must be between 1 and {MAX_MESSAGE_CHARS} characters"
                )
            text_blocks.append({"text": text})
        messages.append({"role": message["role"], "content": text_blocks})
    return messages
