"""Inventory and explicitly tag historical transient result versions for expiry.

Dry-run writes a private manifest. Apply requires that same manifest and its
reviewed to-tag count; it never deletes objects or changes their contents.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

RETENTION_TAG = {"Key": "heytim-retention", "Value": "transient-tool-result"}
RESULT_KEY = re.compile(
    r"(?:users/[a-f0-9]{64}(?:/bots/[A-Za-z0-9][A-Za-z0-9_-]{0,63})?"
    r"|groups/[a-f0-9-]{36})/tool-results/[a-f0-9-]{32,64}/"
    r"result_[a-f0-9]{24}_[a-f0-9]{32}\Z"
)
BUCKET_PREFIXES = (
    "heytim-user-files",
    "heytim-production-user-files",
    "frogbot-user-files",  # existing physical bucket only
    "frogbot-production-user-files",  # existing physical bucket only
)


class BackfillError(Exception):
    pass


def validate_target(account: str, region: str, bucket: str) -> None:
    if not re.fullmatch(r"[0-9]{12}", account):
        raise BackfillError("--account must be a 12-digit AWS account ID")
    if not re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]", region):
        raise BackfillError("--region must be an AWS region")
    if bucket not in {f"{name}-{account}-{region}" for name in BUCKET_PREFIXES}:
        raise BackfillError(
            "bucket must be a known user-files bucket for this account and region"
        )


def normalized_tags(tags: list[dict[str, str]]) -> list[dict[str, str]]:
    if not isinstance(tags, list) or any(
        not isinstance(tag, dict)
        or not isinstance(tag.get("Key"), str)
        or not isinstance(tag.get("Value"), str)
        for tag in tags
    ):
        raise BackfillError("object tags are malformed")
    keys = [tag["Key"] for tag in tags]
    if len(keys) != len(set(keys)):
        raise BackfillError("object has duplicate tag keys")
    return sorted(
        ({"Key": tag["Key"], "Value": tag["Value"]} for tag in tags),
        key=lambda x: x["Key"],
    )


def desired_tags(original: list[dict[str, str]]) -> list[dict[str, str]]:
    current = normalized_tags(original)
    same_key = next(
        (tag for tag in current if tag["Key"] == RETENTION_TAG["Key"]), None
    )
    if same_key and same_key != RETENTION_TAG:
        raise BackfillError("an object has a conflicting retention tag")
    if not same_key and len(current) >= 10:
        raise BackfillError("an object already has the maximum 10 tags")
    return normalized_tags(current if same_key else [*current, RETENTION_TAG])


def inventory(s3: Any, bucket: str, account: str) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    delete_markers = 0
    paginator = s3.get_paginator("list_object_versions")
    for prefix in ("users/", "groups/"):
        for page in paginator.paginate(
            Bucket=bucket, Prefix=prefix, ExpectedBucketOwner=account
        ):
            delete_markers += sum(
                bool(RESULT_KEY.fullmatch(item.get("Key", "")))
                for item in page.get("DeleteMarkers", [])
            )
            for item in page.get("Versions", []):
                key = item.get("Key", "")
                if not RESULT_KEY.fullmatch(key):
                    continue
                version_id = item.get("VersionId")
                if not isinstance(version_id, str) or not version_id:
                    raise BackfillError("matching object has no version ID")
                tags = normalized_tags(
                    s3.get_object_tagging(
                        Bucket=bucket,
                        Key=key,
                        VersionId=version_id,
                        ExpectedBucketOwner=account,
                    ).get("TagSet", [])
                )
                desired_tags(tags)
                rows.append(
                    {
                        "key": key,
                        "versionId": version_id,
                        "size": item["Size"],
                        "etag": item.get("ETag", ""),
                        "lastModified": item["LastModified"].isoformat(),
                        "isLatest": item["IsLatest"],
                        "tags": tags,
                    }
                )
    rows.sort(key=lambda row: (row["key"], row["versionId"]))
    if len({(row["key"], row["versionId"]) for row in rows}) != len(rows):
        raise BackfillError("inventory contains duplicate object versions")
    return rows, delete_markers


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, ensure_ascii=False)
            output.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def load_manifest(path: Path) -> dict[str, Any]:
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_uid != os.getuid()
        or path.stat().st_mode & 0o077
    ):
        raise BackfillError("manifest must be a private regular file (mode 0600)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != 1:
        raise BackfillError("manifest format is unsupported")
    return payload


def apply_manifest(
    s3: Any,
    payload: dict[str, Any],
    account: str,
    region: str,
    bucket: str,
    confirm_count: int,
) -> tuple[int, int]:
    if (payload.get("account"), payload.get("region"), payload.get("bucket")) != (
        account,
        region,
        bucket,
    ):
        raise BackfillError("manifest target differs from requested AWS target")
    planned = payload.get("versions")
    if not isinstance(planned, list):
        raise BackfillError("manifest has no version inventory")
    if payload.get("versionCount") != len(planned):
        raise BackfillError("manifest version count is inconsistent")
    if any(
        not isinstance(row, dict)
        or not isinstance(row.get("key"), str)
        or not RESULT_KEY.fullmatch(row["key"])
        or not isinstance(row.get("versionId"), str)
        or not isinstance(row.get("tags"), list)
        for row in planned
    ):
        raise BackfillError("manifest contains an invalid result version")
    if len({(row["key"], row["versionId"]) for row in planned}) != len(planned):
        raise BackfillError("manifest has duplicate versions")
    to_tag = sum(row["tags"] != desired_tags(row["tags"]) for row in planned)
    if confirm_count != to_tag or payload.get("toTag") != to_tag:
        raise BackfillError("reviewed --confirm-count does not match manifest")

    actual, markers = inventory(s3, bucket, account)
    if len(actual) != len(planned) or markers != payload.get("deleteMarkers"):
        raise BackfillError("live version or delete-marker count changed since dry-run")
    for before, now in zip(planned, actual, strict=True):
        fields = ("key", "versionId", "size", "etag", "lastModified", "isLatest")
        if any(before.get(field) != now.get(field) for field in fields):
            raise BackfillError("live object versions changed since dry-run")
        if now["tags"] not in (before["tags"], desired_tags(before["tags"])):
            raise BackfillError("live object tags changed since dry-run")

    changed = 0
    for before, now in zip(planned, actual, strict=True):
        expected_tags = desired_tags(before["tags"])
        if now["tags"] == expected_tags:
            continue
        s3.put_object_tagging(
            Bucket=bucket,
            Key=before["key"],
            VersionId=before["versionId"],
            ExpectedBucketOwner=account,
            Tagging={"TagSet": expected_tags},
        )
        readback = normalized_tags(
            s3.get_object_tagging(
                Bucket=bucket,
                Key=before["key"],
                VersionId=before["versionId"],
                ExpectedBucketOwner=account,
            ).get("TagSet", [])
        )
        if readback != expected_tags:
            raise BackfillError("tag readback differs from planned tags")
        changed += 1

    final, final_markers = inventory(s3, bucket, account)
    if final_markers != markers or len(final) != len(planned):
        raise BackfillError("post-apply version count differs from dry-run")
    for before, after in zip(planned, final, strict=True):
        fields = ("key", "versionId", "size", "etag", "lastModified", "isLatest")
        if any(before.get(field) != after.get(field) for field in fields):
            raise BackfillError("post-apply object versions differ from dry-run")
        if after["tags"] != desired_tags(before["tags"]):
            raise BackfillError("post-apply tags differ from plan")
    return changed, len(final)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-count", type=int)
    args = parser.parse_args()
    try:
        validate_target(args.account, args.region, args.bucket)
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        actual_account = session.client("sts").get_caller_identity()["Account"]
        if actual_account != args.account:
            raise BackfillError("AWS profile is signed into a different account")
        s3 = session.client("s3")
        s3.head_bucket(Bucket=args.bucket, ExpectedBucketOwner=args.account)
        actual_region = (
            s3.get_bucket_location(
                Bucket=args.bucket, ExpectedBucketOwner=args.account
            ).get("LocationConstraint")
            or "us-east-1"
        )
        if actual_region != args.region:
            raise BackfillError("bucket is in a different AWS region")
        if args.apply:
            if args.confirm_count is None or args.confirm_count < 0:
                raise BackfillError("--apply requires reviewed --confirm-count")
            payload = load_manifest(args.manifest)
            changed, total = apply_manifest(
                s3, payload, args.account, args.region, args.bucket, args.confirm_count
            )
            print(f"Tagged {changed} versions; verified {total} result versions.")
        else:
            if args.confirm_count is not None:
                raise BackfillError("--confirm-count is only valid with --apply")
            rows, markers = inventory(s3, args.bucket, args.account)
            to_tag = sum(row["tags"] != desired_tags(row["tags"]) for row in rows)
            write_manifest(
                args.manifest,
                {
                    "format": 1,
                    "account": args.account,
                    "region": args.region,
                    "bucket": args.bucket,
                    "versionCount": len(rows),
                    "deleteMarkers": markers,
                    "toTag": to_tag,
                    "versions": rows,
                },
            )
            print(
                f"Dry-run: {len(rows)} result versions, {markers} delete markers, "
                f"{to_tag} versions to tag. Manifest: {args.manifest}"
            )
        return 0
    except (BackfillError, ClientError, OSError, ValueError, KeyError) as exc:
        print(f"Backfill stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
