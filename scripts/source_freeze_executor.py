"""Reversible freeze plan with a source-account mutation guard.

It can capture a private read-only source snapshot, rehearse staged controls on
fixtures or explicitly allowlisted disposable AWS resources, and restore them
while refusing drift. Live source execution remains disabled.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from _source_freeze_plan import (
    STAGES,
    Control,
    FreezePlanError,
    Ref,
    build_controls,
    canonical,
    refs,
    validate_preflight,
)
from _source_writer_preflight_core import SOURCE_ACCOUNT

REPO_ROOT = Path(__file__).resolve().parents[1]
GATES = {
    "ingress": set(),
    "consumers": {"queues_drained", "runtime_sessions_drained"},
    "retention": {"application_ingress_closed_mail_capture_open", "consumers_stopped"},
    "storage": {
        "ttl_settled",
        "lifecycle_settled",
        "store_only_mail_capture_rechecked",
        "presigned_600s_elapsed",
        "memory_extraction_settled",
    },
}
PERMANENT_NO_GO = (
    "source_account_mutation_guard_active",
    "agentcore_ingest_data_deny_unproven",
    "agentcore_managed_extraction_and_event_expiry_unpausable",
    "provider_retry_and_webhook_routing_external",
    "auxiliary_and_unmanaged_writers_require_review",
    "production_denial_probes_not_run",
    "idempotent_mail_replay_not_verified",
)


class FixtureAdapter(Protocol):
    kind: str
    account: str

    def read(self, ref: Ref) -> Any: ...

    def write(self, ref: Ref, expected: Any, value: Any) -> None: ...


@dataclass(frozen=True)
class Snapshot:
    manifest: dict[str, Any]
    preflight_sha256: str
    observed: dict[str, Any]

    def data(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "manifest": self.manifest,
            "preflight_sha256": self.preflight_sha256,
            "observed": self.observed,
        }

    def digest(self) -> str:
        import hashlib

        return hashlib.sha256(canonical(self.data()).encode()).hexdigest()


def capture(
    adapter: FixtureAdapter, manifest: dict[str, Any], evidence: dict[str, Any]
) -> Snapshot:
    if adapter.account != manifest.get("account"):
        raise FreezePlanError("adapter account differs from manifest")
    digest = validate_preflight(manifest, evidence)
    observed = {ref.key: adapter.read(ref) for ref in refs(manifest)}
    build_controls(manifest, observed)
    return Snapshot(manifest, digest, observed)


def _private_path(path: Path) -> Path:
    path = path.resolve()
    if path.is_relative_to(REPO_ROOT):
        raise FreezePlanError("private freeze evidence must be outside the repository")
    return path


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path = _private_path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())


def _replace_private(path: Path, value: dict[str, Any]) -> None:
    path = _private_path(path)
    temporary = path.with_name(path.name + ".next")
    _write_new(temporary, value)
    os.replace(temporary, path)


def save_snapshot(path: Path, snapshot: Snapshot) -> None:
    _write_new(path, snapshot.data())


def _load_saved_snapshot(path: Path, expected: Snapshot) -> None:
    path = _private_path(path)
    if path.stat().st_mode & 0o077:
        raise FreezePlanError("snapshot permissions are too broad")
    if json.loads(path.read_text()) != expected.data():
        raise FreezePlanError("persisted snapshot differs from active plan")


def _journal(path: Path, snapshot: Snapshot) -> dict[str, Any]:
    path = _private_path(path)
    if not path.exists():
        value = {"snapshot_sha256": snapshot.digest(), "applied": [], "pending": None}
        _write_new(path, value)
        return value
    if path.stat().st_mode & 0o077:
        raise FreezePlanError("journal permissions are too broad")
    value = json.loads(path.read_text())
    if value.get("snapshot_sha256") != snapshot.digest():
        raise FreezePlanError("journal belongs to another snapshot")
    if not isinstance(value.get("applied"), list):
        raise FreezePlanError("journal is malformed")
    return value


def _mutation_guard(adapter: FixtureAdapter, snapshot: Snapshot) -> None:
    if snapshot.manifest["account"] == SOURCE_ACCOUNT:
        raise FreezePlanError("live source mutation is disabled")
    if adapter.account != snapshot.manifest["account"]:
        raise FreezePlanError("adapter account differs from saved snapshot")
    if adapter.kind == "fixture":
        return
    if adapter.kind != "aws-disposable" or not getattr(
        adapter, "allow_disposable_writes", False
    ):
        raise FreezePlanError(
            "AWS writes require an exact disposable resource allowlist"
        )


def _controls(snapshot: Snapshot) -> list[Control]:
    return build_controls(snapshot.manifest, snapshot.observed)


def _stage_complete(stage: str, controls: list[Control], applied: set[str]) -> bool:
    return all(c.ref.key in applied for c in controls if c.ref.stage == stage)


def execute_stage(
    adapter: FixtureAdapter,
    snapshot: Snapshot,
    snapshot_path: Path,
    journal_path: Path,
    stage: str,
    attestations: set[str] = frozenset(),
) -> dict[str, Any]:
    """Apply one stage; persist intent before each write and stop on drift."""
    _mutation_guard(adapter, snapshot)
    _load_saved_snapshot(snapshot_path, snapshot)
    if stage not in STAGES:
        raise FreezePlanError("unknown stage")
    controls = _controls(snapshot)
    mail_rule = next(c for c in controls if c.ref.key == "ses_receipt")
    if adapter.read(mail_rule.ref) != mail_rule.before:
        raise FreezePlanError("store-only SES receipt rule drifted after capture")
    journal = _journal(journal_path, snapshot)
    applied = set(journal["applied"])
    preceding = STAGES[: STAGES.index(stage)]
    if any(not _stage_complete(previous, controls, applied) for previous in preceding):
        raise FreezePlanError("preceding stage incomplete")
    if not GATES[stage] <= attestations:
        raise FreezePlanError("required drain or settling attestation missing")
    for control in (c for c in controls if c.ref.stage == stage):
        key = control.ref.key
        current = adapter.read(control.ref)
        if key in applied:
            if current != control.after:
                raise FreezePlanError(f"{key} drifted after application")
            continue
        if current == control.after and journal["pending"] == key:
            journal["pending"] = None
        elif current != control.before:
            raise FreezePlanError(f"{key} changed after snapshot")
        elif current != control.after:
            journal["pending"] = key
            _replace_private(journal_path, journal)
            adapter.write(control.ref, control.before, control.after)
            if adapter.read(control.ref) != control.after:
                raise FreezePlanError(f"{key} write not verified; inspect pending step")
            journal["pending"] = None
        applied.add(key)
        journal["applied"] = sorted(applied)
        _replace_private(journal_path, journal)
    return {
        "stage": stage,
        "stage_complete": True,
        "freeze_status": "NO_GO",
        "remaining_blockers": PERMANENT_NO_GO,
    }


def restore(
    adapter: FixtureAdapter,
    snapshot: Snapshot,
    snapshot_path: Path,
    journal_path: Path,
) -> dict[str, Any]:
    """Restore attempted controls in reverse order; never overwrite drift."""
    _mutation_guard(adapter, snapshot)
    _load_saved_snapshot(snapshot_path, snapshot)
    journal = _journal(journal_path, snapshot)
    controls = _controls(snapshot)
    attempted = set(journal["applied"])
    if journal.get("pending"):
        attempted.add(journal["pending"])
    for control in reversed(controls):
        key = control.ref.key
        if key not in attempted:
            continue
        current = adapter.read(control.ref)
        if current == control.before:
            pass
        elif current == control.after:
            adapter.write(control.ref, control.after, control.before)
            if adapter.read(control.ref) != control.before:
                raise FreezePlanError(f"{key} restore not verified")
        else:
            raise FreezePlanError(f"{key} drifted; restore halted")
        attempted.remove(key)
        journal["applied"] = sorted(attempted)
        journal["pending"] = None
        _replace_private(journal_path, journal)
    return {"restored": not attempted, "freeze_status": "NO_GO"}
