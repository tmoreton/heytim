from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "tag_transient_tool_results.py"
SPEC = importlib.util.spec_from_file_location("tag_transient_tool_results", SOURCE)
assert SPEC and SPEC.loader
backfill = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = backfill
SPEC.loader.exec_module(backfill)

BackfillError = backfill.BackfillError
RESULT_KEY = backfill.RESULT_KEY
apply_manifest = backfill.apply_manifest
desired_tags = backfill.desired_tags
inventory = backfill.inventory
validate_target = backfill.validate_target

ACCOUNT = "123456789012"
REGION = "us-east-1"
BUCKET = f"heytim-production-user-files-{ACCOUNT}-{REGION}"
USER = "a" * 64
TURN = "12345678-1234-1234-1234-123456789012"
REFERENCE = "result_" + "b" * 24 + "_" + "c" * 32
TOOL_KEY = f"users/{USER}/bots/finance/tool-results/{TURN}/{REFERENCE}"
EXPORT_KEY = f"users/{USER}/bots/finance/artifacts/{TURN}/saved-export.csv"


class Paginator:
    def __init__(self, owner):
        self.owner = owner

    def paginate(self, *, Bucket, Prefix, ExpectedBucketOwner):
        assert (Bucket, ExpectedBucketOwner) == (BUCKET, ACCOUNT)
        yield {
            "Versions": [
                row for row in self.owner.versions if row["Key"].startswith(Prefix)
            ],
            "DeleteMarkers": [
                row for row in self.owner.markers if row["Key"].startswith(Prefix)
            ],
        }


class S3:
    def __init__(self):
        self.versions = [
            {
                "Key": TOOL_KEY,
                "VersionId": "version-1",
                "Size": 42,
                "ETag": '"etag"',
                "LastModified": datetime(2026, 9, 29, tzinfo=UTC),
                "IsLatest": True,
            },
            {
                "Key": TOOL_KEY,
                "VersionId": "version-0",
                "Size": 36,
                "ETag": '"older-etag"',
                "LastModified": datetime(2026, 9, 28, tzinfo=UTC),
                "IsLatest": False,
            },
            {
                "Key": EXPORT_KEY,
                "VersionId": "saved-file",
                "Size": 8,
                "ETag": '"saved"',
                "LastModified": datetime(2026, 9, 29, tzinfo=UTC),
                "IsLatest": True,
            },
        ]
        self.markers = [
            {"Key": TOOL_KEY.replace("/finance/", "/other/"), "VersionId": "marker-1"}
        ]
        self.tags = {(TOOL_KEY, "version-1"): [{"Key": "owner", "Value": "user"}]}
        self.writes = []

    def get_paginator(self, name):
        assert name == "list_object_versions"
        return Paginator(self)

    def get_object_tagging(self, *, Bucket, Key, VersionId, ExpectedBucketOwner):
        assert (Bucket, ExpectedBucketOwner) == (BUCKET, ACCOUNT)
        return {"TagSet": self.tags.get((Key, VersionId), [])}

    def put_object_tagging(
        self, *, Bucket, Key, VersionId, ExpectedBucketOwner, Tagging
    ):
        assert (Bucket, ExpectedBucketOwner) == (BUCKET, ACCOUNT)
        self.writes.append((Key, VersionId, Tagging["TagSet"]))
        self.tags[(Key, VersionId)] = Tagging["TagSet"]


def test_scope_matches_only_transient_result_keys():
    assert RESULT_KEY.fullmatch(TOOL_KEY)
    assert not RESULT_KEY.fullmatch(EXPORT_KEY)
    assert not RESULT_KEY.fullmatch(TOOL_KEY + "/other")
    with pytest.raises(BackfillError, match="known user-files bucket"):
        validate_target(ACCOUNT, REGION, "unrelated-bucket")
    validate_target(ACCOUNT, REGION, BUCKET)


def test_tag_plan_preserves_existing_tags_and_refuses_conflicts():
    assert desired_tags([{"Key": "owner", "Value": "user"}]) == [
        {"Key": "heytim-retention", "Value": "transient-tool-result"},
        {"Key": "owner", "Value": "user"},
    ]
    with pytest.raises(BackfillError, match="conflicting"):
        desired_tags([{"Key": "heytim-retention", "Value": "durable"}])


def test_version_specific_apply_verifies_count_and_does_not_touch_exports():
    s3 = S3()
    rows, markers = inventory(s3, BUCKET, ACCOUNT)
    assert len(rows) == 2
    assert markers == 1
    manifest = {
        "format": 1,
        "account": ACCOUNT,
        "region": REGION,
        "bucket": BUCKET,
        "toTag": 2,
        "versionCount": len(rows),
        "deleteMarkers": markers,
        "versions": rows,
    }
    with pytest.raises(BackfillError, match="confirm-count"):
        apply_manifest(s3, manifest, ACCOUNT, REGION, BUCKET, 0)
    assert s3.writes == []
    assert apply_manifest(s3, manifest, ACCOUNT, REGION, BUCKET, 2) == (2, 2)
    assert [(key, version) for key, version, _ in s3.writes] == [
        (TOOL_KEY, "version-0"),
        (TOOL_KEY, "version-1"),
    ]
    assert (EXPORT_KEY, "saved-file") not in s3.tags
    assert apply_manifest(s3, manifest, ACCOUNT, REGION, BUCKET, 2) == (0, 2)


def test_apply_stops_before_writing_if_versions_change_after_dry_run():
    s3 = S3()
    rows, markers = inventory(s3, BUCKET, ACCOUNT)
    s3.versions.append(
        {
            **s3.versions[0],
            "Key": TOOL_KEY.replace("/finance/", "/other/"),
            "VersionId": "new-version",
        }
    )
    manifest = {
        "account": ACCOUNT,
        "region": REGION,
        "bucket": BUCKET,
        "toTag": 2,
        "versionCount": len(rows),
        "deleteMarkers": markers,
        "versions": rows,
    }
    with pytest.raises(BackfillError, match="count changed"):
        apply_manifest(s3, manifest, ACCOUNT, REGION, BUCKET, 2)
    assert s3.writes == []
