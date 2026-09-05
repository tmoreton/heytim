from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3
from bedrock_agentcore.memory.integrations.strands.memorystore import (
    create_agentcore_memory_stores,
)
from botocore.config import Config
from strands.memory import MemoryManager

MEMORY_ID = os.environ.get("MEMORY_FROGBOTMEMORY_ID")
_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class MemoryContext:
    actor_id: str
    session_id: str
    event_id: str


def memory_context_from_payload(payload: dict) -> MemoryContext | None:
    """Validate the trusted identity envelope supplied by the app worker."""
    raw = payload.get("memory")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("memory must be an object")
    values = {}
    for source, target, maximum in (
        ("actorId", "actor_id", 255),
        ("sessionId", "session_id", 100),
        ("eventId", "event_id", 128),
    ):
        value = raw.get(source)
        if (
            not isinstance(value, str)
            or not value
            or len(value) > maximum
            or not _IDENTITY_PATTERN.fullmatch(value)
        ):
            raise ValueError(f"memory.{source} is invalid")
        values[target] = value
    return MemoryContext(**values)


def memory_manager(context: MemoryContext | None) -> MemoryManager | None:
    """Build recall-only stores; each completed turn is written once separately."""
    if context is None or not MEMORY_ID:
        return None
    stores = create_agentcore_memory_stores(
        memory_id=MEMORY_ID,
        actor_id=context.actor_id,
        session_id=context.session_id,
        namespaces=[
            {
                "name": "preferences",
                "namespace": "/preferences/{actorId}/",
                "max_search_results": 3,
                "min_score": 0.45,
            },
            {
                "name": "facts",
                "namespace": "/facts/{actorId}/",
                "max_search_results": 3,
                "min_score": 0.4,
            },
            {
                "name": "summaries",
                "namespace": "/summaries/{actorId}/{sessionId}/",
                "max_search_results": 3,
                "min_score": 0.4,
            },
        ],
        extraction=False,
    )
    return MemoryManager(
        stores=stores,
        injection={"trigger": "userTurn", "max_entries": 6},
    )


def message_text(message: Any, role: str) -> str | None:
    if not isinstance(message, dict) or message.get("role") != role:
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    parts = [
        block["text"].strip()
        for block in content
        if isinstance(block, dict)
        and isinstance(block.get("text"), str)
        and block["text"].strip()
    ]
    return "\n".join(parts) if parts else None


def latest_assistant_text(messages: Any) -> str | None:
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        text = message_text(message, "assistant")
        if text:
            return text
    return None


def _memory_client():
    return boto3.client(
        "bedrock-agentcore",
        config=Config(
            retries={"total_max_attempts": 4, "mode": "adaptive"},
            connect_timeout=3,
            read_timeout=15,
        ),
    )


async def record_completed_turn(
    context: MemoryContext | None,
    user_text: str | None,
    assistant_text: str | None,
    *,
    client=None,
) -> None:
    """Persist exactly one completed user/assistant turn with retry idempotency."""
    if context is None or not MEMORY_ID or not user_text or not assistant_text:
        return
    target = client or _memory_client()
    await asyncio.to_thread(
        target.create_event,
        memoryId=MEMORY_ID,
        actorId=context.actor_id,
        sessionId=context.session_id,
        eventTimestamp=datetime.now(UTC),
        clientToken=context.event_id,
        payload=[
            {"conversational": {"role": "USER", "content": {"text": user_text}}},
            {
                "conversational": {
                    "role": "ASSISTANT",
                    "content": {"text": assistant_text},
                }
            },
        ],
    )
