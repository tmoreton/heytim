"""Offline safety checks for the versioned S3 migration tool."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl

SCRIPT = Path(__file__).with_name("migrate_versioned_s3.py")
# importlib's file loader does not add the script directory to sys.path.
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("migrate_versioned_s3", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)

ACTOR = "a" * 64
NEW_ACTOR = "b" * 64
MAPPINGS = [(f"users/{ACTOR}/", f"users/{NEW_ACTOR}/")]
START = datetime(2026, 9, 1, tzinfo=timezone.utc)
COPIED_HEAD_FIELDS = (
    "CacheControl",
    "ContentDisposition",
    "ContentEncoding",
    "ContentLanguage",
    "ContentType",
    "Expires",
    "WebsiteRedirectLocation",
)


class Paginator:
    def __init__(self, client: FakeS3) -> None:
        self.client = client

    def paginate(self, *, Bucket: str, Prefix: str, ExpectedBucketOwner: str):
        assert Bucket == self.client.bucket
        assert ExpectedBucketOwner == self.client.account
        selected = [
            entry for entry in self.client.entries if entry["key"].startswith(Prefix)
        ]
        by_key = {}
        for entry in selected:
            by_key.setdefault(entry["key"], []).append(entry)
        versions = []
        markers = []
        for key, history in sorted(by_key.items()):
            for entry in reversed(history):
                item = {
                    "Key": key,
                    "VersionId": entry["id"],
                    "LastModified": entry["time"],
                    "IsLatest": entry is history[-1],
                }
                if entry["deleted"]:
                    markers.append(item)
                else:
                    versions.append({**item, "Size": len(entry["body"])})
        yield {"Versions": versions, "DeleteMarkers": markers}


class FakeS3:
    def __init__(self, bucket: str, account: str) -> None:
        self.bucket = bucket
        self.account = account
        self.entries: list[dict] = []
        self.calls: list[tuple[str, dict]] = []
        self.pending: dict[str, dict] = {}

    def add(
        self, key: str, body: bytes | None, version: str, time: datetime, **fields
    ) -> None:
        self.entries.append(
            {
                "key": key,
                "body": body,
                "id": version,
                "time": time,
                "deleted": body is None,
                "fields": fields,
            }
        )

    def get_paginator(self, operation: str):
        assert operation == "list_object_versions"
        return Paginator(self)

    def _entry(self, key: str, version: str):
        return next(
            entry
            for entry in self.entries
            if entry["key"] == key and entry["id"] == version
        )

    def head_object(self, *, Bucket, Key, VersionId, ExpectedBucketOwner):
        assert (Bucket, ExpectedBucketOwner) == (self.bucket, self.account)
        entry = self._entry(Key, VersionId)
        return {
            "ContentLength": len(entry["body"]),
            "Metadata": entry["fields"].get("Metadata", {}),
            "ContentType": entry["fields"].get(
                "ContentType", "application/octet-stream"
            ),
            **{
                field: entry["fields"][field]
                for field in COPIED_HEAD_FIELDS
                if field != "ContentType" and field in entry["fields"]
            },
            **(
                {"ServerSideEncryption": entry["fields"]["ServerSideEncryption"]}
                if "ServerSideEncryption" in entry["fields"]
                else {}
            ),
            **(
                {"SSEKMSKeyId": entry["fields"]["SSEKMSKeyId"]}
                if "SSEKMSKeyId" in entry["fields"]
                else {}
            ),
        }

    def get_object_tagging(self, *, Bucket, Key, VersionId, ExpectedBucketOwner):
        assert (Bucket, ExpectedBucketOwner) == (self.bucket, self.account)
        return {"TagSet": self._entry(Key, VersionId)["fields"].get("TagSet", [])}

    def get_object(self, *, Bucket, Key, VersionId, ExpectedBucketOwner):
        assert (Bucket, ExpectedBucketOwner) == (self.bucket, self.account)
        return {"Body": io.BytesIO(self._entry(Key, VersionId)["body"])}

    def put_object(self, **kwargs):
        assert (kwargs["Bucket"], kwargs["ExpectedBucketOwner"]) == (
            self.bucket,
            self.account,
        )
        self.calls.append(("put", kwargs))
        version = f"created-{len(self.entries)}"
        self.add(
            kwargs["Key"],
            kwargs["Body"],
            version,
            START + timedelta(days=30, seconds=len(self.entries)),
            ContentType=kwargs.get("ContentType", "application/octet-stream"),
            Metadata=kwargs.get("Metadata", {}),
            **{
                field: kwargs[field]
                for field in COPIED_HEAD_FIELDS
                if field != "ContentType" and field in kwargs
            },
            ServerSideEncryption=kwargs.get("ServerSideEncryption"),
            SSEKMSKeyId=kwargs.get("SSEKMSKeyId"),
            TagSet=[
                {"Key": key, "Value": value}
                for key, value in parse_qsl(kwargs.get("Tagging", ""))
            ],
        )
        return {"VersionId": version}

    def create_multipart_upload(self, **kwargs):
        self.calls.append(("multipart", kwargs))
        upload_id = f"upload-{len(self.pending)}"
        self.pending[upload_id] = {"args": kwargs, "parts": {}}
        return {"UploadId": upload_id}

    def upload_part(self, **kwargs):
        self.pending[kwargs["UploadId"]]["parts"][kwargs["PartNumber"]] = kwargs["Body"]
        return {"ETag": f"part-{kwargs['PartNumber']}"}

    def complete_multipart_upload(self, **kwargs):
        upload = self.pending.pop(kwargs["UploadId"])
        body = b"".join(upload["parts"][number] for number in sorted(upload["parts"]))
        settings = upload["args"]
        version = f"created-{len(self.entries)}"
        self.add(
            kwargs["Key"],
            body,
            version,
            START + timedelta(days=30, seconds=len(self.entries)),
            ContentType=settings.get("ContentType", "application/octet-stream"),
            Metadata=settings.get("Metadata", {}),
            **{
                field: settings[field]
                for field in COPIED_HEAD_FIELDS
                if field != "ContentType" and field in settings
            },
            ServerSideEncryption=settings.get("ServerSideEncryption"),
            SSEKMSKeyId=settings.get("SSEKMSKeyId"),
            TagSet=[
                {"Key": key, "Value": value}
                for key, value in parse_qsl(settings.get("Tagging", ""))
            ],
        )
        return {"VersionId": version}

    def abort_multipart_upload(self, **kwargs):
        self.pending.pop(kwargs["UploadId"], None)

    def delete_object(self, **kwargs):
        assert (kwargs["Bucket"], kwargs["ExpectedBucketOwner"]) == (
            self.bucket,
            self.account,
        )
        self.calls.append(("delete", kwargs))
        version = f"created-{len(self.entries)}"
        self.add(
            kwargs["Key"],
            None,
            version,
            START + timedelta(days=30, seconds=len(self.entries)),
        )
        return {"VersionId": version, "DeleteMarker": True}


def scope() -> dict:
    return {
        "sourceAccount": "111111111111",
        "sourceBucket": "source",
        "destinationAccount": "222222222222",
        "destinationBucket": "destination",
        "destinationKmsKey": "arn:aws:kms:us-east-1:222222222222:key/abc",
        "region": "us-east-1",
        "prefixes": ["users/"],
        "keyMap": MAPPINGS,
        "archivePrefix": "",
    }


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = FakeS3("source", "111111111111")
        self.destination = FakeS3("destination", "222222222222")
        self.key = f"users/{ACTOR}/uploads/example.txt"
        self.target = f"users/{NEW_ACTOR}/uploads/example.txt"

    def plan(self):
        versions = migration.inventory(
            self.source, "source", "111111111111", ["users/"]
        )
        return migration.make_plan(versions, scope(), MAPPINGS)

    def test_orders_versions_and_delete_markers_oldest_first(self):
        self.source.add(self.key, b"old", "v1", START)
        self.source.add(self.key, None, "deleted", START + timedelta(seconds=1))
        self.source.add(self.key, b"new", "v2", START + timedelta(seconds=2))
        plan = self.plan()
        self.assertEqual(
            [op["sourceVersionId"] for op in plan["operations"]],
            ["v1", "deleted", "v2"],
        )
        self.assertEqual(
            [op["deleteMarker"] for op in plan["operations"]], [False, True, False]
        )

    def test_fails_on_ambiguous_cross_type_timestamp(self):
        self.source.add(self.key, b"old", "v1", START)
        self.source.add(self.key, None, "deleted", START)
        with self.assertRaisesRegex(migration.MigrationError, "share a timestamp"):
            self.plan()

    def test_exact_allowlist_excludes_adjacent_keys(self):
        self.source.add(self.key, b"old", "v1", START)
        self.source.add(self.key + ".other", b"other", "v2", START)
        chosen = migration.inventory(
            self.source, "source", "111111111111", [], [self.key]
        )
        self.assertEqual([item["sourceKey"] for item in chosen], [self.key])

    def test_archive_all_keys_without_user_remap(self):
        self.source.add(self.key, b"old", "v1", START)
        self.source.add("meme-templates/v1/catalog.json", b"template", "v2", START)
        archive_scope = {
            **scope(),
            "prefixes": [""],
            "keyMap": [],
            "archivePrefix": "migration-archive/legacy/",
        }
        all_versions = migration.inventory(self.source, "source", "111111111111", [""])
        plan = migration.make_plan(all_versions, archive_scope, [])
        self.assertEqual(
            {op["destinationKey"] for op in plan["operations"]},
            {
                "migration-archive/legacy/" + self.key,
                "migration-archive/legacy/meme-templates/v1/catalog.json",
            },
        )

    def test_requires_explicit_user_actor_remap(self):
        self.source.add(self.key, b"old", "v1", START)
        versions = migration.inventory(
            self.source, "source", "111111111111", ["users/"]
        )
        with self.assertRaisesRegex(
            migration.MigrationError, "explicit destination prefix remap"
        ):
            migration.make_plan(versions, scope(), [])

    def test_user_actor_map_must_match_verified_cognito_pair(self):
        old_actor = hashlib.sha256(b"user:source-sub").hexdigest()
        new_actor = hashlib.sha256(b"user:destination-sub").hexdigest()
        old_prefix = f"users/{old_actor}/"
        new_prefix = f"users/{new_actor}/"
        selected = [{"sourceKey": old_prefix + "uploads/report.pdf"}]
        source_users = {"owner@example.test": "source-sub"}
        destination_users = {"owner@example.test": "destination-sub"}
        migration.validate_user_actor_mappings(
            selected, [(old_prefix, new_prefix)], source_users, destination_users
        )
        with self.assertRaisesRegex(
            migration.MigrationError, "differs from verified Cognito"
        ):
            migration.validate_user_actor_mappings(
                selected,
                [(old_prefix, f"users/{'f' * 64}/")],
                source_users,
                destination_users,
            )
        with self.assertRaisesRegex(
            migration.MigrationError, "differs from verified Cognito"
        ):
            migration.validate_user_actor_mappings(
                selected,
                [(old_prefix, new_prefix), (old_prefix + "uploads/", "users/wrong/")],
                source_users,
                destination_users,
            )
        with self.assertRaisesRegex(
            migration.MigrationError, "no verified destination"
        ):
            migration.validate_user_actor_mappings(
                selected, [(old_prefix, new_prefix)], source_users, {}
            )

    def test_rejects_mapping_collision(self):
        another = f"users/{'c' * 64}/uploads/example.txt"
        self.source.add(self.key, b"old", "v1", START)
        self.source.add(another, b"second", "v2", START)
        versions = migration.inventory(
            self.source, "source", "111111111111", ["users/"]
        )
        mappings = MAPPINGS + [(f"users/{'c' * 64}/", f"users/{NEW_ACTOR}/")]
        with self.assertRaisesRegex(migration.MigrationError, "same destination key"):
            migration.make_plan(versions, scope(), mappings)

    def test_private_allowlist_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "allowlist.json"
            path.write_text(json.dumps([self.key]))
            path.chmod(0o600)
            self.assertEqual(migration.load_exact_keys(path), [self.key])
            path.chmod(0o644)
            with self.assertRaisesRegex(migration.MigrationError, "owner-only"):
                migration.load_exact_keys(path)

    def test_pending_write_requires_explicit_verified_adoption(self):
        self.source.add(
            self.key,
            b"old",
            "v1",
            START,
            ContentType="text/plain",
            Metadata={"author": "owner"},
        )
        plan = self.plan()
        plan["operations"][0]["state"] = "pending"
        self.destination.put_object(
            Bucket="destination",
            Key=self.target,
            Body=b"old",
            ExpectedBucketOwner="222222222222",
            ContentType="text/plain",
            Metadata={"author": "owner"},
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=scope()["destinationKmsKey"],
        )
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "manifest"
            version_map = Path(folder) / "map"
            migration.write_private_json(manifest, plan)
            with self.assertRaisesRegex(
                migration.MigrationError, "--adopt-pending-version-id"
            ):
                migration.execute(
                    plan, self.source, self.destination, manifest, version_map
                )
            self.assertEqual(len(self.destination.entries), 1)
            result = migration.execute(
                plan, self.source, self.destination, manifest, version_map, "created-0"
            )
            self.assertEqual(result["versions"], 1)
            self.assertEqual(len(self.destination.entries), 1)
            self.assertEqual(
                plan["operations"][0]["sha256"],
                migration.stream_hash(
                    self.source, "source", self.key, "v1", "111111111111"
                )[0],
            )

    def test_pending_without_destination_write_restarts_once(self):
        self.source.add(self.key, b"old", "v1", START)
        plan = self.plan()
        plan["operations"][0]["state"] = "pending"
        with tempfile.TemporaryDirectory() as folder:
            result = migration.execute(
                plan,
                self.source,
                self.destination,
                Path(folder) / "manifest",
                Path(folder) / "map",
            )
            self.assertEqual(result["versions"], 1)
            self.assertEqual(len(self.destination.entries), 1)

    def test_resume_accepts_verified_operations_and_rejects_inventory_drift(self):
        self.source.add(self.key, b"old", "v1", START)
        plan = self.plan()
        plan["operations"][0].update(
            state="done", destinationVersionId="dest-v1", sha256="x" * 64
        )
        self.assertIs(migration.check_resume(plan, self.plan()), plan)
        self.source.add(self.key, b"new", "v2", START + timedelta(seconds=1))
        with self.assertRaisesRegex(
            migration.MigrationError, "Source inventory changed"
        ):
            migration.check_resume(plan, self.plan())

    def test_apply_requires_a_reviewed_dry_run_manifest(self):
        self.source.add(self.key, b"old", "v1", START)
        plan = self.plan()
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "manifest.json"
            with self.assertRaisesRegex(migration.MigrationError, "reviewed dry run"):
                migration.reviewed_plan(manifest, plan, apply=True)
            self.assertFalse(manifest.exists())
            self.assertIs(migration.reviewed_plan(manifest, plan, apply=False), plan)
            migration.write_private_json(manifest, plan)
            self.assertEqual(
                migration.canonical_hash(
                    migration.reviewed_plan(manifest, plan, apply=True)
                ),
                migration.canonical_hash(plan),
            )

    def test_replay_preserves_versions_marker_metadata_tags_and_checksums(self):
        self.source.add(
            self.key,
            b"old",
            "v1",
            START,
            ContentType="text/plain",
            Metadata={"author": "owner"},
            TagSet=[{"Key": "purpose", "Value": "test"}],
        )
        self.source.add(self.key, None, "deleted", START + timedelta(seconds=1))
        self.source.add(self.key, b"new", "v2", START + timedelta(seconds=2))
        # A preexisting template is outside the selected key and remains untouched.
        self.destination.add(
            "meme-templates/v1/catalog.json", b"template", "template-v1", START
        )
        plan = self.plan()
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "manifest.json"
            version_map = Path(folder) / "map.json"
            result = migration.execute(
                plan, self.source, self.destination, manifest, version_map
            )
            self.assertEqual(
                result,
                {"versions": 2, "deleteMarkers": 1, "bytes": 6, "currentObjects": 1},
            )
            self.assertEqual(
                [
                    entry["body"]
                    for entry in self.destination.entries
                    if entry["key"] == self.target
                ],
                [b"old", None, b"new"],
            )
            self.assertEqual(
                len(
                    [
                        entry
                        for entry in self.destination.entries
                        if entry["key"].startswith("meme-templates/")
                    ]
                ),
                1,
            )
            uploaded = next(
                args for method, args in self.destination.calls if method == "put"
            )
            self.assertEqual(uploaded["ServerSideEncryption"], "aws:kms")
            self.assertEqual(uploaded["Metadata"], {"author": "owner"})
            self.assertEqual(uploaded["Tagging"], "purpose=test")
            self.assertEqual(len(json.loads(version_map.read_text())["versions"]), 3)
            self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)
            # Rerunning a completed manifest creates no duplicate versions.
            fresh = self.plan()
            resumed = migration.check_resume(
                migration.load_private_json(manifest), fresh
            )
            self.assertEqual(
                migration.execute(
                    resumed, self.source, self.destination, manifest, version_map
                ),
                result,
            )
            self.assertEqual(len(self.destination.entries), 4)

    def test_existing_destination_key_blocks_replay(self):
        self.source.add(self.key, b"old", "v1", START)
        self.destination.add(self.target, b"unrelated", "dest-v1", START)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(
                migration.MigrationError, "unexpected or missing version"
            ):
                migration.execute(
                    self.plan(),
                    self.source,
                    self.destination,
                    Path(folder) / "manifest",
                    Path(folder) / "map",
                )
            self.assertFalse(self.destination.calls)

    def test_multipart_streams_without_local_body_file(self):
        payload = b"a" * (migration.CHUNK_SIZE + 1)
        self.source.add(self.key, payload, "v1", START)
        with tempfile.TemporaryDirectory() as folder:
            result = migration.execute(
                self.plan(),
                self.source,
                self.destination,
                Path(folder) / "manifest",
                Path(folder) / "map",
            )
            self.assertEqual(result["bytes"], len(payload))
            self.assertEqual(self.destination.calls[0][0], "multipart")
            self.assertEqual(self.destination.entries[0]["body"], payload)


if __name__ == "__main__":
    unittest.main()
