from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from frogbot_runtime import memory


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


def test_model_enables_one_hour_prompt_and_tool_caching() -> None:
    from model.load import load_model

    model = load_model()

    assert model.config["cache_config"].ttl == "1h"
    assert model.config["cache_tools"].ttl == "1h"
