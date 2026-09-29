#!/usr/bin/env python3
"""Guarded, version-preserving S3 migration between distinct AWS accounts.

Inventory and plan are read-only by default. An explicit --apply replays each
source key's versions and delete markers into a versioned destination bucket.
Object bodies are streamed through memory and never written to local disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__:
    from ._s3_migration_plan import (
        ACCOUNT_ID,
        CHUNK_SIZE,
        KMS_ARN,
        MigrationError,
        assert_destination_is_owned,
        canonical_hash,
        check_resume,
        destination_key,
        destination_versions,
        inventory,
        load_exact_keys,
        load_key_map,
        load_private_json,
        make_plan,
        reviewed_plan,
        validate_user_actor_mappings,
        write_private_json,
    )
    from ._s3_migration_transfer import (
        copy_version,
        execute,
        object_settings,
        reconcile_pending,
        stream_hash,
        verify_complete,
        verify_recovery_settings,
        version_map,
    )
    from .memory_migration_inventory import verified_cognito_users
else:
    from _s3_migration_plan import (
        ACCOUNT_ID,
        CHUNK_SIZE,
        KMS_ARN,
        MigrationError,
        assert_destination_is_owned,
        canonical_hash,
        check_resume,
        destination_key,
        destination_versions,
        inventory,
        load_exact_keys,
        load_key_map,
        load_private_json,
        make_plan,
        reviewed_plan,
        validate_user_actor_mappings,
        write_private_json,
    )
    from _s3_migration_transfer import (
        copy_version,
        execute,
        object_settings,
        reconcile_pending,
        stream_hash,
        verify_complete,
        verify_recovery_settings,
        version_map,
    )
    from memory_migration_inventory import verified_cognito_users

# Preserve the import surface used by the focused offline safety tests.
__all__ = [
    "CHUNK_SIZE",
    "MigrationError",
    "assert_destination_is_owned",
    "canonical_hash",
    "check_resume",
    "copy_version",
    "destination_key",
    "destination_versions",
    "execute",
    "inventory",
    "load_exact_keys",
    "load_key_map",
    "load_private_json",
    "make_plan",
    "object_settings",
    "reconcile_pending",
    "reviewed_plan",
    "stream_hash",
    "validate_user_actor_mappings",
    "verify_complete",
    "verify_recovery_settings",
    "version_map",
    "write_private_json",
]


def verify_identity(session: Any, expected_account: str, label: str) -> None:
    actual = session.client("sts").get_caller_identity()["Account"]
    if actual != expected_account:
        raise MigrationError(f"{label} AWS profile is not the specified account.")


def verify_buckets_and_key(
    source: Any,
    destination: Any,
    kms: Any,
    scope: dict[str, Any],
) -> None:
    for label, client, bucket, account in (
        ("Source", source, scope["sourceBucket"], scope["sourceAccount"]),
        (
            "Destination",
            destination,
            scope["destinationBucket"],
            scope["destinationAccount"],
        ),
    ):
        client.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
        state = client.get_bucket_versioning(Bucket=bucket, ExpectedBucketOwner=account)
        if state.get("Status") != "Enabled":
            raise MigrationError(f"{label} bucket versioning is not enabled.")
    key = kms.describe_key(KeyId=scope["destinationKmsKey"])["KeyMetadata"]
    if (
        key.get("Arn") != scope["destinationKmsKey"]
        or key.get("AWSAccountId") != scope["destinationAccount"]
        or key.get("KeyState") != "Enabled"
        or key.get("KeyManager") != "CUSTOMER"
    ):
        raise MigrationError(
            "Destination KMS key is not an enabled destination-owned customer key."
        )
    encryption = destination.get_bucket_encryption(
        Bucket=scope["destinationBucket"],
        ExpectedBucketOwner=scope["destinationAccount"],
    )
    rules = encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
    defaults = [rule.get("ApplyServerSideEncryptionByDefault", {}) for rule in rules]
    configured_keys = [
        item["KMSMasterKeyID"]
        for item in defaults
        if item.get("SSEAlgorithm") == "aws:kms" and item.get("KMSMasterKeyID")
    ]
    if not any(
        kms.describe_key(KeyId=key_id)["KeyMetadata"]["Arn"]
        == scope["destinationKmsKey"]
        for key_id in configured_keys
    ):
        raise MigrationError(
            "Destination bucket default encryption does not use the specified KMS key."
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "destination"):
        result.add_argument(f"--{name}-profile", required=True)
        result.add_argument(f"--{name}-account", required=True)
        result.add_argument(f"--{name}-bucket", required=True)
    result.add_argument(
        "--destination-kms-key", required=True, help="Full destination KMS key ARN"
    )
    result.add_argument("--region", required=True)
    result.add_argument("--source-user-pool-id")
    result.add_argument("--destination-user-pool-id")
    selection = result.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--prefix", action="append", help="Repeat for each selected source prefix"
    )
    selection.add_argument(
        "--exact-key-file",
        type=Path,
        help="Private 0600 JSON array of exact source keys",
    )
    selection.add_argument(
        "--all-keys",
        action="store_true",
        help="Select all source keys for archival migration",
    )
    result.add_argument(
        "--key-map-file",
        type=Path,
        help="JSON array of sourcePrefix/destinationPrefix pairs",
    )
    result.add_argument(
        "--archive-prefix",
        help="Explicit destination archival prefix, such as migration-archive/legacy/",
    )
    result.add_argument("--manifest", type=Path, required=True)
    result.add_argument(
        "--version-map",
        type=Path,
        help="Default: manifest with .version-map.json suffix",
    )
    result.add_argument(
        "--apply", action="store_true", help="Enable destination writes"
    )
    result.add_argument(
        "--adopt-pending-version-id",
        help="Explicitly reconcile one reviewed version left by an interrupted apply",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if not ACCOUNT_ID.fullmatch(args.source_account) or not ACCOUNT_ID.fullmatch(
            args.destination_account
        ):
            raise MigrationError("Expected AWS accounts must be twelve-digit IDs.")
        if args.source_account == args.destination_account:
            raise MigrationError("Source and destination accounts must differ.")
        key_match = KMS_ARN.fullmatch(args.destination_kms_key)
        if (
            not key_match
            or key_match.group(1) != args.region
            or key_match.group(2) != args.destination_account
        ):
            raise MigrationError(
                "Destination KMS key ARN must match region and destination account."
            )
        if any(not selector for selector in (args.prefix or [])):
            raise MigrationError("Source selectors must be nonempty.")
        if args.archive_prefix and (
            not args.archive_prefix.startswith("migration-archive/")
            or not args.archive_prefix.endswith("/")
        ):
            raise MigrationError(
                "Archive prefix must live under migration-archive/ and end in '/'."
            )
        if args.all_keys and not args.archive_prefix:
            raise MigrationError("--all-keys requires an archival destination prefix.")
        if args.archive_prefix and args.key_map_file:
            raise MigrationError(
                "Archive prefix and user key remap cannot be combined."
            )
        if args.adopt_pending_version_id and not args.apply:
            raise MigrationError("Pending-version adoption requires --apply.")
        if args.source_bucket == args.destination_bucket:
            raise MigrationError("Source and destination buckets must differ.")
        if args.source_profile == args.destination_profile:
            raise MigrationError("Source and destination AWS profiles must differ.")
        repository = Path(__file__).resolve().parents[1]
        map_path = args.version_map or args.manifest.with_suffix(".version-map.json")
        for path in (args.manifest, map_path, args.key_map_file, args.exact_key_file):
            if path is not None and path.resolve().is_relative_to(repository):
                raise MigrationError(
                    "Migration manifests and key maps must be outside the repository."
                )
        mappings = load_key_map(args.key_map_file)
        exact_keys = load_exact_keys(args.exact_key_file)
        scope = {
            "sourceAccount": args.source_account,
            "sourceBucket": args.source_bucket,
            "destinationAccount": args.destination_account,
            "destinationBucket": args.destination_bucket,
            "destinationKmsKey": args.destination_kms_key,
            "region": args.region,
            "prefixes": [""] if args.all_keys else sorted(set(args.prefix or [])),
            "exactKeys": exact_keys,
            "keyMap": mappings,
            "archivePrefix": args.archive_prefix or "",
        }
        # Import here so pure planning and checkpoint tests run without AWS SDK.
        import boto3
        from botocore.config import Config

        config = Config(
            retries={"mode": "adaptive", "total_max_attempts": 5}, read_timeout=120
        )
        source_session = boto3.Session(
            profile_name=args.source_profile, region_name=args.region
        )
        destination_session = boto3.Session(
            profile_name=args.destination_profile, region_name=args.region
        )
        verify_identity(source_session, args.source_account, "Source")
        verify_identity(destination_session, args.destination_account, "Destination")
        source = source_session.client("s3", config=config)
        destination = destination_session.client("s3", config=config)
        verify_buckets_and_key(
            source, destination, destination_session.client("kms", config=config), scope
        )
        source_inventory = inventory(
            source,
            args.source_bucket,
            args.source_account,
            scope["prefixes"],
            scope["exactKeys"],
        )
        planned = make_plan(source_inventory, scope, mappings)
        if (
            any(item["sourceKey"].startswith("users/") for item in source_inventory)
            and not args.archive_prefix
        ):
            if not args.source_user_pool_id or not args.destination_user_pool_id:
                raise MigrationError(
                    "Application-visible user files require both Cognito user pool IDs."
                )
            source_users = verified_cognito_users(
                source_session.client("cognito-idp", config=config),
                args.source_user_pool_id,
                args.source_account,
                args.region,
            )
            destination_users = verified_cognito_users(
                destination_session.client("cognito-idp", config=config),
                args.destination_user_pool_id,
                args.destination_account,
                args.region,
            )
            validate_user_actor_mappings(
                source_inventory, mappings, source_users, destination_users
            )
        plan = reviewed_plan(args.manifest, planned, apply=args.apply)
        if not args.apply:
            assert_destination_is_owned(
                plan,
                destination_versions(
                    destination,
                    scope["destinationBucket"],
                    scope["destinationAccount"],
                    {op["destinationKey"] for op in plan["operations"]},
                ),
            )
        # Complete metadata/tag access checks before the first destination write.
        for operation in plan["operations"]:
            if not operation["deleteMarker"]:
                object_settings(
                    source, scope["sourceBucket"], scope["sourceAccount"], operation
                )
        write_private_json(args.manifest, plan)
        if not args.apply:
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "keys": len({op["sourceKey"] for op in plan["operations"]}),
                        "versions": sum(
                            not op["deleteMarker"] for op in plan["operations"]
                        ),
                        "deleteMarkers": sum(
                            op["deleteMarker"] for op in plan["operations"]
                        ),
                        "bytes": sum(op["size"] for op in plan["operations"]),
                        "manifest": str(args.manifest),
                    },
                    sort_keys=True,
                )
            )
            return 0
        result = execute(
            plan,
            source,
            destination,
            args.manifest,
            map_path,
            args.adopt_pending_version_id,
        )
        if canonical_hash(source_inventory) != canonical_hash(
            inventory(
                source,
                args.source_bucket,
                args.source_account,
                scope["prefixes"],
                scope["exactKeys"],
            )
        ):
            raise MigrationError(
                "Source inventory changed during migration; do not cut over."
            )
        print(
            json.dumps(
                {"mode": "applied", **result, "versionMap": str(map_path)},
                sort_keys=True,
            )
        )
        return 0
    except (MigrationError, OSError, ValueError) as error:
        print(f"S3 migration stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
