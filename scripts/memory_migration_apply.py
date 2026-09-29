"""Replay and verify a mapped AgentCore Memory snapshot."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any

from botocore.validate import validate_parameters
from memory_migration_inventory import (
    digest,
    event_fields,
    inventory,
    paged,
    record_fields,
)


def mapped_namespace(
    path: str, actors: dict[str, str], sessions: dict[tuple[str, str], str]
) -> str:
    parts = path.split("/")
    if (
        len(parts) < 4
        or parts[0]
        or parts[1] not in {"facts", "preferences", "summaries"}
    ):
        raise ValueError("Unsupported memory namespace")
    source_actor = parts[2]
    if source_actor not in actors:
        raise ValueError("Record namespace refers to an unmapped actor")
    parts[2] = actors[source_actor]
    if parts[1] == "summaries":
        if len(parts) < 5 or (source_actor, parts[3]) not in sessions:
            raise ValueError("Summary namespace refers to an unmapped session")
        parts[3] = sessions[(source_actor, parts[3])]
    return "/".join(parts)


def expected_event(
    event: dict,
    actors: dict[str, str],
    sessions: dict[tuple[str, str], str],
    event_ids: dict[str, str],
) -> dict:
    fields = event_fields(event)
    fields["actorId"] = actors[event["actorId"]]
    fields["sessionId"] = sessions[(event["actorId"], event["sessionId"])]
    if "branch" in fields and "rootEventId" in fields["branch"]:
        branch = dict(fields["branch"])
        root = branch["rootEventId"]
        if root not in event_ids:
            raise ValueError("Branch root must be migrated before its child event")
        branch["rootEventId"] = event_ids[root]
        fields["branch"] = branch
    return fields


def expected_record(
    record: dict,
    actors: dict[str, str],
    sessions: dict[tuple[str, str], str],
    strategies: dict[str, str],
) -> dict:
    fields = record_fields(record)
    fields["memoryStrategyId"] = strategies[record["memoryStrategyId"]]
    fields["namespaces"] = [
        mapped_namespace(n, actors, sessions) for n in record["namespaces"]
    ]
    return fields


def deterministic_token(kind: str, destination_id: str, source_ids: list[str]) -> str:
    return f"heytim-{kind}-{digest([destination_id, source_ids])[:56]}"


def validate_payload_shapes(
    destination: Any, destination_id: str, original: dict, strategies: dict[str, str]
) -> None:
    """Validate every source payload against the destination SDK model before writing."""
    operations = destination.meta.service_model
    event_shape = operations.operation_model("CreateEvent").input_shape
    batch_shape = operations.operation_model("BatchCreateMemoryRecords").input_shape
    identity_actors = {actor: actor for actor in original["actors"]}
    identity_sessions = {
        (actor, session): session for actor, session in original["sessions"]
    }
    for event in original["events"]:
        validate_parameters(
            {
                **event_fields(event),
                "memoryId": destination_id,
                "extractionMode": "SKIP",
                "clientToken": deterministic_token(
                    "event", destination_id, [event["eventId"]]
                ),
            },
            event_shape,
        )
    for record in original["records"]:
        fields = expected_record(record, identity_actors, identity_sessions, strategies)
        validate_parameters(
            {
                "memoryId": destination_id,
                "records": [
                    {
                        "requestIdentifier": deterministic_token(
                            "record", destination_id, [record["memoryRecordId"]]
                        ),
                        "namespaces": fields["namespaces"],
                        "content": fields["content"],
                        "timestamp": fields["createdAt"],
                        "memoryStrategyId": fields["memoryStrategyId"],
                        **(
                            {"metadata": fields["metadata"]}
                            if "metadata" in fields
                            else {}
                        ),
                    }
                ],
            },
            batch_shape,
        )


def batches(items: list[dict], size: int = 100) -> list[list[dict]]:
    return [items[offset : offset + size] for offset in range(0, len(items), size)]


def ordered_events(events: list[dict]) -> list[dict]:
    by_id = {event["eventId"]: event for event in events}
    remaining = sorted(
        events, key=lambda event: (event["eventTimestamp"], event["eventId"])
    )
    result = []
    done = set()
    while remaining:
        pending = []
        for event in remaining:
            root = event.get("branch", {}).get("rootEventId")
            if root and root not in by_id:
                raise ValueError(
                    "A branch root event is absent from the source inventory"
                )
            if root and root not in done:
                pending.append(event)
                continue
            result.append(event)
            done.add(event["eventId"])
        if len(pending) == len(remaining):
            raise ValueError("Cyclic AgentCore event branches")
        remaining = pending
    return result


def write_manifest(path: Path, manifest: dict) -> None:
    # The manifest has identifiers and digests only. Never serialize API payloads.
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def replace_manifest(path: Path, manifest: dict) -> None:
    if path.stat().st_mode & 0o077:
        raise ValueError("Manifest permissions changed; expected mode 0600")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    write_manifest(temporary, manifest)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_manifest(path: Path) -> dict:
    if path.stat().st_mode & 0o077:
        raise ValueError("Manifest must be readable only by its owner (mode 0600)")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise TypeError("Manifest is invalid")
    return result


def migration_manifest(
    args: argparse.Namespace,
    snapshot: str,
    actors: dict[str, str],
    sessions: dict[tuple[str, str], str],
    strategies: dict[str, str],
    decisions: dict,
) -> dict:
    return {
        "schemaVersion": 1,
        "status": "in-progress",
        "sourceAccount": args.source_account,
        "destinationAccount": args.destination_account,
        "sourceMemoryId": args.source_memory_id,
        "destinationMemoryId": args.destination_memory_id,
        "sourceSnapshotSha256": snapshot,
        "actorIds": actors,
        "sessionIds": {f"{a}/{s}": d for (a, s), d in sessions.items()},
        "strategyIds": strategies,
        "preservationDecisions": decisions,
        "eventIds": {},
        "recordIds": {},
    }


def reconcile_existing(
    original: dict,
    before: dict,
    actors: dict[str, str],
    sessions: dict[tuple[str, str], str],
    strategies: dict[str, str],
    event_map: dict[str, str],
    record_map: dict[str, str],
) -> None:
    """Match a partial destination to source IDs without exposing content."""
    expected_actors = set(actors.values())
    expected_sessions = {(actors[actor], dest) for (actor, _), dest in sessions.items()}
    if (
        not before["actors"] <= expected_actors
        or not before["sessions"] <= expected_sessions
    ):
        raise ValueError("Destination has an unexpected actor or session")
    source_event_ids = {event["eventId"] for event in original["events"]}
    source_record_ids = {record["memoryRecordId"] for record in original["records"]}
    if (
        not set(event_map) <= source_event_ids
        or not set(record_map) <= source_record_ids
        or len(set(event_map.values())) != len(event_map)
        or len(set(record_map.values())) != len(record_map)
    ):
        raise ValueError("Resume manifest contains unknown or duplicate IDs")
    destination_events = {event["eventId"]: event for event in before["events"]}
    available_events: dict[str, list[str]] = {}
    for event in before["events"]:
        available_events.setdefault(digest(event_fields(event)), []).append(
            event["eventId"]
        )
    used_event_ids = set()
    for event in ordered_events(original["events"]):
        source_id = event["eventId"]
        root = event.get("branch", {}).get("rootEventId")
        if root and root not in event_map:
            # A child cannot already exist without its root in the destination.
            if source_id in event_map:
                raise ValueError("Manifest contains a child event without its root")
            continue
        expected_hash = digest(expected_event(event, actors, sessions, event_map))
        mapped_id = event_map.get(source_id)
        if mapped_id:
            existing = destination_events.get(mapped_id)
            if existing is None or digest(event_fields(existing)) != expected_hash:
                raise ValueError("Manifest event ID does not match destination content")
        else:
            candidates = [
                event_id
                for event_id in available_events.get(expected_hash, [])
                if event_id not in used_event_ids
            ]
            if len(candidates) > 1:
                raise ValueError("Ambiguous destination event; cannot safely resume")
            if candidates:
                mapped_id = candidates[0]
                event_map[source_id] = mapped_id
        if mapped_id:
            if mapped_id in used_event_ids:
                raise ValueError("Two source events mapped to one destination event")
            used_event_ids.add(mapped_id)
    if used_event_ids != set(destination_events):
        raise ValueError("Destination has an event not in the source snapshot")

    destination_records = {
        record["memoryRecordId"]: record for record in before["records"]
    }
    available_records: dict[str, list[str]] = {}
    for record in before["records"]:
        available_records.setdefault(digest(record_fields(record)), []).append(
            record["memoryRecordId"]
        )
    used_record_ids = set()
    for record in sorted(
        original["records"], key=lambda value: value["memoryRecordId"]
    ):
        source_id = record["memoryRecordId"]
        expected_hash = digest(expected_record(record, actors, sessions, strategies))
        mapped_id = record_map.get(source_id)
        if mapped_id:
            existing = destination_records.get(mapped_id)
            if existing is None or digest(record_fields(existing)) != expected_hash:
                raise ValueError(
                    "Manifest record ID does not match destination content"
                )
        else:
            candidates = [
                record_id
                for record_id in available_records.get(expected_hash, [])
                if record_id not in used_record_ids
            ]
            if candidates:
                mapped_id = min(candidates)
                record_map[source_id] = mapped_id
        if mapped_id:
            if mapped_id in used_record_ids:
                raise ValueError("Two source records mapped to one destination record")
            used_record_ids.add(mapped_id)
    if used_record_ids != set(destination_records):
        raise ValueError("Destination has a record not in the source snapshot")


def apply_migration(
    source: Any,
    destination: Any,
    source_id: str,
    destination_id: str,
    original: dict,
    actors: dict[str, str],
    sessions: dict[tuple[str, str], str],
    strategies: dict[str, str],
    *,
    manifest: dict | None = None,
    progress: Any = None,
    resume: bool = False,
    decisions: dict | None = None,
) -> dict:
    ordered = ordered_events(original["events"])
    before = inventory(destination, destination_id, list(strategies.values()))
    if not resume and (before["actors"] or before["events"] or before["records"]):
        raise ValueError("Destination memory is not empty; no writes were started")

    event_map: dict[str, str] = dict(manifest.get("eventIds", {})) if manifest else {}
    record_map: dict[str, str] = dict(manifest.get("recordIds", {})) if manifest else {}
    if resume:
        reconcile_existing(
            original, before, actors, sessions, strategies, event_map, record_map
        )
        if progress:
            progress(event_map, record_map)
    expected_event_hashes = []
    for event in ordered:
        fields = expected_event(event, actors, sessions, event_map)
        expected_event_hashes.append(digest(fields))
        if event["eventId"] in event_map:
            continue
        request = dict(fields)
        request.update(
            memoryId=destination_id,
            extractionMode="SKIP",
            clientToken=deterministic_token(
                "event", destination_id, [event["eventId"]]
            ),
        )
        created = destination.create_event(**request)["event"]
        event_map[event["eventId"]] = created["eventId"]
        if progress:
            progress(event_map, record_map)

    sorted_records = sorted(original["records"], key=lambda r: r["memoryRecordId"])
    expected_record_hashes = []
    for record in sorted_records:
        expected_record_hashes.append(
            digest(expected_record(record, actors, sessions, strategies))
        )
    for batch in batches(
        [r for r in sorted_records if r["memoryRecordId"] not in record_map]
    ):
        inputs = []
        request_to_source = {}
        for record in batch:
            fields = expected_record(record, actors, sessions, strategies)
            identifier = deterministic_token(
                "record", destination_id, [record["memoryRecordId"]]
            )
            request_to_source[identifier] = record["memoryRecordId"]
            inputs.append(
                {
                    "requestIdentifier": identifier,
                    "namespaces": fields["namespaces"],
                    "content": fields["content"],
                    "timestamp": fields["createdAt"],
                    "memoryStrategyId": fields["memoryStrategyId"],
                    **(
                        {"metadata": fields["metadata"]} if "metadata" in fields else {}
                    ),
                }
            )
        response = destination.batch_create_memory_records(
            memoryId=destination_id,
            records=inputs,
            clientToken=deterministic_token(
                "batch", destination_id, [r["memoryRecordId"] for r in batch]
            ),
        )
        for result in response["successfulRecords"]:
            source_record = request_to_source[result["requestIdentifier"]]
            record_map[source_record] = result["memoryRecordId"]
        if progress:
            progress(event_map, record_map)
        if response.get("failedRecords") or len(
            response.get("successfulRecords", [])
        ) != len(batch):
            raise ValueError("AgentCore reported incomplete record creation")

    for attempt in range(12):
        after = inventory(destination, destination_id, list(strategies.values()))
        if (
            after["actors"] == set(actors.values())
            and after["sessions"]
            == {(actors[a], dest) for (a, _), dest in sessions.items()}
            and Counter(digest(event_fields(e)) for e in after["events"])
            == Counter(expected_event_hashes)
            and Counter(digest(record_fields(r)) for r in after["records"])
            == Counter(expected_record_hashes)
        ):
            break
        if attempt == 11:
            raise ValueError("Destination count or canonical content hash differs")
        time.sleep(3)
    if len(event_map) != len(original["events"]) or len(record_map) != len(
        original["records"]
    ):
        raise ValueError("Destination ID mapping is incomplete")
    exception_retrievals = 0
    for entries in (decisions or {}).values():
        for entry in entries:
            actor_id = actors[entry["actorId"]]
            session_id = sessions[(entry["actorId"], entry["sessionId"])]
            retrieved_events = paged(
                destination,
                "list_events",
                "events",
                memoryId=destination_id,
                actorId=actor_id,
                sessionId=session_id,
                includePayloads=True,
            )
            retrieved_summaries = paged(
                destination,
                "list_memory_records",
                "memoryRecordSummaries",
                memoryId=destination_id,
                namespacePath=f"/summaries/{actor_id}/{session_id}/",
            )
            if (
                len(retrieved_events) != entry["events"]
                or len(retrieved_summaries) != entry["summaries"]
            ):
                raise ValueError(
                    "Preserved exception is not retrievable by mapped path"
                )
            exception_retrievals += 1
    return {
        "events": event_map,
        "records": record_map,
        "exceptionRetrievalsVerified": exception_retrievals,
        "verifiedContentSha256": digest(
            {
                "actorIds": sorted(actors.values()),
                "sessionIds": sorted(
                    (actors[a], dest) for (a, _), dest in sessions.items()
                ),
                "eventHashes": sorted(expected_event_hashes),
                "recordHashes": sorted(expected_record_hashes),
            }
        ),
    }
