from __future__ import annotations

import asyncio
import logging
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
from strands.memory import MemoryEntry, MemoryStore, SearchOptions

MEMORY_ID = os.environ.get("MEMORY_HEYTIMMEMORY_ID")
_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_MEMORY_SCOPES = {"personal", "group"}
MAX_MEMORY_SEARCH_QUERY_CHARS = 10_000
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryContext:
    actor_id: str
    session_id: str
    event_id: str
    scope: str = "personal"
    user_text: str | None = None


class BalancedMemoryStore:
    """Recall from every memory category without registration-order starvation."""

    def __init__(
        self,
        name: str,
        stores: list[tuple[str, MemoryStore]],
        *,
        max_search_results: int = 6,
    ) -> None:
        self.name = name
        self.description = "Scoped AgentCore memories, balanced across categories."
        self.max_search_results = max_search_results
        self.writable = False
        self.extraction = None
        self._stores = stores

    async def search(
        self, query: str, options: SearchOptions | None = None
    ) -> list[MemoryEntry]:
        # AgentCore Memory rejects searchQuery values over 10,000 characters.
        # A long user turn should degrade to bounded recall instead of failing
        # every category lookup and polluting the runtime's error telemetry.
        query = query[:MAX_MEMORY_SEARCH_QUERY_CHARS]
        want = (
            options.get("max_search_results")
            if options and "max_search_results" in options
            else self.max_search_results
        )
        if type(want) is not int or want < 1:
            raise ValueError("Memory result limit must be a positive integer")
        per_store = max(1, (want + len(self._stores) - 1) // len(self._stores))
        settled = await asyncio.gather(
            *(
                store.search(query, {"max_search_results": per_store})
                for _label, store in self._stores
            ),
            return_exceptions=True,
        )
        buckets: list[list[MemoryEntry]] = []
        for (label, store), outcome in zip(self._stores, settled, strict=True):
            if isinstance(outcome, BaseException):
                logger.warning(
                    "Memory category %s could not be searched: %s", store.name, outcome
                )
                buckets.append([])
                continue
            buckets.append(
                [
                    MemoryEntry(
                        content=f"{label}: {entry.content}",
                        metadata=entry.metadata,
                    )
                    for entry in outcome
                ]
            )

        results: list[MemoryEntry] = []
        for index in range(per_store):
            for bucket in buckets:
                if index < len(bucket):
                    results.append(bucket[index])
                    if len(results) == want:
                        return results
        return results


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
    scope = raw.get("scope", "personal")
    if scope not in _MEMORY_SCOPES:
        raise ValueError("memory.scope is invalid")
    user_text = raw.get("userText")
    if user_text is not None and (
        not isinstance(user_text, str)
        or not user_text.strip()
        or len(user_text) > 12_000
    ):
        raise ValueError("memory.userText is invalid")
    values["scope"] = scope
    values["user_text"] = user_text.strip() if isinstance(user_text, str) else None
    return MemoryContext(**values)


def memory_stores(context: MemoryContext | None) -> list[MemoryStore] | None:
    """Build one balanced, recall-only store for Strands harness and its delegates."""
    if context is None or not MEMORY_ID:
        return None
    namespaces = [
        {
            "name": "preferences",
            "namespace": "/preferences/{actorId}/",
            "max_search_results": 2,
            "min_score": 0.45,
        },
        {
            "name": "facts",
            "namespace": "/facts/{actorId}/",
            "max_search_results": 2,
            "min_score": 0.4,
        },
        {
            "name": "summaries",
            "namespace": "/summaries/{actorId}/{sessionId}/",
            "max_search_results": 2,
            "min_score": 0.4,
        },
    ]
    if context.scope == "personal":
        labels = [
            "Personal preference",
            "Personal fact",
            "This bot's conversation summary",
        ]
    else:
        labels = [
            "Shared group preference",
            "Shared group fact",
            "Group conversation summary",
        ]
    category_stores = create_agentcore_memory_stores(
        memory_id=MEMORY_ID,
        actor_id=context.actor_id,
        session_id=context.session_id,
        namespaces=namespaces,
        extraction=False,
    )
    balanced = BalancedMemoryStore(
        f"{context.scope}-memory",
        list(zip(labels, category_stores, strict=True)),
    )
    return [balanced]


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
    user_text = context.user_text if context and context.user_text else user_text
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
        metadata={
            "heytimScope": {"stringValue": context.scope},
            "heytimSource": {"stringValue": "conversation"},
        },
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
