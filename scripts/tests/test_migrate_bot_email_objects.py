from __future__ import annotations

import base64
import hashlib
import io
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import migrate_bot_email_objects as mail


class Body(io.BytesIO):
    def iter_chunks(self, chunk_size: int):
        while part := self.read(chunk_size):
            yield part


class SourceS3:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls: list[tuple[str, dict]] = []

    def get_object(self, **kwargs):
        self.calls.append(("get_object", kwargs))
        return {"Body": Body(self.data), "ContentLength": len(self.data)}


class DestinationS3(SourceS3):
    def put_object(self, **kwargs):
        self.calls.append(("put_object", kwargs))
        self.data = kwargs["Body"]


class MailMigrationTests(unittest.TestCase):
    def test_stack_bucket_identity_requires_one_exact_resource(self) -> None:
        resources = [
            {
                "ResourceType": "AWS::S3::Bucket",
                "LogicalResourceId": "IncomingBotMailAB12",
                "PhysicalResourceId": "source-mail",
            },
            {
                "ResourceType": "AWS::S3::Bucket",
                "LogicalResourceId": "UnrelatedBucketAB12",
                "PhysicalResourceId": "other",
            },
        ]
        self.assertEqual(
            mail._physical(resources, "AWS::S3::Bucket", "IncomingBotMail"),
            "source-mail",
        )
        with self.assertRaises(mail.MailMigrationError):
            mail._physical(
                resources + [resources[0]], "AWS::S3::Bucket", "IncomingBotMail"
            )

    def test_historical_raw_expiry_is_distinct_from_recent_loss(self) -> None:
        now = datetime(2026, 9, 29, tzinfo=UTC)
        old = (
            "INBOX#old",
            "old",
            "received/old",
            "bot",
            (now - timedelta(days=9)).isoformat(),
        )
        recent = (
            "INBOX#new",
            "new",
            "received/new",
            "bot",
            (now - timedelta(days=1)).isoformat(),
        )
        self.assertEqual(mail._raw_missing([old, recent], set(), now), (2, 1))
        self.assertEqual(
            mail._raw_missing([old, recent], {"received/new"}, now), (1, 0)
        )
        with self.assertRaises(mail.MailMigrationError):
            mail._raw_missing(
                [("INBOX#bad", "bad", "received/bad", "bot", "bad")], set(), now
            )

    def test_destination_only_copy_checks_source_and_destination_bytes(self) -> None:
        payload = b"From: example@example.test\r\n\r\nA test message"
        source = SourceS3(payload)
        destination = DestinationS3(b"")
        expected = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        mail._copy_one(
            source,
            destination,
            "source-mail",
            "destination-mail",
            "received/ses-id",
            expected,
        )
        self.assertEqual(destination.data, payload)
        self.assertEqual([name for name, _ in source.calls], ["get_object"])
        put = next(args for name, args in destination.calls if name == "put_object")
        self.assertEqual(put["ExpectedBucketOwner"], mail.DESTINATION_ACCOUNT)
        self.assertEqual(put["ServerSideEncryption"], "AES256")
        self.assertEqual(
            put["ChecksumSHA256"],
            base64.b64encode(hashlib.sha256(payload).digest()).decode(),
        )
        self.assertEqual(destination.calls[-1][0], "get_object")

    def test_copy_refuses_changed_source_before_destination_write(self) -> None:
        source = SourceS3(b"changed")
        destination = DestinationS3(b"")
        with self.assertRaises(mail.MailMigrationError):
            mail._copy_one(
                source,
                destination,
                "source-mail",
                "destination-mail",
                "received/ses-id",
                {"bytes": 7, "sha256": "0" * 64},
            )
        self.assertEqual(destination.calls, [])

    def test_plan_rejects_recent_missing_raw_and_conflicting_destination(self) -> None:
        rows = [("INBOX#id", "id", "received/id", "bot", "2026-09-29T00:00:00Z")]
        manifest = {
            "sourceRecentRowsMissingRaw": 0,
            "destinationExtraObjects": 0,
            "destinationDivergentObjects": 0,
            "destinationSevenDayLifecycle": True,
            "destinationObjectsMatching": 1,
            "sourceObjects": {"received/id": {}},
        }
        state = {"sourceRows": rows, "destinationRows": rows}
        mail._assert_plan(manifest, state, final=True)
        for changed in (
            {"sourceRecentRowsMissingRaw": 1},
            {"destinationExtraObjects": 1},
            {"destinationDivergentObjects": 1},
            {"destinationSevenDayLifecycle": False},
        ):
            with (
                self.subTest(changed=changed),
                self.assertRaises(mail.MailMigrationError),
            ):
                mail._assert_plan({**manifest, **changed}, state, final=True)
        with self.assertRaises(mail.MailMigrationError):
            mail._assert_plan(manifest, {**state, "destinationRows": []}, final=True)

    def test_apply_requires_digest_and_cutover_flag_before_cloud_access(self) -> None:
        args = [
            "--source-profile",
            "source",
            "--destination-profile",
            "destination",
            "--source-stack",
            "source-stack",
            "--destination-stack",
            "destination-stack",
            "--source-bucket",
            "source-mail",
            "--destination-bucket",
            "destination-mail",
            "--manifest",
            "/private/tmp/mail-test.json",
            "--apply",
        ]
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("boto3.Session") as session,
        ):
            self.assertEqual(mail.main(args), 1)
            session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
