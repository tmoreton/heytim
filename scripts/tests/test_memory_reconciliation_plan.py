from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.tests.memory_migration_test_support import MemoryMigrationFixture, migration


SCRIPT = Path(__file__).resolve().parents[1] / "plan-agentcore-memory-reconciliation.py"
spec = importlib.util.spec_from_file_location("memory_reconciliation_plan", SCRIPT)
assert spec and spec.loader
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


class ReconciliationPlanTests(MemoryMigrationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        migrated = migration.apply_migration(
            self.source, self.destination, "source-memory", "dest-memory",
            self.original, self.actors, self.sessions, self.strategies,
        )
        self.manifest = {
            "actorIds": self.actors,
            "sessionIds": {"actor-old/session-old": "session-new"},
            "strategyIds": self.strategies,
            "eventIds": migrated["events"],
            "recordIds": migrated["records"],
            "recordHashes": migration.record_content_hashes(
                self.original["records"], self.actors, self.sessions, self.strategies
            ),
            "verifiedContentSha256": migrated["verifiedContentSha256"],
        }

    def snapshots(self):
        source = migration.inventory(self.source, "source-memory", list(self.strategies))
        destination = migration.inventory(self.destination, "dest-memory", list(self.strategies.values()))
        return copy.deepcopy(source), copy.deepcopy(destination)

    def test_late_create_update_delete_have_deterministic_read_only_plan(self):
        self.source.records[0]["content"] = {"text": "late managed revision"}
        self.source.records.pop(1)
        created = copy.deepcopy(self.source.records[0])
        created["memoryRecordId"] = "record-late"
        created["content"] = {"text": "new late fact"}
        self.source.records.append(created)
        source, destination = self.snapshots()
        before = copy.deepcopy(self.destination.records)
        first = planner.plan_reconciliation(source, destination, self.manifest)
        second = planner.plan_reconciliation(source, destination, self.manifest)
        self.assertEqual(first, second)
        self.assertEqual({kind: len(first["actions"][kind]) for kind in
                          ("create", "update", "delete", "conflict")},
                         {"create": 1, "update": 1, "delete": 1, "conflict": 0})
        self.assertEqual(self.destination.records, before)
        self.assertFalse(first["strictNoLossProven"])

    def test_destination_user_edit_is_conflict_not_overwritten(self):
        self.source.records[0]["content"] = {"text": "source managed revision"}
        destination_id = self.manifest["recordIds"]["record-1"]
        next(record for record in self.destination.records
             if record["memoryRecordId"] == destination_id)["content"] = {"text": "user edit"}
        source, destination = self.snapshots()
        result = planner.plan_reconciliation(source, destination, self.manifest)
        self.assertEqual(len(result["actions"]["conflict"]), 1)
        self.assertEqual(result["actions"]["conflict"][0]["reason"], "destination-diverged")

    def test_source_delete_with_changed_destination_is_conflict(self):
        self.source.records.pop(0)
        destination_id = self.manifest["recordIds"]["record-1"]
        next(record for record in self.destination.records
             if record["memoryRecordId"] == destination_id)["content"] = {"text": "user edit"}
        source, destination = self.snapshots()
        result = planner.plan_reconciliation(source, destination, self.manifest)
        self.assertEqual(len(result["actions"]["conflict"]), 1)

    def test_legacy_manifest_bootstraps_only_from_unchanged_destination(self):
        old = dict(self.manifest)
        old.pop("recordHashes")
        source, destination = self.snapshots()
        self.assertEqual(planner.plan_reconciliation(source, destination, old)["baselineRecordHashes"],
                         self.manifest["recordHashes"])
        self.destination.records.append({**copy.deepcopy(self.destination.records[0]),
                                         "memoryRecordId": "destination-owned"})
        source, destination = self.snapshots()
        with self.assertRaisesRegex(ValueError, "Legacy manifest cannot establish"):
            planner.plan_reconciliation(source, destination, old)

    def test_new_source_record_with_identical_destination_is_ambiguous(self):
        created = copy.deepcopy(self.source.records[0])
        created["memoryRecordId"] = "record-late"
        self.source.records.append(created)
        destination_copy = copy.deepcopy(self.destination.records[0])
        destination_copy["memoryRecordId"] = "destination-owned"
        self.destination.records.append(destination_copy)
        source, destination = self.snapshots()
        result = planner.plan_reconciliation(source, destination, self.manifest)
        self.assertEqual(result["actions"]["conflict"][0]["reason"],
                         "unmapped-identical-destination")

    def test_concurrent_managed_source_change_fails_snapshot_gate(self):
        source_before, destination_before = self.snapshots()
        self.source.records[0]["content"] = {"text": "changed during scan"}
        source_after, destination_after = self.snapshots()
        with self.assertRaisesRegex(ValueError, "Source changed during planning"):
            planner.verify_stable_snapshots(source_before, destination_before,
                                            source_after, destination_after)

    def test_concurrent_destination_change_fails_snapshot_gate(self):
        source_before, destination_before = self.snapshots()
        self.destination.records[0]["content"] = {"text": "destination changed"}
        source_after, destination_after = self.snapshots()
        with self.assertRaisesRegex(ValueError, "Destination changed during planning"):
            planner.verify_stable_snapshots(source_before, destination_before,
                                            source_after, destination_after)

    def test_wrong_account_stops_before_memory_reads(self):
        class Session:
            def __init__(self, **kwargs):
                pass

            def client(self, service, **kwargs):
                if service != "sts":
                    raise AssertionError("Memory must not be read from wrong account")
                return type("Sts", (), {"get_caller_identity": lambda self: {"Account": "820323452649"}})()

        with patch.object(planner.boto3, "Session", Session):
            with self.assertRaisesRegex(ValueError, "unexpected account"):
                planner.verified_clients("source", "destination")

    def test_completed_private_plan_retries_idempotently(self):
        source, destination = self.snapshots()
        plan = planner.plan_reconciliation(source, destination, self.manifest)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            planner.write_or_verify_plan(path, plan)
            planner.write_or_verify_plan(path, plan)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("private fact", path.read_text())
            changed = dict(plan)
            changed["alreadyConverged"] = -1
            with self.assertRaisesRegex(ValueError, "Existing private plan differs"):
                planner.write_or_verify_plan(path, changed)


if __name__ == "__main__":
    unittest.main()
