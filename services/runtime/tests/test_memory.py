from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from strands.memory import MemoryEntry

from heytim_runtime import memory


def test_memory_context_validates_worker_identity_envelope() -> None:
    context = memory.memory_context_from_payload(
        {
            "memory": {
                "actorId": "a" * 64,
                "sessionId": "b" * 64,
                "eventId": "7ac6f8b2-5ea9-4ea8-a8a4-54ca9670ca13",
            }
        }
    )

    assert context is not None
    assert context.actor_id == "a" * 64
    assert context.scope == "personal"


def test_group_memory_context_keeps_the_original_user_prompt() -> None:
    context = memory.memory_context_from_payload(
        {
            "memory": {
                "actorId": "a" * 64,
                "sessionId": "b" * 64,
                "eventId": "event-1",
                "scope": "group",
                "userText": "Make a shared launch plan.",
            }
        }
    )

    assert context is not None
    assert context.scope == "group"
    assert context.user_text == "Make a shared launch plan."


def test_memory_context_rejects_untrusted_identifiers() -> None:
    with pytest.raises(ValueError, match="memory.actorId"):
        memory.memory_context_from_payload(
            {
                "memory": {
                    "actorId": "../../another-user",
                    "sessionId": "session-1",
                    "eventId": "event-1",
                }
            }
        )


def test_completed_turn_uses_event_id_as_idempotency_token(monkeypatch) -> None:
    monkeypatch.setattr(memory, "MEMORY_ID", "FrogBotMemory-abcdefghij")
    client = MagicMock()
    context = memory.MemoryContext("actor-1", "session-1", "event-1")

    asyncio.run(
        memory.record_completed_turn(
            context,
            "Remember that I prefer tea.",
            "I'll remember that.",
            client=client,
        )
    )

    request = client.create_event.call_args.kwargs
    assert request["clientToken"] == "event-1"
    assert request["actorId"] == "actor-1"
    assert [item["conversational"]["role"] for item in request["payload"]] == [
        "USER",
        "ASSISTANT",
    ]
    assert request["metadata"]["heytimScope"]["stringValue"] == "personal"


def test_balanced_store_round_robins_categories() -> None:
    class Store:
        writable = False
        extraction = None
        max_search_results = 3

        def __init__(self, name: str, values: list[str]) -> None:
            self.name = name
            self.description = None
            self.values = values

        async def search(self, _query: str, options=None) -> list[MemoryEntry]:
            limit = options["max_search_results"]
            return [MemoryEntry(content=value) for value in self.values[:limit]]

    store = memory.BalancedMemoryStore(
        "personal-memory",
        [
            ("Preference", Store("preferences", ["p1", "p2"])),
            ("Fact", Store("facts", ["f1", "f2"])),
            ("Summary", Store("summaries", ["s1", "s2"])),
        ],
    )

    entries = asyncio.run(store.search("launch", {"max_search_results": 5}))

    assert [entry.content for entry in entries] == [
        "Preference: p1",
        "Fact: f1",
        "Summary: s1",
        "Preference: p2",
        "Fact: f2",
    ]


def test_balanced_store_bounds_agentcore_search_queries() -> None:
    queries = []

    class Store:
        name = "preferences"

        async def search(self, query: str, _options=None) -> list[MemoryEntry]:
            queries.append(query)
            return []

    store = memory.BalancedMemoryStore(
        "personal-memory",
        [("Preference", Store())],
    )

    asyncio.run(store.search("x" * (memory.MAX_MEMORY_SEARCH_QUERY_CHARS + 1)))

    assert queries == ["x" * memory.MAX_MEMORY_SEARCH_QUERY_CHARS]


def test_group_store_uses_only_the_group_actor_for_each_category(monkeypatch) -> None:
    captured = {}

    class Store:
        writable = False
        extraction = None
        max_search_results = 2
        description = None

        def __init__(self, name: str) -> None:
            self.name = name

        async def search(self, _query: str, _options=None) -> list[MemoryEntry]:
            return []

    def factory(**kwargs):
        captured.update(kwargs)
        return [Store(value["name"]) for value in kwargs["namespaces"]]

    monkeypatch.setattr(memory, "MEMORY_ID", "memory-1")
    monkeypatch.setattr(memory, "create_agentcore_memory_stores", factory)

    stores = memory.memory_stores(
        memory.MemoryContext("group-actor", "group-session", "event-1", "group")
    )

    assert stores is not None
    assert captured["actor_id"] == "group-actor"
    assert [value["name"] for value in captured["namespaces"]] == [
        "preferences",
        "facts",
        "summaries",
    ]
