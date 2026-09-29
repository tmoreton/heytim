"""Metadata and tag parity checks for versioned S3 account migration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import test_migrate_versioned_s3 as fixture


class MetadataParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = fixture.FakeS3("source", "111111111111")
        self.destination = fixture.FakeS3("destination", "222222222222")
        self.key = f"users/{fixture.ACTOR}/uploads/example.txt"

    def plan(self) -> dict:
        versions = fixture.migration.inventory(
            self.source, "source", "111111111111", ["users/"]
        )
        return fixture.migration.make_plan(versions, fixture.scope(), fixture.MAPPINGS)

    def test_copy_fails_when_destination_drops_object_metadata(self) -> None:
        self.source.add(
            self.key,
            b"body",
            "v1",
            fixture.START,
            ContentType="text/plain",
            Metadata={"author": "owner"},
        )
        original_put = self.destination.put_object

        def drop_metadata(**kwargs):
            return original_put(**{**kwargs, "Metadata": {}})

        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(self.destination, "put_object", side_effect=drop_metadata),
            self.assertRaisesRegex(
                fixture.migration.MigrationError,
                "different encryption, size, or metadata",
            ),
        ):
            fixture.migration.execute(
                self.plan(),
                self.source,
                self.destination,
                Path(folder) / "manifest",
                Path(folder) / "map",
            )

    def test_final_parity_catches_tag_or_content_setting_drift(self) -> None:
        self.source.add(
            self.key,
            b"body",
            "v1",
            fixture.START,
            ContentType="text/plain",
            CacheControl="max-age=60",
            TagSet=[{"Key": "purpose", "Value": "test"}],
        )
        plan = self.plan()
        with tempfile.TemporaryDirectory() as folder:
            fixture.migration.execute(
                plan,
                self.source,
                self.destination,
                Path(folder) / "manifest",
                Path(folder) / "map",
            )
        copied = self.destination.entries[0]["fields"]
        copied["TagSet"] = [{"Key": "purpose", "Value": "other"}]
        with self.assertRaisesRegex(
            fixture.migration.MigrationError, "different object tags"
        ):
            fixture.migration.verify_complete(plan, self.source, self.destination)
        copied["TagSet"] = [{"Key": "purpose", "Value": "test"}]
        copied["CacheControl"] = "max-age=120"
        with self.assertRaisesRegex(
            fixture.migration.MigrationError, "different content settings"
        ):
            fixture.migration.verify_complete(plan, self.source, self.destination)


if __name__ == "__main__":
    unittest.main()
