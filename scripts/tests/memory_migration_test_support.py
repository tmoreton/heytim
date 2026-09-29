"""Offline AgentCore Memory client and fixture shared by migration tests."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "migrate-agentcore-memory.py"
SCRIPT_DIRECTORY = str(SCRIPT.parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)
spec = importlib.util.spec_from_file_location("migrate_agentcore_memory", SCRIPT)
assert spec and spec.loader
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class Paginator:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def paginate(self, **kwargs):
        kwargs.pop("PaginationConfig")
        key = {
            "list_actors": "actorSummaries",
            "list_sessions": "sessionSummaries",
            "list_events": "events",
            "list_memory_records": "memoryRecordSummaries",
        }[self.name]
        values = self.client.list_values(self.name, **kwargs)
        for offset in range(0, len(values), 1):
            yield {key: values[offset : offset + 1]}


class MemoryClient:
    def __init__(self, events=None, records=None):
        self.events = list(events or [])
        self.records = list(records or [])
        self.event_calls = []
        self.record_calls = []

    def can_paginate(self, name):
        return True

    def get_paginator(self, name):
        return Paginator(self, name)

    def list_values(self, name, **kwargs):
        if name == "list_actors":
            return [
                {"actorId": actor}
                for actor in sorted({e["actorId"] for e in self.events})
            ]
        if name == "list_sessions":
            return [
                {"actorId": kwargs["actorId"], "sessionId": session}
                for session in sorted(
                    {
                        e["sessionId"]
                        for e in self.events
                        if e["actorId"] == kwargs["actorId"]
                    }
                )
            ]
        if name == "list_events":
            return [
                e
                for e in self.events
                if e["actorId"] == kwargs["actorId"]
                and e["sessionId"] == kwargs["sessionId"]
            ]
        if name == "list_memory_records":
            return [
                r
                for r in self.records
                if (
                    not kwargs.get("memoryStrategyId")
                    or r["memoryStrategyId"] == kwargs["memoryStrategyId"]
                )
                and any(n.startswith(kwargs["namespacePath"]) for n in r["namespaces"])
            ]
        raise AssertionError(name)

    def create_event(self, **kwargs):
        self.event_calls.append(kwargs)
        event = {
            k: v
            for k, v in kwargs.items()
            if k
            in {
                "actorId",
                "sessionId",
                "eventTimestamp",
                "payload",
                "metadata",
                "branch",
            }
        }
        event["eventId"] = f"new-event-{len(self.events) + 1}"
        self.events.append(event)
        return {"event": event}

    def batch_create_memory_records(self, **kwargs):
        self.record_calls.append(kwargs)
        response = []
        for record in kwargs["records"]:
            record_id = f"new-record-{len(self.records) + 1}"
            self.records.append(
                {
                    "memoryRecordId": record_id,
                    "content": record["content"],
                    "namespaces": record["namespaces"],
                    "createdAt": record["timestamp"],
                    "metadata": record.get("metadata", {}),
                    "memoryStrategyId": record["memoryStrategyId"],
                }
            )
            response.append(
                {
                    "memoryRecordId": record_id,
                    "requestIdentifier": record["requestIdentifier"],
                }
            )
        return {"successfulRecords": response, "failedRecords": []}


class MemoryMigrationFixture:
    def setUp(self):
        self.when = datetime(2026, 9, 15, 10, 20, 30, tzinfo=UTC)
        self.source = MemoryClient(
            events=[
                {
                    "eventId": "event-1",
                    "actorId": "actor-old",
                    "sessionId": "session-old",
                    "eventTimestamp": self.when,
                    "payload": [
                        {
                            "conversational": {
                                "role": "USER",
                                "content": {"text": "private conversation"},
                            }
                        }
                    ],
                    "metadata": {"heytimScope": {"stringValue": "personal"}},
                }
            ],
            records=[
                {
                    "memoryRecordId": "record-1",
                    "memoryStrategyId": "facts-old",
                    "namespaces": ["/facts/actor-old/"],
                    "content": {"text": "private fact"},
                    "createdAt": self.when,
                    "metadata": {"heytimSource": {"stringValue": "manual"}},
                },
                {
                    "memoryRecordId": "record-2",
                    "memoryStrategyId": "summaries-old",
                    "namespaces": ["/summaries/actor-old/session-old/"],
                    "content": {"text": "private summary"},
                    "createdAt": self.when,
                    "metadata": {},
                },
            ],
        )
        self.destination = MemoryClient()
        self.original = migration.inventory(
            self.source, "source-memory", ["facts-old", "summaries-old"]
        )
        self.actors = {"actor-old": "actor-new"}
        self.sessions = {("actor-old", "session-old"): "session-new"}
        self.strategies = {"facts-old": "facts-new", "summaries-old": "summaries-new"}
