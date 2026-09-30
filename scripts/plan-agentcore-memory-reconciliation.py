#!/usr/bin/env python3
"""Read-only late AgentCore Memory reconciliation plan; never modifies AWS.

The Memory update/delete APIs have no conditional version. This script flags
safe-looking candidates but deliberately has no apply mode while destination
traffic or managed extraction may update those same records.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from memory_migration_apply import (
    expected_event,
    expected_record,
    read_manifest,
    write_manifest,
)
from memory_migration_inventory import (
    ID_PATTERN,
    digest,
    event_fields,
    inventory,
    record_fields,
    source_snapshot_digest,
    strategy_map,
)


SOURCE_ACCOUNT = "188757775631"
DESTINATION_ACCOUNT = "820323452649"
REGION = "us-east-1"
SOURCE_MEMORY_ID = "HeyTimProduction_HeyTimMemory-xeQPMmBQGC"
DESTINATION_MEMORY_ID = "HeyTim_HeyTimMemory-6ltsOWEt5B"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def private_file(path: Path) -> dict:
    require(path.stat().st_mode & 0o077 == 0, "Private file must have mode 0600")
    result = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(result, dict), "Private file is invalid")
    return result


def read_context(identity_path: Path, manifest_path: Path) -> tuple[dict, dict]:
    root = Path(__file__).resolve().parents[1]
    for path in (identity_path, manifest_path):
        require(not path.resolve().is_relative_to(root), "Private files must be outside repository")
    identity = private_file(identity_path)
    manifest = read_manifest(manifest_path)
    require(manifest.get("status") == "verified", "Initial migration manifest is not verified")
    require(manifest.get("sourceAccount") == SOURCE_ACCOUNT and
            manifest.get("destinationAccount") == DESTINATION_ACCOUNT and
            manifest.get("sourceMemoryId") == SOURCE_MEMORY_ID and
            manifest.get("destinationMemoryId") == DESTINATION_MEMORY_ID,
            "Manifest account or Memory identity mismatch")
    require(identity.get("actors") == manifest.get("actorIds") and
            identity.get("decisions") == manifest.get("preservationDecisions"),
            "Identity map differs from verified migration manifest")
    require(isinstance(identity.get("sessions"), dict) and
            all(isinstance(value, dict) for value in identity["sessions"].values()),
            "Identity session map is invalid")
    sessions = {
        f"{actor}/{session}": target
        for actor, values in identity.get("sessions", {}).items()
        for session, target in values.items()
    }
    require(sessions == manifest.get("sessionIds"), "Session map differs from verified manifest")
    actors = manifest.get("actorIds")
    require(isinstance(actors, dict) and all(ID_PATTERN.fullmatch(value) for value in actors.values()) and
            len(set(actors.values())) == len(actors), "Actor map is invalid")
    require(isinstance(manifest.get("eventIds"), dict) and isinstance(manifest.get("recordIds"), dict) and
            len(set(manifest["eventIds"].values())) == len(manifest["eventIds"]) and
            len(set(manifest["recordIds"].values())) == len(manifest["recordIds"]),
            "Migration ID map is invalid")
    return identity, manifest


def baseline_hashes(manifest: dict, destination: dict, actors: dict,
                    sessions: dict[tuple[str, str], str]) -> dict[str, str]:
    record_map = manifest["recordIds"]
    stored = manifest.get("recordHashes")
    if isinstance(stored, dict):
        require(set(stored) == set(record_map) and
                all(isinstance(value, str) and len(value) == 64 for value in stored.values()),
                "Manifest record baseline is incomplete")
        mapped_events = {event["eventId"]: event for event in destination["events"]}
        require(set(manifest["eventIds"].values()) <= set(mapped_events),
                "Mapped initial events are absent")
        initial_digest = digest({
            "actorIds": sorted(actors.values()),
            "sessionIds": sorted((actors[a], target) for (a, _), target in sessions.items()),
            "eventHashes": sorted(digest(event_fields(mapped_events[destination_id]))
                                  for destination_id in manifest["eventIds"].values()),
            "recordHashes": sorted(stored.values()),
        })
        require(initial_digest == manifest.get("verifiedContentSha256"),
                "Manifest record baseline does not match verified initial digest")
        return stored

    # Older verified manifests have only an aggregate digest. Bootstrap solely
    # while destination still equals that *entire* initial snapshot.
    require({record["memoryRecordId"] for record in destination["records"]} == set(record_map.values()) and
            {event["eventId"] for event in destination["events"]} == set(manifest["eventIds"].values()),
            "Legacy manifest cannot establish a per-record baseline after destination changes")
    record_by_id = {record["memoryRecordId"]: record for record in destination["records"]}
    actual = digest({
        "actorIds": sorted(actors.values()),
        "sessionIds": sorted((actors[a], target) for (a, _), target in sessions.items()),
        "eventHashes": sorted(digest(event_fields(event)) for event in destination["events"]),
        "recordHashes": sorted(digest(record_fields(record)) for record in destination["records"]),
    })
    require(actual == manifest.get("verifiedContentSha256"),
            "Legacy manifest aggregate no longer matches destination")
    return {source_id: digest(record_fields(record_by_id[destination_id]))
            for source_id, destination_id in record_map.items()}


def plan_reconciliation(source: dict, destination: dict, manifest: dict) -> dict:
    actors = manifest["actorIds"]
    sessions = {
        tuple(key.split("/", 1)): value for key, value in manifest["sessionIds"].items()
    }
    require(set(actors) == source["actors"] and set(sessions) == source["sessions"],
            "Source actor or session changed after the identity map was verified")
    event_map = manifest["eventIds"]
    require({event["eventId"] for event in source["events"]} == set(event_map),
            "Source events changed or expired after initial migration")
    dest_events = {event["eventId"]: event for event in destination["events"]}
    for event in source["events"]:
        target = dest_events.get(event_map[event["eventId"]])
        require(target is not None and digest(event_fields(target)) ==
                digest(expected_event(event, actors, sessions, event_map)),
                "Mapped destination event differs from source")
    strategies = manifest["strategyIds"]
    require(isinstance(strategies, dict) and strategies, "Strategy mapping missing")
    baseline = baseline_hashes(manifest, destination, actors, sessions)
    source_records = {record["memoryRecordId"]: record for record in source["records"]}
    destination_records = {record["memoryRecordId"]: record for record in destination["records"]}
    require(len(source_records) == len(source["records"]) and
            len(destination_records) == len(destination["records"]), "Duplicate record IDs")
    record_map = manifest["recordIds"]
    mapped_dest_ids = set(record_map.values())
    extra_hashes = {}
    extra_count = 0
    for record in destination["records"]:
        if record["memoryRecordId"] not in mapped_dest_ids:
            extra_count += 1
            extra_hashes.setdefault(digest(record_fields(record)), 0)
            extra_hashes[digest(record_fields(record))] += 1
    actions = {"create": [], "update": [], "delete": [], "conflict": []}
    already_converged = 0
    for source_id, destination_id in record_map.items():
        current_source = source_records.pop(source_id, None)
        current_dest = destination_records.get(destination_id)
        dest_hash = digest(record_fields(current_dest)) if current_dest else None
        source_hash = digest(expected_record(current_source, actors, sessions, strategies)) if current_source else None
        if current_source is None and current_dest is None:
            already_converged += 1
        elif current_source is None and dest_hash == baseline[source_id]:
            actions["delete"].append({"sourceId": source_id, "destinationId": destination_id,
                                      "expectedDestinationSha256": dest_hash})
        elif current_dest is None:
            actions["conflict"].append({"sourceId": source_id, "reason": "mapped-destination-missing"})
        elif dest_hash == source_hash:
            already_converged += 1
        elif dest_hash == baseline[source_id]:
            actions["update"].append({"sourceId": source_id, "destinationId": destination_id,
                                      "expectedDestinationSha256": dest_hash,
                                      "expectedSourceSha256": source_hash})
        else:
            actions["conflict"].append({"sourceId": source_id, "reason": "destination-diverged"})
    for source_id, record in source_records.items():
        source_hash = digest(expected_record(record, actors, sessions, strategies))
        if extra_hashes.get(source_hash):
            actions["conflict"].append({"sourceId": source_id, "reason": "unmapped-identical-destination"})
        else:
            actions["create"].append({"sourceId": source_id, "expectedSourceSha256": source_hash})
    return {
        "status": "read-only-plan",
        "sourceAccount": SOURCE_ACCOUNT,
        "destinationAccount": DESTINATION_ACCOUNT,
        "sourceMemoryId": SOURCE_MEMORY_ID,
        "destinationMemoryId": DESTINATION_MEMORY_ID,
        "sourceSnapshotSha256": source_snapshot_digest(source),
        "destinationSnapshotSha256": source_snapshot_digest(destination),
        "baselineRecordHashes": baseline,
        "actions": actions,
        "alreadyConverged": already_converged,
        "destinationOnlyRecords": extra_count,
        "strictNoLossProven": False,
    }


def verify_stable_snapshots(source_before: dict, destination_before: dict,
                            source_after: dict, destination_after: dict) -> None:
    require(source_snapshot_digest(source_before) == source_snapshot_digest(source_after),
            "Source changed during planning; retry")
    require(source_snapshot_digest(destination_before) == source_snapshot_digest(destination_after),
            "Destination changed during planning; retry")


def verified_clients(source_profile: str, destination_profile: str) -> tuple[Any, Any, dict]:
    require(source_profile != destination_profile, "Profiles must differ")
    config = Config(retries={"total_max_attempts": 8, "mode": "adaptive"},
                    connect_timeout=5, read_timeout=30)
    clients = []
    memories = []
    for profile, account, memory_id in (
        (source_profile, SOURCE_ACCOUNT, SOURCE_MEMORY_ID),
        (destination_profile, DESTINATION_ACCOUNT, DESTINATION_MEMORY_ID),
    ):
        session = boto3.Session(profile_name=profile, region_name=REGION)
        require(session.client("sts", config=config).get_caller_identity().get("Account") == account,
                "AWS profile resolved to an unexpected account")
        memory = session.client("bedrock-agentcore-control", config=config).get_memory(memoryId=memory_id)["memory"]
        require(memory.get("id") == memory_id and memory.get("status") == "ACTIVE" and
                memory.get("arn") == f"arn:aws:bedrock-agentcore:{REGION}:{account}:memory/{memory_id}",
                "Memory identity or status mismatch")
        memories.append(memory)
        clients.append(session.client("bedrock-agentcore", config=config))
    return clients[0], clients[1], strategy_map(*memories)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-profile", required=True)
    parser.add_argument("--destination-profile", required=True)
    parser.add_argument("--identity-map", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--plan-out", type=Path)
    args = parser.parse_args()
    try:
        if args.plan_out:
            require(not args.plan_out.resolve().is_relative_to(Path(__file__).resolve().parents[1]),
                    "Private plan must be outside repository")
        _, manifest = read_context(args.identity_map, args.manifest)
        source, destination, live_strategies = verified_clients(args.source_profile, args.destination_profile)
        require(live_strategies == manifest["strategyIds"], "Memory strategy mapping changed")
        source_before = copy.deepcopy(inventory(source, SOURCE_MEMORY_ID, list(live_strategies)))
        destination_before = copy.deepcopy(inventory(destination, DESTINATION_MEMORY_ID, list(live_strategies.values())))
        result = plan_reconciliation(source_before, destination_before, manifest)
        source_after = inventory(source, SOURCE_MEMORY_ID, list(live_strategies))
        destination_after = inventory(destination, DESTINATION_MEMORY_ID, list(live_strategies.values()))
        verify_stable_snapshots(source_before, destination_before, source_after, destination_after)
        if args.plan_out:
            write_manifest(args.plan_out, result)
        print(json.dumps({
            "status": result["status"],
            "create": len(result["actions"]["create"]),
            "update": len(result["actions"]["update"]),
            "delete": len(result["actions"]["delete"]),
            "conflict": len(result["actions"]["conflict"]),
            "alreadyConverged": result["alreadyConverged"],
            "strictNoLossProven": False,
        }, sort_keys=True))
        return 0 if not result["actions"]["conflict"] else 2
    except (ValueError, TypeError, KeyError, OSError, BotoCoreError, ClientError) as error:
        print(f"Memory reconciliation planning stopped: {type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
