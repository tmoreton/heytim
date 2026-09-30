import base64
import io
import json
import os
import unittest
from unittest.mock import patch

import handler
from botocore.exceptions import ClientError

ACCOUNT = "188757775631"
REGION = "us-east-1"
MEMORY_ID = "HeyTimProduction_HeyTimMemory-xeQPMmBQGC"
STREAM_ARN = f"arn:aws:kinesis:{REGION}:{ACCOUNT}:stream/heytim-memory-record-capture"


def make_record(event_type="MemoryRecordCreated", full=True, sequence="123"):
    event = {"eventType": event_type, "memoryId": MEMORY_ID}
    if event_type != "StreamingEnabled":
        event["memoryRecordId"] = "record-private"
    if event_type in ("MemoryRecordCreated", "MemoryRecordUpdated") and full:
        event["memoryRecordText"] = "sensitive text is never logged"
    raw = json.dumps({"memoryStreamEvent": event}).encode()
    record = {
        "eventID": f"shardId-000000000000:{sequence}",
        "eventSourceARN": STREAM_ARN,
        "awsRegion": REGION,
        "kinesis": {"sequenceNumber": sequence, "data": base64.b64encode(raw).decode()},
    }
    return record, raw


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        assert kwargs["ExpectedBucketOwner"] == ACCOUNT
        key = kwargs["Key"]
        if key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"},
                               "ResponseMetadata": {"HTTPStatusCode": 412}}, "PutObject")
        self.objects[key] = kwargs["Body"]

    def get_object(self, **kwargs):
        assert kwargs["ExpectedBucketOwner"] == ACCOUNT
        return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}


class CaptureTests(unittest.TestCase):
    def test_archive_exact_raw_and_idempotent_replay(self):
        record, raw = make_record()
        key, actual = handler.validate_record(record, ACCOUNT, REGION, MEMORY_ID, STREAM_ARN)
        self.assertEqual(actual, raw)
        self.assertEqual(key, handler.archive_key(STREAM_ARN, "shardId-000000000000", "123"))
        s3 = FakeS3()
        handler.archive_record(s3, "private-archive", ACCOUNT, key, raw)
        handler.archive_record(s3, "private-archive", ACCOUNT, key, raw)
        self.assertEqual(s3.objects[key], raw)

    def test_conflicting_replay_fails(self):
        s3 = FakeS3()
        key = "records/" + "a" * 64 + ".json"
        handler.archive_record(s3, "private-archive", ACCOUNT, key, b"first")
        with self.assertRaisesRegex(ValueError, "Conflicting archived"):
            handler.archive_record(s3, "private-archive", ACCOUNT, key, b"second")

    def test_missing_full_content_and_wrong_identity_fail(self):
        record, _ = make_record(full=False)
        with self.assertRaisesRegex(ValueError, "FULL_CONTENT"):
            handler.validate_record(record, ACCOUNT, REGION, MEMORY_ID, STREAM_ARN)
        record, _ = make_record()
        record["eventSourceARN"] = STREAM_ARN.replace(ACCOUNT, "820323452649")
        with self.assertRaisesRegex(ValueError, "Wrong Kinesis source"):
            handler.validate_record(record, ACCOUNT, REGION, MEMORY_ID, STREAM_ARN)

    def test_delete_and_activation_are_archived(self):
        for event_type in ("MemoryRecordDeleted", "StreamingEnabled"):
            record, raw = make_record(event_type=event_type)
            self.assertEqual(handler.validate_record(record, ACCOUNT, REGION, MEMORY_ID, STREAM_ARN)[1], raw)

    def test_lambda_rejects_wrong_account_before_s3_call(self):
        record, _ = make_record()
        context = type("Context", (), {"invoked_function_arn":
            "arn:aws:lambda:us-east-1:820323452649:function:wrong"})()
        environment = {"SOURCE_ACCOUNT": ACCOUNT, "SOURCE_REGION": REGION, "SOURCE_MEMORY_ID": MEMORY_ID,
                       "SOURCE_STREAM_ARN": STREAM_ARN, "ARCHIVE_BUCKET": "private-archive"}
        with patch.dict(os.environ, environment), self.assertRaisesRegex(ValueError, "Wrong Lambda account"):
            handler.lambda_handler({"Records": [record]}, context)


if __name__ == "__main__":
    unittest.main()
