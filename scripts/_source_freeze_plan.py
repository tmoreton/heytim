"""Private, reversible control plan for a source-account freeze rehearsal.

The plan records full settings because thaw must restore absence as absence and
must preserve unrelated policy statements and schedule/receipt-rule fields.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from _source_mail_capture import validate_store_only_rule
from _source_writer_preflight_core import (
    BUCKET_DENY,
    FREEZE_SID,
    MEMORY_DENY,
    SOURCE_REGION,
    TABLE_DENY,
    fingerprint,
)

BUCKET_LABELS = {"legacy_files", "files", "runtime_files", "inbound_mail"}
QUARANTINE_BUCKET = "inbound_quarantine"
TABLE_LABELS = {"application", "invite"}
INGRESS_LAMBDAS = {
    "api",
    "public_api",
    "plaid_webhook",
    "pre_signup",
    "email_receiver",
    "autofix_dispatcher",
}
CONSUMER_LAMBDAS = {"worker", "email_sender"}
RULE_LABELS = {"catalog_rule", "public_availability_rule"}
AGENTCORE_LABELS = {"runtime", "endpoint", "memory"}
STAGES = ("ingress", "consumers", "retention", "storage")


class FreezePlanError(ValueError):
    """A plan cannot be applied or restored without human review."""


@dataclass(frozen=True)
class Ref:
    key: str
    kind: str
    stage: str
    identity: dict[str, str]


@dataclass(frozen=True)
class Control:
    ref: Ref
    before: Any
    after: Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _exact_keys(value: dict, required: set[str], label: str) -> None:
    if set(value) != required:
        raise FreezePlanError(f"{label} labels differ from reviewed inventory")


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("region") != SOURCE_REGION:
        raise FreezePlanError("unreviewed region")
    account = manifest.get("account")
    if not isinstance(account, str) or len(account) != 12 or not account.isdigit():
        raise FreezePlanError("invalid account")
    for key, required in (
        ("buckets", BUCKET_LABELS | {QUARANTINE_BUCKET}),
        ("tables", TABLE_LABELS),
        ("lambdas", INGRESS_LAMBDAS | CONSUMER_LAMBDAS),
        ("mappings", CONSUMER_LAMBDAS),
        ("event_rules", RULE_LABELS),
        ("agentcore", AGENTCORE_LABELS),
    ):
        value = manifest.get(key)
        if not isinstance(value, dict):
            raise FreezePlanError(f"{key} missing")
        _exact_keys(value, required, key)
    if len(set(manifest["buckets"].values())) != 5:
        raise FreezePlanError("bucket identities overlap")
    if len(set(manifest["lambdas"].values())) != 8:
        raise FreezePlanError("Lambda identities overlap")
    for table in manifest["tables"].values():
        if not isinstance(table, dict) or set(table) != {"name", "arn"}:
            raise FreezePlanError("table identity incomplete")
        if f":{SOURCE_REGION}:{account}:" not in table["arn"]:
            raise FreezePlanError("table account or region mismatch")
    for arn in manifest["agentcore"].values():
        if f":{SOURCE_REGION}:{account}:" not in arn:
            raise FreezePlanError("AgentCore account or region mismatch")
    schedules = manifest.get("schedules")
    if not isinstance(schedules, list) or not schedules:
        raise FreezePlanError("schedule inventory empty")
    if len({(s.get("group"), s.get("name")) for s in schedules}) != len(schedules):
        raise FreezePlanError("schedule identities overlap")
    if any(not s.get("group") or not s.get("name") for s in schedules):
        raise FreezePlanError("schedule identity incomplete")
    receipt = manifest.get("ses")
    if not isinstance(receipt, dict) or set(receipt) != {"rule_set", "rule_name"}:
        raise FreezePlanError("SES identity incomplete")
    capture = manifest.get("mail_capture")
    required = {"topic_arn", "subscription_arn", "queue_arn", "failure_queue_arn", "role_arn"}
    if not isinstance(capture, dict) or set(capture) != required:
        raise FreezePlanError("store-only mail capture identity incomplete")
    if any(not isinstance(capture[label], str) or not capture[label] for label in required):
        raise FreezePlanError("store-only mail capture ARN malformed")
    for label in ("topic_arn", "subscription_arn"):
        if not capture[label].startswith(f"arn:aws:sns:{SOURCE_REGION}:{account}:"):
            raise FreezePlanError(f"mail capture {label} account or region mismatch")
    for label in ("queue_arn", "failure_queue_arn"):
        if not capture[label].startswith(f"arn:aws:sqs:{SOURCE_REGION}:{account}:"):
            raise FreezePlanError(f"mail capture {label} account or region mismatch")
    if not capture["role_arn"].startswith(f"arn:aws:iam::{account}:role/"):
        raise FreezePlanError("mail capture SES role account mismatch")


def validate_preflight(manifest: dict[str, Any], evidence: dict[str, Any]) -> str:
    """Bind private physical IDs to the sanitized inventory before snapshotting."""
    validate_manifest(manifest)
    if (evidence.get("source_account"), evidence.get("source_region")) != (
        manifest["account"],
        manifest["region"],
    ):
        raise FreezePlanError("preflight identity mismatch")
    checks = evidence.get("checks")
    if not isinstance(checks, list):
        raise FreezePlanError("preflight checks missing")

    def must_match(label: str, identity: str) -> None:
        if not any(
            c.get("label") == label and c.get("id_sha256_12") == fingerprint(identity)
            for c in checks
        ):
            raise FreezePlanError(f"preflight did not bind {label}")

    for label, name in manifest["buckets"].items():
        must_match(
            "agentcore_runtime_bucket"
            if label == "runtime_files"
            else f"bucket_{label}",
            name,
        )
    for label, table in manifest["tables"].items():
        must_match(f"table_{label}", table["name"])
    for label, name in manifest["lambdas"].items():
        must_match(f"lambda_{label}", name)
    for label, name in manifest["event_rules"].items():
        must_match(label, name)
    for label, arn in manifest["agentcore"].items():
        must_match(f"agentcore_{label}", arn)
    for label, uuid in manifest["mappings"].items():
        if not any(
            c.get("label") == "queue_mapping"
            and c.get("function") == label
            and c.get("id_sha256_12") == fingerprint(uuid)
            for c in checks
        ):
            raise FreezePlanError(f"preflight did not bind {label} mapping")
    if not any(
        c.get("label") == "task_schedules"
        and c.get("count") == len(manifest["schedules"])
        for c in checks
    ):
        raise FreezePlanError("schedule count differs from preflight")
    if not any(
        c.get("label") == "receipt_rule"
        and c.get("matching_source_rules") == 1
        and c.get("enabled") == 1
        for c in checks
    ):
        raise FreezePlanError("store-only SES rule not uniquely observed")
    capture = manifest["mail_capture"]
    expected_hashes = {
        "bucket_sha256_12": fingerprint(manifest["buckets"][QUARANTINE_BUCKET]),
        **{f"{key}_sha256_12": fingerprint(value) for key, value in capture.items()},
    }
    if not any(
        c.get("label") == "mail_capture"
        and c.get("state") == "READY"
        and all(c.get(key) == value for key, value in expected_hashes.items())
        for c in checks
    ):
        raise FreezePlanError("store-only mail capture not bound to preflight")
    return hashlib.sha256(canonical(evidence).encode()).hexdigest()


def refs(manifest: dict[str, Any]) -> list[Ref]:
    validate_manifest(manifest)
    items: list[Ref] = []
    for label in sorted(RULE_LABELS):
        items.append(
            Ref(
                f"event_{label}",
                "event_rule",
                "ingress",
                {"name": manifest["event_rules"][label]},
            )
        )
    for schedule in manifest["schedules"]:
        items.append(
            Ref(
                f"schedule_{schedule['group']}_{schedule['name']}",
                "schedule",
                "ingress",
                schedule,
            )
        )
    items.append(Ref("ses_receipt", "ses_rule", "ingress", {
        **manifest["ses"],
        "capture_bucket": manifest["buckets"][QUARANTINE_BUCKET],
        "topic_arn": manifest["mail_capture"]["topic_arn"],
        "role_arn": manifest["mail_capture"]["role_arn"],
    }))
    for label in sorted(INGRESS_LAMBDAS):
        items.append(
            Ref(
                f"lambda_{label}",
                "lambda_concurrency",
                "ingress",
                {"name": manifest["lambdas"][label]},
            )
        )
    for label in ("runtime", "endpoint"):
        items.append(
            Ref(
                f"agentcore_{label}",
                "agentcore_policy",
                "ingress",
                {"arn": manifest["agentcore"][label], "role": label},
            )
        )
    for label in sorted(CONSUMER_LAMBDAS):
        items.append(
            Ref(
                f"mapping_{label}",
                "queue_mapping",
                "consumers",
                {"uuid": manifest["mappings"][label]},
            )
        )
    for label in sorted(CONSUMER_LAMBDAS):
        items.append(
            Ref(
                f"lambda_{label}",
                "lambda_concurrency",
                "consumers",
                {"name": manifest["lambdas"][label]},
            )
        )
    for label in sorted(TABLE_LABELS):
        table = manifest["tables"][label]
        items.append(Ref(f"ttl_{label}", "table_ttl", "retention", table))
    for label in sorted(BUCKET_LABELS):
        items.append(
            Ref(
                f"lifecycle_{label}",
                "bucket_lifecycle",
                "retention",
                {"name": manifest["buckets"][label]},
            )
        )
    items.append(Ref(
        "lifecycle_inbound_quarantine", "bucket_lifecycle", "retention",
        {"name": manifest["buckets"][QUARANTINE_BUCKET]},
    ))
    for label in sorted(BUCKET_LABELS):
        items.append(
            Ref(
                f"policy_bucket_{label}",
                "bucket_policy",
                "storage",
                {"name": manifest["buckets"][label]},
            )
        )
    for label in sorted(TABLE_LABELS):
        items.append(
            Ref(
                f"policy_table_{label}",
                "table_policy",
                "storage",
                manifest["tables"][label],
            )
        )
    items.append(
        Ref(
            "agentcore_memory",
            "agentcore_policy",
            "storage",
            {"arn": manifest["agentcore"]["memory"], "role": "memory"},
        )
    )
    if len({item.key for item in items}) != len(items):
        raise FreezePlanError("control keys overlap")
    return items


def _append_deny(existing: Any, arn: str, actions: set[str]) -> dict:
    policy = (
        copy.deepcopy(existing)
        if existing is not None
        else {"Version": "2012-10-17", "Statement": []}
    )
    if not isinstance(policy, dict):
        raise FreezePlanError("policy is not a JSON object")
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or any(
        not isinstance(s, dict) for s in statements
    ):
        raise FreezePlanError("policy statements malformed")
    if any(s.get("Sid") == FREEZE_SID for s in statements):
        raise FreezePlanError("freeze Sid already exists")
    statements.append(
        {
            "Sid": FREEZE_SID,
            "Effect": "Deny",
            "Principal": "*",
            "Action": sorted(actions),
            "Resource": arn,
        }
    )
    policy["Statement"] = statements
    if len(canonical(policy).encode()) > 20_000:
        raise FreezePlanError("merged policy exceeds conservative 20 KB limit")
    return policy


def desired(ref: Ref, before: Any) -> Any:
    kind = ref.kind
    if kind == "bucket_lifecycle":
        if before is None:
            return None
        after = copy.deepcopy(before)
        if not isinstance(after, dict) or not isinstance(after.get("Rules"), list):
            raise FreezePlanError(f"{ref.key} lifecycle malformed")
        for rule in after["Rules"]:
            rule["Status"] = "Disabled"
        return after
    if kind == "bucket_policy":
        return _append_deny(
            before, f"arn:aws:s3:::{ref.identity['name']}/*", BUCKET_DENY
        )
    if kind == "table_ttl":
        if not isinstance(before, dict) or before.get("status") not in {
            "ENABLED",
            "DISABLED",
        }:
            raise FreezePlanError(f"{ref.key} TTL transitional or unknown")
        if before["status"] == "ENABLED" and not before.get("attribute"):
            raise FreezePlanError(f"{ref.key} TTL attribute missing")
        return {"status": "DISABLED", "attribute": before.get("attribute")}
    if kind == "table_policy":
        return _append_deny(before, ref.identity["arn"], TABLE_DENY)
    if kind == "lambda_concurrency":
        if before is not None and (not isinstance(before, int) or before < 0):
            raise FreezePlanError(f"{ref.key} concurrency malformed")
        if ref.key == "lambda_email_receiver" and before != 0:
            raise FreezePlanError("mail receiver must already be held at zero")
        return 0
    if kind == "queue_mapping":
        if not isinstance(before, bool):
            raise FreezePlanError(f"{ref.key} mapping state unknown")
        return False
    if kind == "event_rule":
        if before not in {"ENABLED", "DISABLED"}:
            raise FreezePlanError(f"{ref.key} rule state unknown")
        return "DISABLED"
    if kind == "schedule":
        if not isinstance(before, dict) or before.get("State") not in {
            "ENABLED",
            "DISABLED",
        }:
            raise FreezePlanError(f"{ref.key} schedule malformed")
        after = copy.deepcopy(before)
        after["State"] = "DISABLED"
        return after
    if kind == "ses_rule":
        if not validate_store_only_rule(
            before,
            bucket=ref.identity["capture_bucket"],
            topic_arn=ref.identity["topic_arn"],
            role_arn=ref.identity["role_arn"],
        ):
            raise FreezePlanError("SES rule is not verified store-only capture")
        return copy.deepcopy(before)
    if kind == "agentcore_policy":
        actions = (
            MEMORY_DENY
            if ref.identity["role"] == "memory"
            else {"bedrock-agentcore:InvokeAgentRuntime*"}
        )
        return _append_deny(before, ref.identity["arn"], actions)
    raise FreezePlanError(f"unsupported control type: {kind}")


def build_controls(manifest: dict[str, Any], observed: dict[str, Any]) -> list[Control]:
    references = refs(manifest)
    if set(observed) != {ref.key for ref in references}:
        raise FreezePlanError("snapshot controls differ from manifest")
    return [
        Control(ref, copy.deepcopy(observed[ref.key]), desired(ref, observed[ref.key]))
        for ref in references
    ]
