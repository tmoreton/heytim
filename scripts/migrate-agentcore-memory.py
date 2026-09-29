#!/usr/bin/env python3
"""Inventory and migrate AgentCore Memory without writing customer payloads to disk.

Run a dry run first. Apply requires an exhaustive, identifier-only identity map and
the source digest from that dry run. Keep writes frozen during apply. The manifest
contains IDs and hashes, never event payloads or memory record content.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from memory_migration_apply import (
    apply_migration,
    batches,
    deterministic_token,
    expected_event,
    expected_record,
    mapped_namespace,
    migration_manifest,
    ordered_events,
    read_manifest,
    reconcile_existing,
    replace_manifest,
    validate_payload_shapes,
    write_manifest,
)
from memory_migration_inventory import (
    canonical,
    derive_identity_map,
    digest,
    event_fields,
    hashed_identity,
    inventory,
    paged,
    read_identity_map,
    record_fields,
    source_key_inventory,
    source_snapshot_digest,
    strategy_map,
    validate_identity_map,
    verified_cognito_users,
)

__all__ = [
    "apply_migration",
    "batches",
    "canonical",
    "derive_identity_map",
    "deterministic_token",
    "digest",
    "event_fields",
    "expected_event",
    "expected_record",
    "generated_identity_map",
    "hashed_identity",
    "inventory",
    "main",
    "mapped_namespace",
    "migration_manifest",
    "ordered_events",
    "paged",
    "read_identity_map",
    "read_manifest",
    "reconcile_existing",
    "record_fields",
    "replace_manifest",
    "source_key_inventory",
    "source_snapshot_digest",
    "strategy_map",
    "validate_identity_map",
    "validate_live_identity_map",
    "validate_payload_shapes",
    "verified_clients",
    "verified_cognito_users",
    "write_manifest",
]


def verified_clients(args: argparse.Namespace) -> tuple[Any, Any, dict[str, str]]:
    if (
        args.source_profile == args.destination_profile
        or args.source_account == args.destination_account
    ):
        raise ValueError("Source and destination accounts/profiles must differ")
    config = Config(
        retries={"total_max_attempts": 8, "mode": "adaptive"},
        connect_timeout=5,
        read_timeout=30,
    )
    clients = []
    memory_details = []
    for profile, account, memory_id in (
        (args.source_profile, args.source_account, args.source_memory_id),
        (
            args.destination_profile,
            args.destination_account,
            args.destination_memory_id,
        ),
    ):
        session = boto3.Session(profile_name=profile, region_name=args.region)
        identity = session.client("sts", config=config).get_caller_identity()
        if identity.get("Account") != account:
            raise ValueError("AWS profile resolved to an unexpected account")
        control = session.client("bedrock-agentcore-control", config=config)
        memory = control.get_memory(memoryId=memory_id)["memory"]
        if memory.get("id") != memory_id or memory.get("status") != "ACTIVE":
            raise ValueError("Memory ID or status differs from the expected target")
        expected_arn_prefix = (
            f"arn:aws:bedrock-agentcore:{args.region}:{account}:memory/"
        )
        if not memory.get("arn", "").startswith(expected_arn_prefix):
            raise ValueError(
                "Memory ARN does not belong to the expected region/account"
            )
        clients.append(session.client("bedrock-agentcore", config=config))
        memory_details.append(memory)
    return clients[0], clients[1], strategy_map(*memory_details)


def generated_identity_map(args: argparse.Namespace, data: dict) -> dict:
    source_session = boto3.Session(
        profile_name=args.source_profile, region_name=args.region
    )
    destination_session = boto3.Session(
        profile_name=args.destination_profile, region_name=args.region
    )
    source_users = verified_cognito_users(
        source_session.client("cognito-idp"),
        args.source_user_pool_id,
        args.source_account,
        args.region,
    )
    destination_users = verified_cognito_users(
        destination_session.client("cognito-idp"),
        args.destination_user_pool_id,
        args.destination_account,
        args.region,
    )
    # The resource's client unmarshals projected DynamoDB keys to native strings.
    dynamodb = source_session.resource("dynamodb").meta.client
    keys = source_key_inventory(
        dynamodb, args.source_table_name, args.source_account, args.region
    )
    return derive_identity_map(
        source_users,
        destination_users,
        keys,
        data,
        expected_orphans=args.expect_orphan_actors,
        expected_historical_sessions=args.expect_historical_sessions,
    )


def validate_live_identity_map(
    args: argparse.Namespace,
    data: dict,
    actors: dict[str, str],
    sessions: dict[tuple[str, str], str],
    decisions: dict,
) -> None:
    """Reject a private map that no longer matches verified live identities."""
    regenerated = validate_identity_map(generated_identity_map(args, data), data)
    if regenerated != (actors, sessions, decisions):
        raise ValueError(
            "Identity map differs from verified Cognito and DynamoDB ownership"
        )


def require_outside_repository(path: Path) -> None:
    if path.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise ValueError(
            "Private identity and manifest paths must be outside the repository"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-profile", required=True)
    parser.add_argument("--source-account", required=True)
    parser.add_argument("--source-memory-id", required=True)
    parser.add_argument("--destination-profile", required=True)
    parser.add_argument("--destination-account", required=True)
    parser.add_argument("--destination-memory-id", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--identity-map", type=Path)
    parser.add_argument("--generate-identity-map", type=Path)
    parser.add_argument("--source-user-pool-id")
    parser.add_argument("--destination-user-pool-id")
    parser.add_argument("--source-table-name")
    parser.add_argument("--expect-orphan-actors", type=int, default=0)
    parser.add_argument("--expect-historical-sessions", type=int, default=0)
    parser.add_argument("--expect-source-digest")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Write to the destination memory"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume an existing identifier manifest"
    )
    args = parser.parse_args()
    for account in (args.source_account, args.destination_account):
        if not re.fullmatch(r"[0-9]{12}", account):
            parser.error("Account IDs must be 12 digits")
    if args.apply and (
        not args.identity_map or not args.expect_source_digest or not args.manifest
    ):
        parser.error(
            "--apply requires --identity-map, --expect-source-digest, and --manifest"
        )
    if args.apply and (
        not args.source_user_pool_id
        or not args.destination_user_pool_id
        or not args.source_table_name
    ):
        parser.error(
            "--apply requires both Cognito user pool IDs and the source table name"
        )
    if args.resume and not args.apply:
        parser.error("--resume requires --apply")
    if args.generate_identity_map and (
        args.identity_map
        or args.apply
        or args.manifest
        or not args.source_user_pool_id
        or not args.destination_user_pool_id
        or not args.source_table_name
    ):
        parser.error(
            "Map generation needs both user pool IDs and the source table name"
        )
    if args.expect_orphan_actors not in {0, 1} or args.expect_historical_sessions < 0:
        parser.error(
            "Preservation exception counts must be nonnegative and at most one orphan"
        )
    return args


def main() -> int:
    args = parse_args()
    try:
        for path in (args.identity_map, args.generate_identity_map, args.manifest):
            if path:
                require_outside_repository(path)
        source, destination, strategies = verified_clients(args)
        original = inventory(source, args.source_memory_id, list(strategies))
        validate_payload_shapes(
            destination, args.destination_memory_id, original, strategies
        )
        snapshot = source_snapshot_digest(original)
        actors = {}
        sessions = {}
        decisions = {
            "orphanPreservedUnmapped": [],
            "historicalSessionsPreservedUnmapped": [],
        }
        if args.identity_map:
            actors, sessions, decisions = read_identity_map(args.identity_map, original)
            for record in original["records"]:
                expected_record(record, actors, sessions, strategies)
        elif args.generate_identity_map:
            raw = generated_identity_map(args, original)
            actors, sessions, decisions = validate_identity_map(raw, original)
            write_manifest(args.generate_identity_map, raw)
        if (
            len(decisions["orphanPreservedUnmapped"]) != args.expect_orphan_actors
            or len(decisions["historicalSessionsPreservedUnmapped"])
            != args.expect_historical_sessions
        ):
            raise ValueError("Preservation exception counts differ from command flags")
        destination_before = inventory(
            destination, args.destination_memory_id, list(strategies.values())
        )
        report = {
            "source": {
                "actors": len(original["actors"]),
                "sessions": len(original["sessions"]),
                "events": len(original["events"]),
                "records": len(original["records"]),
                "snapshotSha256": snapshot,
            },
            "destinationBefore": {
                "actors": len(destination_before["actors"]),
                "sessions": len(destination_before["sessions"]),
                "events": len(destination_before["events"]),
                "records": len(destination_before["records"]),
            },
            "strategyIds": strategies,
            "status": "dry-run",
        }
        if args.identity_map or args.generate_identity_map:
            report["mappedActors"] = len(actors)
            report["mappedSessions"] = len(sessions)
            report["orphanPreservedUnmapped"] = len(
                decisions["orphanPreservedUnmapped"]
            )
            report["historicalSessionsPreservedUnmapped"] = len(
                decisions["historicalSessionsPreservedUnmapped"]
            )
        if args.generate_identity_map:
            report["status"] = "identity-map-generated"
        if args.apply:
            validate_live_identity_map(args, original, actors, sessions, decisions)
            if snapshot != args.expect_source_digest:
                raise ValueError(
                    "Source snapshot changed since dry run; no writes were started"
                )
            expected_manifest = migration_manifest(
                args, snapshot, actors, sessions, strategies, decisions
            )
            if args.resume:
                manifest = read_manifest(args.manifest)
                for key, value in expected_manifest.items():
                    if key in {"status", "eventIds", "recordIds"}:
                        continue
                    if manifest.get(key) != value:
                        raise ValueError(
                            "Resume manifest does not match accounts, IDs, map, or snapshot"
                        )
                if manifest.get("status") not in {"in-progress", "verified"}:
                    raise ValueError("Resume manifest has an invalid status")
                if not isinstance(manifest.get("eventIds"), dict) or not isinstance(
                    manifest.get("recordIds"), dict
                ):
                    raise ValueError("Resume manifest has invalid ID maps")
            else:
                if (
                    destination_before["actors"]
                    or destination_before["events"]
                    or destination_before["records"]
                ):
                    raise ValueError(
                        "Destination memory is not empty; no writes were started"
                    )
                manifest = expected_manifest
                write_manifest(args.manifest, manifest)

            def progress(event_ids: dict[str, str], record_ids: dict[str, str]) -> None:
                manifest["eventIds"] = dict(event_ids)
                manifest["recordIds"] = dict(record_ids)
                replace_manifest(args.manifest, manifest)

            mappings = apply_migration(
                source,
                destination,
                args.source_memory_id,
                args.destination_memory_id,
                original,
                actors,
                sessions,
                strategies,
                manifest=manifest,
                progress=progress,
                resume=args.resume,
                decisions=decisions,
            )
            if (
                source_snapshot_digest(
                    inventory(source, args.source_memory_id, list(strategies))
                )
                != snapshot
            ):
                raise ValueError("Source changed during migration; keep traffic frozen")
            report["status"] = "verified"
            report["destinationAfter"] = {
                "actors": len(actors),
                "sessions": len(sessions),
                "events": len(mappings["events"]),
                "records": len(mappings["records"]),
                "verifiedContentSha256": mappings["verifiedContentSha256"],
                "exceptionRetrievalsVerified": mappings["exceptionRetrievalsVerified"],
            }
            progress(mappings["events"], mappings["records"])
            manifest["verifiedContentSha256"] = mappings["verifiedContentSha256"]
            manifest["status"] = "verified"
            replace_manifest(args.manifest, manifest)
        elif args.manifest:
            write_manifest(args.manifest, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        BotoCoreError,
        ClientError,
    ) as error:
        # SDK error strings can include request details. Never print their payloads.
        print(f"Memory migration stopped: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
