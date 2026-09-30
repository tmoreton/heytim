"""Inventory, copy, and verify unversioned inbound bot mail for the account move.

Only the destination S3 bucket can be written. Raw MIME stays in AWS or process
memory; the owner-only manifest contains keys, sizes, and hashes, never bodies.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError
from migrate_dynamodb_state import write_private_manifest

SOURCE_ACCOUNT = "188757775631"
DESTINATION_ACCOUNT = "820323452649"
REGION = "us-east-1"
MESSAGE_KEY = re.compile(r"^received/[A-Za-z0-9_-]{1,200}$")
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
RAW_RETENTION = timedelta(days=7)


class MailMigrationError(RuntimeError):
    """A cutover precondition or parity check failed."""


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _account(session: Any, expected: str) -> None:
    actual = session.client("sts").get_caller_identity()["Account"]
    if actual != expected:
        raise MailMigrationError("AWS profile is in the wrong account")


def _stack_resources(cfn: Any, root: str, account: str) -> list[dict]:
    stack = cfn.describe_stacks(StackName=root)["Stacks"]
    if len(stack) != 1 or not stack[0]["StackStatus"].endswith("_COMPLETE"):
        raise MailMigrationError("Amplify stack is not in a completed state")
    pending = [stack[0]["StackId"]]
    seen: set[str] = set()
    resources: list[dict] = []
    while pending:
        stack_id = pending.pop()
        if stack_id in seen:
            continue
        if f":{REGION}:{account}:" not in stack_id:
            raise MailMigrationError("Nested stack has an unexpected account or region")
        seen.add(stack_id)
        for page in cfn.get_paginator("list_stack_resources").paginate(
            StackName=stack_id
        ):
            for item in page.get("StackResourceSummaries", []):
                resources.append(item)
                if item["ResourceType"] == "AWS::CloudFormation::Stack":
                    pending.append(item["PhysicalResourceId"])
    return resources


def _physical(resources: list[dict], kind: str, logical_prefix: str) -> str:
    found = [
        item["PhysicalResourceId"]
        for item in resources
        if item["ResourceType"] == kind
        and item["LogicalResourceId"].startswith(logical_prefix)
        and item.get("PhysicalResourceId")
    ]
    if len(found) != 1:
        raise MailMigrationError(f"Expected one {logical_prefix} resource")
    return found[0]


def _table_rows(ddb: Any, table_name: str, account: str) -> list[tuple[str, ...]]:
    table = ddb.Table(table_name)
    detail = table.meta.client.describe_table(TableName=table_name)["Table"]
    if (
        detail["TableStatus"] != "ACTIVE"
        or f":{account}:" not in detail["TableArn"]
        or [(part["AttributeName"], part["KeyType"]) for part in detail["KeySchema"]]
        != [("pk", "HASH"), ("sk", "RANGE")]
    ):
        raise MailMigrationError("Application table identity or schema changed")
    rows: list[tuple[str, ...]] = []
    paginator = table.meta.client.get_paginator("scan")
    for page in paginator.paginate(
        TableName=table_name,
        ConsistentRead=True,
        FilterExpression=Attr("entity").eq("BOT_EMAIL"),
        ProjectionExpression="#pk,#sk,#e,#key,#ses,#bot,#when",
        ExpressionAttributeNames={
            "#pk": "pk",
            "#sk": "sk",
            "#e": "entity",
            "#key": "rawObjectKey",
            "#ses": "sesMessageId",
            "#bot": "botId",
            "#when": "receivedAt",
        },
    ):
        for item in page.get("Items", []):
            fields = tuple(
                item.get(name)
                for name in (
                    "sk",
                    "sesMessageId",
                    "rawObjectKey",
                    "botId",
                    "receivedAt",
                )
            )
            if (
                item.get("entity") != "BOT_EMAIL"
                or not all(isinstance(value, str) and value for value in fields)
                or item["rawObjectKey"] != f"received/{item['sesMessageId']}"
                or not MESSAGE_KEY.fullmatch(item["rawObjectKey"])
                or not isinstance(item.get("pk"), str)
                or not item["pk"].startswith("USER#")
            ):
                raise MailMigrationError("Malformed retained inbox row")
            rows.append(fields)
    return sorted(rows)


def _lifecycle(s3: Any, bucket: str, account: str) -> list[dict]:
    try:
        response = s3.get_bucket_lifecycle_configuration(
            Bucket=bucket, ExpectedBucketOwner=account
        )
    except ClientError as error:
        if (
            error.response.get("Error", {}).get("Code")
            == "NoSuchLifecycleConfiguration"
        ):
            return []
        raise
    return response.get("Rules", [])


def _check_bucket(s3: Any, bucket: str, account: str) -> list[dict]:
    s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
    location = s3.get_bucket_location(Bucket=bucket, ExpectedBucketOwner=account)
    if location.get("LocationConstraint") not in (None, "", REGION):
        raise MailMigrationError("Inbound bucket region changed")
    versioning = s3.get_bucket_versioning(Bucket=bucket, ExpectedBucketOwner=account)
    if versioning.get("Status") or versioning.get("MFADelete"):
        raise MailMigrationError("Inbound bucket is no longer unversioned")
    encryption = s3.get_bucket_encryption(Bucket=bucket, ExpectedBucketOwner=account)
    rules = encryption["ServerSideEncryptionConfiguration"]["Rules"]
    if (
        len(rules) != 1
        or rules[0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] != "AES256"
    ):
        raise MailMigrationError(
            "Inbound bucket is not using reviewed SSE-S3 encryption"
        )
    block = s3.get_public_access_block(Bucket=bucket, ExpectedBucketOwner=account)
    if not all(
        block["PublicAccessBlockConfiguration"].get(key) is True
        for key in (
            "BlockPublicAcls",
            "IgnorePublicAcls",
            "BlockPublicPolicy",
            "RestrictPublicBuckets",
        )
    ):
        raise MailMigrationError("Inbound bucket public access block changed")
    return _lifecycle(s3, bucket, account)


def _objects(s3: Any, bucket: str, account: str) -> dict[str, int]:
    objects: dict[str, int] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix="received/", ExpectedBucketOwner=account
    ):
        for item in page.get("Contents", []):
            key = item["Key"]
            if not MESSAGE_KEY.fullmatch(key) or key in objects:
                raise MailMigrationError("Unexpected or duplicate inbound object key")
            if item["Size"] > MAX_MESSAGE_BYTES:
                raise MailMigrationError("Inbound MIME exceeds bounded transfer size")
            objects[key] = item["Size"]
    return objects


def _hash_object(s3: Any, bucket: str, account: str, key: str, size: int) -> str:
    response = s3.get_object(Bucket=bucket, Key=key, ExpectedBucketOwner=account)
    digest = hashlib.sha256()
    count = 0
    body = response["Body"]
    try:
        for part in body.iter_chunks(chunk_size=1024 * 1024):
            count += len(part)
            if count > MAX_MESSAGE_BYTES:
                raise MailMigrationError("Inbound MIME exceeds bounded transfer size")
            digest.update(part)
    finally:
        body.close()
    if count != size or response["ContentLength"] != size:
        raise MailMigrationError("Inbound MIME size changed during inventory")
    return digest.hexdigest()


def _raw_missing(
    rows: list[tuple[str, ...]], keys: set[str], now: datetime
) -> tuple[int, int]:
    missing = recent = 0
    for _, _, key, _, received_at in rows:
        try:
            when = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise MailMigrationError("Invalid inbox receipt timestamp") from error
        if when.tzinfo is None or when > now + timedelta(minutes=5):
            raise MailMigrationError("Invalid inbox receipt timestamp")
        if key not in keys:
            missing += 1
            if now - when < RAW_RETENTION:
                recent += 1
    return missing, recent


def inventory(
    source: Any,
    destination: Any,
    source_stack: str,
    destination_stack: str,
    source_bucket: str,
    destination_bucket: str,
) -> tuple[dict, dict]:
    _account(source, SOURCE_ACCOUNT)
    _account(destination, DESTINATION_ACCOUNT)
    src_resources = _stack_resources(
        source.client("cloudformation"), source_stack, SOURCE_ACCOUNT
    )
    dst_resources = _stack_resources(
        destination.client("cloudformation"), destination_stack, DESTINATION_ACCOUNT
    )
    if source_bucket != _physical(src_resources, "AWS::S3::Bucket", "IncomingBotMail"):
        raise MailMigrationError(
            "Source bucket differs from the live CloudFormation resource"
        )
    if destination_bucket != _physical(
        dst_resources, "AWS::S3::Bucket", "IncomingBotMail"
    ):
        raise MailMigrationError(
            "Destination bucket differs from the live CloudFormation resource"
        )
    src_table = _physical(src_resources, "AWS::DynamoDB::Table", "Data")
    dst_table = _physical(dst_resources, "AWS::DynamoDB::Table", "Data")
    src_s3 = source.client("s3")
    dst_s3 = destination.client("s3")
    src_rules = _check_bucket(src_s3, source_bucket, SOURCE_ACCOUNT)
    dst_rules = _check_bucket(dst_s3, destination_bucket, DESTINATION_ACCOUNT)
    src_rows = _table_rows(source.resource("dynamodb"), src_table, SOURCE_ACCOUNT)
    dst_rows = _table_rows(
        destination.resource("dynamodb"), dst_table, DESTINATION_ACCOUNT
    )
    src_sizes = _objects(src_s3, source_bucket, SOURCE_ACCOUNT)
    dst_sizes = _objects(dst_s3, destination_bucket, DESTINATION_ACCOUNT)
    src_objects = {
        key: {
            "bytes": size,
            "sha256": _hash_object(src_s3, source_bucket, SOURCE_ACCOUNT, key, size),
        }
        for key, size in sorted(src_sizes.items())
    }
    dst_objects = {
        key: {
            "bytes": size,
            "sha256": _hash_object(
                dst_s3, destination_bucket, DESTINATION_ACCOUNT, key, size
            ),
        }
        for key, size in sorted(dst_sizes.items())
    }
    extra = set(dst_objects) - set(src_objects)
    divergent = {
        key
        for key in src_objects.keys() & dst_objects.keys()
        if src_objects[key] != dst_objects[key]
    }
    missing, recent = _raw_missing(src_rows, set(src_objects), datetime.now(UTC))
    manifest = {
        "schemaVersion": 1,
        "sourceAccount": SOURCE_ACCOUNT,
        "destinationAccount": DESTINATION_ACCOUNT,
        "region": REGION,
        "sourceBucket": source_bucket,
        "destinationBucket": destination_bucket,
        "sourceTable": src_table,
        "destinationTable": dst_table,
        "sourceRows": len(src_rows),
        "destinationRows": len(dst_rows),
        "sourceRowsDigest": _digest(src_rows),
        "destinationRowsDigest": _digest(dst_rows),
        "sourceObjects": src_objects,
        "destinationObjectsMatching": len(set(src_objects) & set(dst_objects))
        - len(divergent),
        "destinationExtraObjects": len(extra),
        "destinationDivergentObjects": len(divergent),
        "sourceRowsMissingRaw": missing,
        "sourceRecentRowsMissingRaw": recent,
        "sourceEnabledLifecycleRules": sum(
            rule.get("Status") == "Enabled" for rule in src_rules
        ),
        "destinationSevenDayLifecycle": any(
            rule.get("Status") == "Enabled"
            and rule.get("Expiration", {}).get("Days") == 7
            and rule.get("Filter", {}).get("Prefix", "") == ""
            for rule in dst_rules
        ),
    }
    manifest["planDigest"] = _digest(
        {
            "sourceAccount": SOURCE_ACCOUNT,
            "destinationAccount": DESTINATION_ACCOUNT,
            "sourceBucket": source_bucket,
            "destinationBucket": destination_bucket,
            "sourceTable": src_table,
            "destinationTable": dst_table,
            "sourceRowsDigest": manifest["sourceRowsDigest"],
            "sourceObjects": src_objects,
        }
    )
    private = {
        "source": src_s3,
        "destination": dst_s3,
        "destinationObjects": dst_objects,
        "sourceRows": src_rows,
        "destinationRows": dst_rows,
    }
    return manifest, private


def _assert_plan(manifest: dict, private: dict, final: bool) -> None:
    if manifest["destinationExtraObjects"] or manifest["destinationDivergentObjects"]:
        raise MailMigrationError("Destination has unexpected or divergent MIME objects")
    if manifest["sourceRecentRowsMissingRaw"]:
        raise MailMigrationError("A recent inbox row has no source raw MIME object")
    if not manifest["destinationSevenDayLifecycle"]:
        raise MailMigrationError("Destination seven-day raw MIME lifecycle is absent")
    if private["destinationRows"] and Counter(private["destinationRows"]) != Counter(
        private["sourceRows"]
    ):
        raise MailMigrationError("Destination inbox rows differ from source rows")
    if final and Counter(private["destinationRows"]) != Counter(private["sourceRows"]):
        raise MailMigrationError("Destination inbox rows are not yet migrated")
    if final and manifest["destinationObjectsMatching"] != len(
        manifest["sourceObjects"]
    ):
        raise MailMigrationError("Destination raw MIME objects are incomplete")


def _dry_run_blockers(manifest: dict, private: dict) -> list[str]:
    blockers = []
    if manifest["destinationExtraObjects"]:
        blockers.append("destination_has_unclassified_raw_objects")
    if manifest["destinationDivergentObjects"]:
        blockers.append("destination_raw_object_differs")
    if manifest["sourceRecentRowsMissingRaw"]:
        blockers.append("recent_source_inbox_raw_missing")
    if not manifest["destinationSevenDayLifecycle"]:
        blockers.append("destination_raw_retention_unverified")
    if private["destinationRows"] and Counter(private["destinationRows"]) != Counter(
        private["sourceRows"]
    ):
        blockers.append("destination_inbox_rows_differ")
    if manifest["sourceEnabledLifecycleRules"]:
        blockers.append("source_raw_lifecycle_still_enabled")
    return blockers


def _copy_one(
    src: Any,
    dst: Any,
    source_bucket: str,
    destination_bucket: str,
    key: str,
    expected: dict,
) -> None:
    response = src.get_object(
        Bucket=source_bucket, Key=key, ExpectedBucketOwner=SOURCE_ACCOUNT
    )
    body = response["Body"]
    try:
        data = body.read(MAX_MESSAGE_BYTES + 1)
    finally:
        body.close()
    if (
        len(data) != expected["bytes"]
        or hashlib.sha256(data).hexdigest() != expected["sha256"]
    ):
        raise MailMigrationError("Source MIME changed after the reviewed inventory")
    dst.put_object(
        Bucket=destination_bucket,
        Key=key,
        Body=data,
        ContentLength=len(data),
        ContentType="message/rfc822",
        ServerSideEncryption="AES256",
        ChecksumSHA256=base64.b64encode(hashlib.sha256(data).digest()).decode("ascii"),
        ExpectedBucketOwner=DESTINATION_ACCOUNT,
    )
    if (
        _hash_object(dst, destination_bucket, DESTINATION_ACCOUNT, key, len(data))
        != expected["sha256"]
    ):
        raise MailMigrationError("Destination MIME checksum differs after copy")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    for name in (
        "source-profile",
        "destination-profile",
        "source-stack",
        "destination-stack",
        "source-bucket",
        "destination-bucket",
        "manifest",
    ):
        result.add_argument(f"--{name}", required=True)
    result.add_argument(
        "--apply",
        action="store_true",
        help="Copy only missing objects into destination",
    )
    result.add_argument(
        "--verify",
        action="store_true",
        help="Require final object and inbox-row parity",
    )
    result.add_argument("--expected-plan-digest")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.apply and args.verify:
            raise MailMigrationError("Choose copy or final verification")
        if (
            args.source_profile == args.destination_profile
            or args.source_bucket == args.destination_bucket
        ):
            raise MailMigrationError("Source and destination identities must differ")
        if args.apply and (
            not args.expected_plan_digest
            or os.environ.get("HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED") != "true"
        ):
            raise MailMigrationError(
                "Copy needs reviewed digest and cutover approval flag"
            )
        import boto3

        source = boto3.Session(profile_name=args.source_profile, region_name=REGION)
        destination = boto3.Session(
            profile_name=args.destination_profile, region_name=REGION
        )
        manifest, private = inventory(
            source,
            destination,
            args.source_stack,
            args.destination_stack,
            args.source_bucket,
            args.destination_bucket,
        )
        if not args.apply and not args.verify:
            manifest["blockers"] = _dry_run_blockers(manifest, private)
            write_private_manifest(Path(args.manifest), manifest)
            print(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "planDigest": manifest["planDigest"],
                        "sourceObjects": len(manifest["sourceObjects"]),
                        "destinationObjectsMatching": manifest[
                            "destinationObjectsMatching"
                        ],
                        "destinationExtraObjects": manifest["destinationExtraObjects"],
                        "sourceInboxRows": manifest["sourceRows"],
                        "destinationInboxRows": manifest["destinationRows"],
                        "sourceRowsMissingRaw": manifest["sourceRowsMissingRaw"],
                        "blockers": manifest["blockers"],
                    },
                    sort_keys=True,
                )
            )
            return 2 if manifest["blockers"] else 0
        _assert_plan(manifest, private, final=args.verify)
        if args.apply:
            if args.expected_plan_digest != manifest["planDigest"]:
                raise MailMigrationError(
                    "Source objects or inbox rows changed since review"
                )
            if manifest["sourceEnabledLifecycleRules"]:
                raise MailMigrationError("Source raw MIME lifecycle is still enabled")
            for key, expected in manifest["sourceObjects"].items():
                if key not in private["destinationObjects"]:
                    _copy_one(
                        private["source"],
                        private["destination"],
                        args.source_bucket,
                        args.destination_bucket,
                        key,
                        expected,
                    )
            after, after_private = inventory(
                source,
                destination,
                args.source_stack,
                args.destination_stack,
                args.source_bucket,
                args.destination_bucket,
            )
            if after["planDigest"] != manifest["planDigest"]:
                raise MailMigrationError(
                    "Source changed while copying; keep traffic on source"
                )
            _assert_plan(after, after_private, final=False)
            if after["destinationObjectsMatching"] != len(after["sourceObjects"]):
                raise MailMigrationError("Destination object copy is incomplete")
            manifest = after
        write_private_manifest(Path(args.manifest), manifest)
        print(
            json.dumps(
                {
                    "mode": "copy"
                    if args.apply
                    else "verify"
                    if args.verify
                    else "dry-run",
                    "planDigest": manifest["planDigest"],
                    "sourceObjects": len(manifest["sourceObjects"]),
                    "destinationObjectsMatching": manifest[
                        "destinationObjectsMatching"
                    ],
                    "sourceInboxRows": manifest["sourceRows"],
                    "destinationInboxRows": manifest["destinationRows"],
                    "sourceRowsMissingRaw": manifest["sourceRowsMissingRaw"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (MailMigrationError, ClientError, OSError, ValueError, KeyError) as error:
        print(f"Bot email migration stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
