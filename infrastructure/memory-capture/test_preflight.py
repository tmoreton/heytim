import io
import json
import unittest

import preflight


class FakeKinesis:
    def __init__(self, raw):
        self.raw = raw
        self.reads = 0

    def list_shards(self, **kwargs):
        return {"Shards": [{"ShardId": "shardId-000000000000"}]}

    def get_shard_iterator(self, **kwargs):
        return {"ShardIterator": "start"}

    def get_records(self, **kwargs):
        self.reads += 1
        if self.reads == 1:
            return {"Records": [{"SequenceNumber": "123", "Data": self.raw}],
                    "NextShardIterator": "next"}
        return {"Records": [], "NextShardIterator": "next", "MillisBehindLatest": 0}


class FakeS3:
    def __init__(self, raw):
        self.raw = raw

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.raw)}


class PreflightTests(unittest.TestCase):
    def test_wrong_account_fails_before_other_reads(self):
        class WrongAccountSession:
            def client(self, name):
                if name != "sts":
                    raise AssertionError("Other service must not be read")
                return type("Sts", (), {"get_caller_identity": lambda self: {"Account": "820323452649"}})()

        with self.assertRaisesRegex(RuntimeError, "Wrong AWS account"):
            preflight.check_configuration(WrongAccountSession())

    def test_exact_retained_archive_passes_without_claiming_no_loss(self):
        raw = json.dumps({"memoryStreamEvent": {"eventType": "StreamingEnabled",
                        "memoryId": preflight.MEMORY_ID}}).encode()
        result = preflight.verify_retained(FakeKinesis(raw), FakeS3(raw), "private", 10, 5)
        self.assertEqual(result["retainedRecordsArchived"], 1)
        self.assertFalse(result["strictNoLossProven"])

    def test_missing_or_changed_archive_fails(self):
        raw = json.dumps({"memoryStreamEvent": {"eventType": "StreamingEnabled",
                        "memoryId": preflight.MEMORY_ID}}).encode()
        with self.assertRaisesRegex(RuntimeError, "Archive mismatch"):
            preflight.verify_retained(FakeKinesis(raw), FakeS3(b"changed"), "private", 10, 5)

    def test_bounded_scan_fails_closed(self):
        raw = json.dumps({"memoryStreamEvent": {"eventType": "StreamingEnabled",
                        "memoryId": preflight.MEMORY_ID}}).encode()
        with self.assertRaisesRegex(RuntimeError, "count limit"):
            preflight.verify_retained(FakeKinesis(raw), FakeS3(raw), "private", 0, 5)

    def test_shard_rotation_during_scan_fails_closed(self):
        raw = json.dumps({"memoryStreamEvent": {"eventType": "StreamingEnabled",
                        "memoryId": preflight.MEMORY_ID}}).encode()

        class ChangingKinesis(FakeKinesis):
            def __init__(self, data):
                super().__init__(data)
                self.listings = 0

            def list_shards(self, **kwargs):
                self.listings += 1
                result = super().list_shards(**kwargs)
                if self.listings > 1:
                    result["Shards"].append({"ShardId": "shardId-000000000001"})
                return result

        with self.assertRaisesRegex(RuntimeError, "shards changed"):
            preflight.verify_retained(ChangingKinesis(raw), FakeS3(raw), "private", 10, 5)


if __name__ == "__main__":
    unittest.main()
