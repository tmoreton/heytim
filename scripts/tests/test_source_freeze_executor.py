"""Fixture tests for staged source-freeze planning and reversible execution."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _source_freeze_plan import FreezePlanError, Ref, refs
from _source_writer_preflight_core import SOURCE_REGION, fingerprint
from source_freeze_executor import capture, execute_stage, restore, save_snapshot

FIXTURE_ACCOUNT = "820323452649"


def manifest(account: str = FIXTURE_ACCOUNT) -> dict:
    return {
        "account": account,
        "region": SOURCE_REGION,
        "buckets": {
            "legacy_files": "fixture-legacy",
            "files": "fixture-files",
            "runtime_files": "fixture-runtime",
            "inbound_mail": "fixture-mail",
        },
        "tables": {
            label: {
                "name": f"fixture-{label}",
                "arn": f"arn:aws:dynamodb:{SOURCE_REGION}:{account}:table/fixture-{label}",
            }
            for label in ("application", "invite")
        },
        "lambdas": {
            label: f"fixture-{label}"
            for label in (
                "api",
                "public_api",
                "plaid_webhook",
                "pre_signup",
                "email_receiver",
                "autofix_dispatcher",
                "worker",
                "email_sender",
            )
        },
        "mappings": {
            "worker": "fixture-worker-uuid",
            "email_sender": "fixture-mail-uuid",
        },
        "event_rules": {
            "catalog_rule": "fixture-catalog-rule",
            "public_availability_rule": "fixture-public-rule",
        },
        "schedules": [{"group": "fixture-group", "name": "fixture-schedule"}],
        "ses": {"rule_set": "fixture-rule-set", "rule_name": "fixture-receipt"},
        "agentcore": {
            label: f"arn:aws:bedrock-agentcore:{SOURCE_REGION}:{account}:{label}/fixture"
            for label in ("runtime", "endpoint", "memory")
        },
    }


def evidence(target: dict) -> dict:
    checks = []
    for label, name in target["buckets"].items():
        checks.append(
            {
                "label": "agentcore_runtime_bucket"
                if label == "runtime_files"
                else f"bucket_{label}",
                "id_sha256_12": fingerprint(name),
            }
        )
    for label, table in target["tables"].items():
        checks.append(
            {"label": f"table_{label}", "id_sha256_12": fingerprint(table["name"])}
        )
    for label, name in target["lambdas"].items():
        checks.append({"label": f"lambda_{label}", "id_sha256_12": fingerprint(name)})
    for label, name in target["event_rules"].items():
        checks.append({"label": label, "id_sha256_12": fingerprint(name)})
    for label, arn in target["agentcore"].items():
        checks.append({"label": f"agentcore_{label}", "id_sha256_12": fingerprint(arn)})
    for label, uuid in target["mappings"].items():
        checks.append(
            {
                "label": "queue_mapping",
                "function": label,
                "id_sha256_12": fingerprint(uuid),
            }
        )
    checks.extend(
        [
            {"label": "task_schedules", "count": len(target["schedules"])},
            {"label": "receipt_rule", "matching_source_rules": 1},
        ]
    )
    return {
        "source_account": target["account"],
        "source_region": target["region"],
        "checks": checks,
    }


def initial(ref: Ref) -> object:
    if ref.kind == "bucket_lifecycle":
        return (
            None
            if ref.identity["name"] == "fixture-mail"
            else {
                "Rules": [
                    {"ID": "expire", "Status": "Enabled", "Expiration": {"Days": 30}}
                ]
            }
        )
    if ref.kind.endswith("policy"):
        return None
    if ref.kind == "table_ttl":
        return {"status": "ENABLED", "attribute": "expiresAt"}
    if ref.kind == "lambda_concurrency":
        return (
            10
            if ref.identity["name"] in {"fixture-worker", "fixture-email_sender"}
            else None
        )
    if ref.kind == "queue_mapping":
        return True
    if ref.kind == "event_rule":
        return "ENABLED"
    if ref.kind == "schedule":
        return {
            "Name": ref.identity["name"],
            "GroupName": ref.identity["group"],
            "State": "ENABLED",
            "ScheduleExpression": "rate(1 hour)",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "Target": {"Arn": "fixture-target", "RoleArn": "fixture-role"},
        }
    if ref.kind == "ses_rule":
        return {
            "Name": ref.identity["rule_name"],
            "Enabled": True,
            "Recipients": ["fixture@example.invalid"],
            "Actions": [{"S3Action": {"BucketName": "fixture-mail"}}],
        }
    raise AssertionError(ref.kind)


class FakeAdapter:
    kind = "fixture"

    def __init__(self, target: dict):
        self.account = target["account"]
        self.state = {ref.key: initial(ref) for ref in refs(target)}
        self.writes: list[str] = []
        self.fail_key: str | None = None

    def read(self, ref: Ref) -> object:
        return copy.deepcopy(self.state[ref.key])

    def write(self, ref: Ref, expected: object, value: object) -> None:
        if ref.key == self.fail_key:
            raise RuntimeError("fixture write failed")
        assert self.state[ref.key] == expected
        self.state[ref.key] = copy.deepcopy(value)
        self.writes.append(ref.key)


def paths(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "private-snapshot.json", tmp_path / "private-journal.json"


def test_all_stages_restore_original_settings_and_remain_no_go(tmp_path: Path) -> None:
    target = manifest()
    adapter = FakeAdapter(target)
    before = copy.deepcopy(adapter.state)
    snapshot = capture(adapter, target, evidence(target))
    snapshot_path, journal_path = paths(tmp_path)
    save_snapshot(snapshot_path, snapshot)
    assert snapshot_path.stat().st_mode & 0o077 == 0

    result = execute_stage(adapter, snapshot, snapshot_path, journal_path, "ingress")
    assert result["freeze_status"] == "NO_GO"
    with pytest.raises(FreezePlanError, match="attestation"):
        execute_stage(adapter, snapshot, snapshot_path, journal_path, "consumers")
    execute_stage(
        adapter,
        snapshot,
        snapshot_path,
        journal_path,
        "consumers",
        {
            "queues_drained",
            "runtime_sessions_drained",
        },
    )
    execute_stage(
        adapter,
        snapshot,
        snapshot_path,
        journal_path,
        "retention",
        {
            "ingress_closed",
            "consumers_stopped",
        },
    )
    execute_stage(
        adapter,
        snapshot,
        snapshot_path,
        journal_path,
        "storage",
        {
            "ttl_settled",
            "lifecycle_settled",
            "ses_drained",
            "presigned_600s_elapsed",
            "memory_extraction_settled",
        },
    )
    assert all(
        adapter.state[f"policy_bucket_{label}"] is not None
        for label in target["buckets"]
    )
    assert all(
        adapter.state[f"policy_table_{label}"] is not None for label in target["tables"]
    )
    assert all(
        adapter.state[f"ttl_{label}"]["status"] == "DISABLED"
        for label in target["tables"]
    )
    assert all(
        adapter.state[f"mapping_{label}"] is False for label in target["mappings"]
    )
    assert all(adapter.state[f"lambda_{label}"] == 0 for label in target["lambdas"])
    assert all(
        adapter.state[f"event_{label}"] == "DISABLED" for label in target["event_rules"]
    )
    assert (
        adapter.state["schedule_fixture-group_fixture-schedule"]["State"] == "DISABLED"
    )
    assert adapter.state["ses_receipt"]["Enabled"] is False
    assert adapter.state["agentcore_runtime"] is not None
    assert adapter.state["agentcore_endpoint"] is not None
    assert adapter.state["agentcore_memory"] is not None
    assert restore(adapter, snapshot, snapshot_path, journal_path)["restored"]
    assert adapter.state == before
    assert json.loads(journal_path.read_text())["applied"] == []


def test_preflight_mismatch_and_source_account_block_mutation(tmp_path: Path) -> None:
    target = manifest()
    adapter = FakeAdapter(target)
    bad = evidence(target)
    bad["checks"][0]["id_sha256_12"] = "000000000000"
    with pytest.raises(FreezePlanError, match="did not bind"):
        capture(adapter, target, bad)
    assert adapter.writes == []

    target = manifest("188757775631")
    adapter = FakeAdapter(target)
    snapshot = capture(adapter, target, evidence(target))
    snapshot_path, journal_path = paths(tmp_path)
    save_snapshot(snapshot_path, snapshot)
    with pytest.raises(FreezePlanError, match="live source mutation is disabled"):
        execute_stage(adapter, snapshot, snapshot_path, journal_path, "ingress")
    assert adapter.writes == []


def test_uncertain_fixture_write_can_restore_without_overwriting_drift(
    tmp_path: Path,
) -> None:
    target = manifest()
    adapter = FakeAdapter(target)
    original = copy.deepcopy(adapter.state)
    snapshot = capture(adapter, target, evidence(target))
    snapshot_path, journal_path = paths(tmp_path)
    save_snapshot(snapshot_path, snapshot)
    adapter.fail_key = "lambda_api"
    with pytest.raises(RuntimeError, match="fixture write failed"):
        execute_stage(adapter, snapshot, snapshot_path, journal_path, "ingress")
    assert json.loads(journal_path.read_text())["pending"] == "lambda_api"
    adapter.fail_key = None
    assert restore(adapter, snapshot, snapshot_path, journal_path)["restored"]
    assert adapter.state == original

    execute_stage(adapter, snapshot, snapshot_path, journal_path, "ingress")
    adapter.state["lambda_api"] = 7
    with pytest.raises(FreezePlanError, match="drifted"):
        restore(adapter, snapshot, snapshot_path, journal_path)


def test_policy_merge_preserves_existing_statement_and_restore_absence(
    tmp_path: Path,
) -> None:
    target = manifest()
    adapter = FakeAdapter(target)
    existing = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ExistingReadGrant",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::fixture-files/*",
            }
        ],
    }
    adapter.state["policy_bucket_files"] = copy.deepcopy(existing)
    snapshot = capture(adapter, target, evidence(target))
    snapshot_path, journal_path = paths(tmp_path)
    save_snapshot(snapshot_path, snapshot)
    execute_stage(adapter, snapshot, snapshot_path, journal_path, "ingress")
    execute_stage(
        adapter,
        snapshot,
        snapshot_path,
        journal_path,
        "consumers",
        {
            "queues_drained",
            "runtime_sessions_drained",
        },
    )
    execute_stage(
        adapter,
        snapshot,
        snapshot_path,
        journal_path,
        "retention",
        {
            "ingress_closed",
            "consumers_stopped",
        },
    )
    execute_stage(
        adapter,
        snapshot,
        snapshot_path,
        journal_path,
        "storage",
        {
            "ttl_settled",
            "lifecycle_settled",
            "ses_drained",
            "presigned_600s_elapsed",
            "memory_extraction_settled",
        },
    )
    merged = adapter.state["policy_bucket_files"]
    assert merged["Statement"][0] == existing["Statement"][0]
    assert merged["Statement"][1]["Sid"] == "HeyTimSourceWriteFreeze"
    assert restore(adapter, snapshot, snapshot_path, journal_path)["restored"]
    assert adapter.state["policy_bucket_files"] == existing
    assert adapter.state["policy_bucket_legacy_files"] is None
