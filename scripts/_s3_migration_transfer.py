"""Private version transfer, reconciliation, and verification helpers."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode

if __package__:
    from ._s3_migration_plan import (
        CHUNK_SIZE,
        COPY_FIELDS,
        MigrationError,
        assert_destination_is_owned,
        destination_versions,
        write_private_json,
    )
else:
    from _s3_migration_plan import (
        CHUNK_SIZE,
        COPY_FIELDS,
        MigrationError,
        assert_destination_is_owned,
        destination_versions,
        write_private_json,
    )


def object_settings(
    source: Any, bucket: str, account: str, operation: dict[str, Any]
) -> dict[str, Any]:
    selector = {
        "Bucket": bucket,
        "Key": operation["sourceKey"],
        "VersionId": operation["sourceVersionId"],
        "ExpectedBucketOwner": account,
    }
    head = source.head_object(**selector)
    if head["ContentLength"] != operation["size"]:
        raise MigrationError("Source object size changed during migration.")
    if head.get("ObjectLockMode") or head.get("ObjectLockLegalHoldStatus"):
        raise MigrationError("Object Lock state needs an explicit migration plan.")
    tags = source.get_object_tagging(**selector).get("TagSet", [])
    settings = {field: head[field] for field in COPY_FIELDS if field in head}
    settings["Metadata"] = head.get("Metadata", {})
    if tags:
        settings["Tagging"] = urlencode(
            sorted((tag["Key"], tag["Value"]) for tag in tags)
        )
    return settings


def verify_recovery_settings(
    source: Any,
    destination: Any,
    operation: dict[str, Any],
    scope: dict[str, Any],
    version_id: str,
) -> None:
    settings = object_settings(
        source, scope["sourceBucket"], scope["sourceAccount"], operation
    )
    selector = {
        "Bucket": scope["destinationBucket"],
        "Key": operation["destinationKey"],
        "VersionId": version_id,
        "ExpectedBucketOwner": scope["destinationAccount"],
    }
    head = destination.head_object(**selector)
    if (
        head.get("ServerSideEncryption") != "aws:kms"
        or head.get("SSEKMSKeyId") != scope["destinationKmsKey"]
        or head.get("ContentLength") != operation["size"]
        or head.get("Metadata", {}) != settings["Metadata"]
    ):
        raise MigrationError(
            "Pending destination version has different encryption, size, or metadata."
        )
    for field in COPY_FIELDS:
        if head.get(field) != settings.get(field):
            raise MigrationError(
                "Pending destination version has different content settings."
            )
    source_tags = sorted(parse_qsl(settings.get("Tagging", ""), keep_blank_values=True))
    destination_tags = sorted(
        (tag["Key"], tag["Value"])
        for tag in destination.get_object_tagging(**selector).get("TagSet", [])
    )
    if source_tags != destination_tags:
        raise MigrationError("Pending destination version has different object tags.")


def stream_hash(
    client: Any, bucket: str, key: str, version_id: str, account: str
) -> tuple[str, int]:
    response = client.get_object(
        Bucket=bucket, Key=key, VersionId=version_id, ExpectedBucketOwner=account
    )
    digest = hashlib.sha256()
    size = 0
    with response["Body"] as body:
        while True:
            block = body.read(CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def copy_version(
    source: Any,
    destination: Any,
    operation: dict[str, Any],
    source_bucket: str,
    source_account: str,
    destination_bucket: str,
    destination_account: str,
    kms_key: str,
) -> tuple[str, str]:
    settings = object_settings(source, source_bucket, source_account, operation)
    settings.update(ServerSideEncryption="aws:kms", SSEKMSKeyId=kms_key)
    selector = {
        "Bucket": source_bucket,
        "Key": operation["sourceKey"],
        "VersionId": operation["sourceVersionId"],
        "ExpectedBucketOwner": source_account,
    }
    response = source.get_object(**selector)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        if operation["size"] <= CHUNK_SIZE:
            payload = body.read(CHUNK_SIZE + 1)
            if len(payload) != operation["size"]:
                raise MigrationError("Source object length changed during copy.")
            digest.update(payload)
            size = len(payload)
            uploaded = destination.put_object(
                Bucket=destination_bucket,
                Key=operation["destinationKey"],
                Body=payload,
                ExpectedBucketOwner=destination_account,
                **settings,
            )
        else:
            created = destination.create_multipart_upload(
                Bucket=destination_bucket,
                Key=operation["destinationKey"],
                ExpectedBucketOwner=destination_account,
                **settings,
            )
            upload_id = created["UploadId"]
            parts = []
            try:
                part_number = 1
                while True:
                    block = body.read(CHUNK_SIZE)
                    if not block:
                        break
                    size += len(block)
                    digest.update(block)
                    part = destination.upload_part(
                        Bucket=destination_bucket,
                        Key=operation["destinationKey"],
                        UploadId=upload_id,
                        PartNumber=part_number,
                        Body=block,
                        ExpectedBucketOwner=destination_account,
                    )
                    parts.append({"PartNumber": part_number, "ETag": part["ETag"]})
                    part_number += 1
                if size != operation["size"]:
                    raise MigrationError(
                        "Source object length changed during multipart copy."
                    )
                uploaded = destination.complete_multipart_upload(
                    Bucket=destination_bucket,
                    Key=operation["destinationKey"],
                    UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                    ExpectedBucketOwner=destination_account,
                )
            except Exception:
                destination.abort_multipart_upload(
                    Bucket=destination_bucket,
                    Key=operation["destinationKey"],
                    UploadId=upload_id,
                    ExpectedBucketOwner=destination_account,
                )
                raise
    finally:
        body.close()
    version_id = uploaded.get("VersionId")
    if not version_id or version_id == "null":
        raise MigrationError("Destination did not return a durable version ID.")
    destination_hash, destination_size = stream_hash(
        destination,
        destination_bucket,
        operation["destinationKey"],
        version_id,
        destination_account,
    )
    if (digest.hexdigest(), size) != (destination_hash, destination_size):
        raise MigrationError("Destination content SHA-256 or size differs from source.")
    verify_recovery_settings(
        source,
        destination,
        operation,
        {
            "sourceBucket": source_bucket,
            "sourceAccount": source_account,
            "destinationBucket": destination_bucket,
            "destinationAccount": destination_account,
            "destinationKmsKey": kms_key,
        },
        version_id,
    )
    return version_id, destination_hash


def version_map(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": 1,
        "scope": plan["scope"],
        "versions": [
            {
                "sourceKey": op["sourceKey"],
                "sourceVersionId": op["sourceVersionId"],
                "destinationKey": op["destinationKey"],
                "destinationVersionId": op["destinationVersionId"],
                "deleteMarker": op["deleteMarker"],
                **({"sha256": op["sha256"]} if not op["deleteMarker"] else {}),
            }
            for op in plan["operations"]
            if op["state"] == "done"
        ],
    }


def reconcile_pending(
    plan: dict[str, Any],
    source: Any,
    destination: Any,
    manifest_path: Path,
    map_path: Path,
    adopt_version_id: str | None,
) -> None:
    """Recover one interrupted operation without creating another version."""
    pending = [op for op in plan["operations"] if op["state"] == "pending"]
    if not pending:
        if adopt_version_id:
            raise MigrationError("No pending operation exists to adopt.")
        return
    if len(pending) != 1:
        raise MigrationError("Only one operation may be pending.")
    operation = pending[0]
    scope = plan["scope"]
    actual = destination_versions(
        destination,
        scope["destinationBucket"],
        scope["destinationAccount"],
        {operation["destinationKey"]},
    )[operation["destinationKey"]]
    completed = {
        op["destinationVersionId"]
        for op in plan["operations"]
        if op["state"] == "done" and op["destinationKey"] == operation["destinationKey"]
    }
    unknown = [item for item in actual if item["versionId"] not in completed]
    if not unknown:
        if adopt_version_id:
            raise MigrationError("No unrecorded destination version exists to adopt.")
        operation["state"] = "planned"
        write_private_json(manifest_path, plan)
        return
    if (
        len(unknown) != 1
        or not adopt_version_id
        or unknown[0]["versionId"] != adopt_version_id
    ):
        raise MigrationError(
            "Pending write has unrecorded destination history. Review it and pass "
            "the exact --adopt-pending-version-id only if it is the single expected version."
        )
    candidate = unknown[0]
    if (
        not candidate["isLatest"]
        or candidate["deleteMarker"] != operation["deleteMarker"]
    ):
        raise MigrationError(
            "Pending destination version is not the expected latest type."
        )
    if operation["deleteMarker"]:
        digest = None
    else:
        source_hash, source_size = stream_hash(
            source,
            scope["sourceBucket"],
            operation["sourceKey"],
            operation["sourceVersionId"],
            scope["sourceAccount"],
        )
        destination_hash, destination_size = stream_hash(
            destination,
            scope["destinationBucket"],
            operation["destinationKey"],
            candidate["versionId"],
            scope["destinationAccount"],
        )
        if (source_hash, source_size) != (destination_hash, destination_size):
            raise MigrationError(
                "Pending destination body does not match source SHA-256 and size."
            )
        verify_recovery_settings(
            source, destination, operation, scope, candidate["versionId"]
        )
        digest = source_hash
    operation["destinationVersionId"] = candidate["versionId"]
    if digest is not None:
        operation["sha256"] = digest
    operation["state"] = "done"
    write_private_json(manifest_path, plan)
    write_private_json(map_path, version_map(plan))


def verify_complete(
    plan: dict[str, Any], source: Any, destination: Any
) -> dict[str, int]:
    operations = plan["operations"]
    if any(op["state"] != "done" for op in operations):
        raise MigrationError("Migration is incomplete.")
    scope = plan["scope"]
    keys = {op["destinationKey"] for op in operations}
    versions = destination_versions(
        destination, scope["destinationBucket"], scope["destinationAccount"], keys
    )
    assert_destination_is_owned(plan, versions)
    expected_bytes = sum(op["size"] for op in operations)
    actual_bytes = sum(item["size"] for values in versions.values() for item in values)
    if expected_bytes != actual_bytes:
        raise MigrationError("Destination total version bytes differ from source.")
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for op in operations:
        by_key[op["destinationKey"]].append(op)
    for key, history in by_key.items():
        latest = [item for item in versions[key] if item["isLatest"]]
        if (
            len(latest) != 1
            or latest[0]["versionId"] != history[-1]["destinationVersionId"]
        ):
            raise MigrationError(
                "Destination current object state does not match source history."
            )
    for op in operations:
        if not op["deleteMarker"]:
            digest, size = stream_hash(
                destination,
                scope["destinationBucket"],
                op["destinationKey"],
                op["destinationVersionId"],
                scope["destinationAccount"],
            )
            if digest != op["sha256"] or size != op["size"]:
                raise MigrationError(
                    "A destination version failed final content SHA-256 verification."
                )
            verify_recovery_settings(
                source,
                destination,
                op,
                scope,
                op["destinationVersionId"],
            )
    return {
        "versions": sum(not op["deleteMarker"] for op in operations),
        "deleteMarkers": sum(op["deleteMarker"] for op in operations),
        "bytes": expected_bytes,
        "currentObjects": sum(
            not history[-1]["deleteMarker"] for history in by_key.values()
        ),
    }


def execute(
    plan: dict[str, Any],
    source: Any,
    destination: Any,
    manifest_path: Path,
    map_path: Path,
    adopt_pending_version_id: str | None = None,
) -> dict[str, int]:
    scope = plan["scope"]
    reconcile_pending(
        plan, source, destination, manifest_path, map_path, adopt_pending_version_id
    )
    keys = {op["destinationKey"] for op in plan["operations"]}
    assert_destination_is_owned(
        plan,
        destination_versions(
            destination, scope["destinationBucket"], scope["destinationAccount"], keys
        ),
    )
    for op in plan["operations"]:
        if op["state"] == "done":
            continue
        op["state"] = "pending"
        write_private_json(manifest_path, plan)
        if op["deleteMarker"]:
            result = destination.delete_object(
                Bucket=scope["destinationBucket"],
                Key=op["destinationKey"],
                ExpectedBucketOwner=scope["destinationAccount"],
            )
            if not result.get("DeleteMarker"):
                raise MigrationError("Destination did not create a delete marker.")
            version_id = result.get("VersionId")
            sha256 = None
        else:
            version_id, sha256 = copy_version(
                source,
                destination,
                op,
                scope["sourceBucket"],
                scope["sourceAccount"],
                scope["destinationBucket"],
                scope["destinationAccount"],
                scope["destinationKmsKey"],
            )
        if not version_id or version_id == "null":
            raise MigrationError("Destination did not return a durable version ID.")
        op["destinationVersionId"] = version_id
        if sha256 is not None:
            op["sha256"] = sha256
        op["state"] = "done"
        write_private_json(manifest_path, plan)
        write_private_json(map_path, version_map(plan))
    return verify_complete(plan, source, destination)
