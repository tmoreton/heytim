"""Private, append-only evidence ledger for the HeyTim provider cutover.

This tool never calls a provider or AWS API and never authorizes a cutover. It
accepts metadata and evidence references only, not webhook bodies or tokens.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCE_ACCOUNT = "188757775631"
DESTINATION_ACCOUNT = "820323452649"
PROVIDERS = ("stripe", "github", "plaid")
SCOPES = ("provider", "provider-attempts", "source-ingress", "destination-ingress")
EFFECTS = {
    "stripe": ("owner-mapping", "stripe-marker", "billing-row"),
    "github": ("owner-mapping", "subscription-index", "queue-job", "group-message"),
    "plaid": ("owner-mapping", "item-mapping", "sync-row"),
}
NON_ACTIONABLE_EFFECT = "non-actionable-reviewed"
ID_PATTERN = re.compile(r"[A-Za-z0-9._:#-]{1,200}\Z")
REF_PATTERN = re.compile(r"[A-Za-z0-9._:/#-]{1,200}\Z")
EVENT_PATTERN = re.compile(r"[a-zA-Z0-9._:-]{1,120}\Z")
SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("A UTC timestamp is required")  # noqa: TRY004 - ledger input error
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("A UTC timestamp is required") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamp must be UTC")
    return parsed.astimezone(UTC)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _fields(record: dict, required: set[str], optional: set[str] = frozenset()) -> None:
    if set(record) - required - optional or required - set(record):
        raise ValueError("Record has missing or unapproved fields")


def _identity(provider: str, delivery_id: str, identity_kind: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError("Unknown provider")
    if provider == "stripe" and (identity_kind != "provider-id" or
                                  not re.fullmatch(r"evt_[A-Za-z0-9]{5,120}", delivery_id)):
        raise ValueError("Stripe requires its immutable event ID")
    if provider == "github" and (identity_kind != "provider-id" or
                                  not re.fullmatch(r"[A-Za-z0-9-]{8,128}", delivery_id)):
        raise ValueError("GitHub requires X-GitHub-Delivery")
    if provider == "plaid" and (identity_kind != "body-digest" or
                                 not SHA256_PATTERN.fullmatch(delivery_id)):
        raise ValueError("Plaid has no stable provider delivery ID; use an exact body digest")


def validate_record(record: dict, prior: list[dict]) -> None:
    if not isinstance(record, dict) or not isinstance(record.get("kind"), str):
        raise ValueError("Record must be a JSON object with kind")  # noqa: TRY004 - ledger input error
    kind = record["kind"]
    window = next((r for r in prior if r["kind"] == "window"), None)
    if kind == "window":
        _fields(record, {"kind", "startedAt", "sourceAccount", "destinationAccount",
                         "stripeEndpointId", "githubAppId"})
        if prior or record["sourceAccount"] != SOURCE_ACCOUNT or record["destinationAccount"] != DESTINATION_ACCOUNT:
            raise ValueError("Ledger is not empty or account IDs do not match")
        _utc(record["startedAt"])
        if record["stripeEndpointId"] != "we_1UHW7fA7YzCs1pRZGFtVDD4J" or record["githubAppId"] != "4931494":
            raise ValueError("Provider identity does not match reviewed cutover")
        return
    if window is None:
        raise ValueError("Initialize a window first")
    if kind == "boundary":
        _fields(record, {"kind", "name", "at", "reference"})
        if record["name"] not in {"source-stopped", "destination-started", "ended"}:
            raise ValueError("Unknown boundary")
        if any(r["kind"] == "boundary" and r["name"] == record["name"] for r in prior):
            raise ValueError("Boundary is immutable")
        at = _utc(record["at"])
        previous = {r["name"]: _utc(r["at"]) for r in prior if r["kind"] == "boundary"}
        if at < _utc(window["startedAt"]):
            raise ValueError("Boundary precedes window")
        if record["name"] == "destination-started" and ("source-stopped" not in previous or at < previous["source-stopped"]):
            raise ValueError("Source must stop before destination starts")
        if record["name"] == "ended" and ("destination-started" not in previous or at < previous["destination-started"]):
            raise ValueError("Destination must start before window ends")
    elif kind == "coverage":
        _fields(record, {"kind", "provider", "scope", "from", "through", "completeness", "method", "reference"})
        if record["provider"] not in PROVIDERS or record["scope"] not in SCOPES:
            raise ValueError("Invalid coverage provider or scope")
        if record["completeness"] not in {"complete", "partial", "unknown"}:
            raise ValueError("Invalid coverage conclusion")
        if record["method"] not in {"provider-api", "provider-dashboard", "aws-ingress", "operator-reconciliation"}:
            raise ValueError("Invalid coverage method")
        if record["scope"] in {"provider", "provider-attempts"} and record["method"] == "aws-ingress":
            raise ValueError("AWS ingress cannot prove a provider-side event or attempt inventory")
        if record["scope"] not in {"provider", "provider-attempts"} and record["method"] in {"provider-api", "provider-dashboard"}:
            raise ValueError("Provider history cannot prove AWS ingress coverage")
        if record["provider"] == "plaid" and record["scope"] in {"provider", "provider-attempts"} and record["method"] == "provider-api" and record["completeness"] == "complete":
            raise ValueError("Plaid has no complete provider delivery listing")
        if _utc(record["through"]) <= _utc(record["from"]):
            raise ValueError("Coverage interval is empty")
    elif kind == "delivery":
        _fields(record, {"kind", "provider", "id", "identityKind", "firstObservedAt",
                         "eventType", "expectedOwner", "effectExpected", "reference"})
        _identity(record["provider"], record["id"], record["identityKind"])
        if record["expectedOwner"] not in {"source", "destination", "unknown"}:
            raise ValueError("Owner must be resolved from a private mapping")
        if type(record["effectExpected"]) is not bool:
            raise ValueError("Effect expectation must be explicit")
        if not EVENT_PATTERN.fullmatch(record["eventType"]):
            raise ValueError("Invalid event type")
        _utc(record["firstObservedAt"])
        if any(r["kind"] == "delivery" and r["provider"] == record["provider"] and r["id"] == record["id"] for r in prior):
            raise ValueError("Immutable delivery ID already recorded")
    elif kind == "attempt":
        _fields(record, {"kind", "provider", "id", "attemptId", "receivedAt", "account", "httpStatus", "reference"})
        _require_delivery(record, prior)
        if record["account"] not in {SOURCE_ACCOUNT, DESTINATION_ACCOUNT}:
            raise ValueError("Attempt account is unreviewed")
        if not ID_PATTERN.fullmatch(record["attemptId"]):
            raise ValueError("Attempt ID is invalid")
        if record["httpStatus"] is not None and (type(record["httpStatus"]) is not int or not 100 <= record["httpStatus"] <= 599):
            raise ValueError("HTTP status is invalid")
        _utc(record["receivedAt"])
        if any(r["kind"] == "attempt" and r["provider"] == record["provider"] and r["id"] == record["id"] and r["attemptId"] == record["attemptId"] for r in prior):
            raise ValueError("Attempt ID already recorded")
    elif kind == "evidence":
        _fields(record, {"kind", "provider", "id", "effect", "account", "state", "reference"})
        _require_delivery(record, prior)
        if record["effect"] not in (*EFFECTS[record["provider"]], NON_ACTIONABLE_EFFECT) or record["account"] not in {SOURCE_ACCOUNT, DESTINATION_ACCOUNT}:
            raise ValueError("Evidence does not match provider or account")
        if record["state"] not in {"present", "absent", "unknown"}:
            raise ValueError("Evidence state is invalid")
    elif kind == "resolution":
        _fields(record, {"kind", "provider", "id", "outcome", "reference"})
        _require_delivery(record, prior)
        if record["outcome"] not in {"reconciled", "replayed", "migrated", "unresolved", "accepted-exception"}:
            raise ValueError("Invalid resolution")
    else:
        raise ValueError("Unknown ledger record")
    if not isinstance(record["reference"], str) or not REF_PATTERN.fullmatch(record["reference"]):
        raise ValueError("Use a non-sensitive evidence reference, not a payload or token")


def _require_delivery(record: dict, prior: list[dict]) -> None:
    if not any(r["kind"] == "delivery" and r["provider"] == record["provider"] and r["id"] == record["id"] for r in prior):
        raise ValueError("Record references an unknown delivery")


def _open_ledger(path: Path, create: bool) -> int:
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
        os.close(fd)
        raise ValueError("Ledger must be a private regular file with mode 0600")
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _read(fd: int) -> list[dict]:
    os.lseek(fd, 0, os.SEEK_SET)
    body = b""
    while chunk := os.read(fd, 1024 * 1024):
        body += chunk
        if len(body) > 64 * 1024 * 1024:
            raise ValueError("Ledger is too large")
    records: list[dict] = []
    previous = "0" * 64
    for index, raw in enumerate(body.splitlines(), 1):
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Ledger contains an incomplete record") from exc
        if set(envelope) != {"sequence", "previousSha256", "record", "sha256"} or envelope["sequence"] != index or envelope["previousSha256"] != previous:
            raise ValueError("Ledger chain is invalid")
        digest = hashlib.sha256(_canonical({key: envelope[key] for key in ("sequence", "previousSha256", "record")})).hexdigest()
        if envelope["sha256"] != digest:
            raise ValueError("Ledger record changed")
        validate_record(envelope["record"], records)
        records.append(envelope["record"])
        previous = digest
    if body and not body.endswith(b"\n"):
        raise ValueError("Ledger contains an incomplete record")
    return records


def append(path: Path, record: dict, *, create: bool = False) -> None:
    fd = _open_ledger(path, create)
    try:
        records = _read(fd)
        validate_record(record, records)
        previous = "0" * 64
        if records:
            os.lseek(fd, 0, os.SEEK_END)
            # The last line was verified above; use its committed digest.
            os.lseek(fd, 0, os.SEEK_SET)
            content = b""
            while chunk := os.read(fd, 1024 * 1024):
                content += chunk
            previous = json.loads(content.splitlines()[-1])["sha256"]
        envelope = {"sequence": len(records) + 1, "previousSha256": previous, "record": record}
        envelope["sha256"] = hashlib.sha256(_canonical(envelope)).hexdigest()
        os.lseek(fd, 0, os.SEEK_END)
        os.write(fd, _canonical(envelope) + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)


def load(path: Path) -> list[dict]:
    fd = _open_ledger(path, False)
    try:
        return _read(fd)
    finally:
        os.close(fd)


def _covered(records: list[dict], provider: str, scope: str, start: datetime, end: datetime) -> bool:
    intervals = sorted(
        ((_utc(r["from"]), _utc(r["through"])) for r in records
         if r["kind"] == "coverage" and r["provider"] == provider and r["scope"] == scope
         and r["completeness"] == "complete"),
        key=lambda pair: pair[0],
    )
    cursor = start
    for left, right in intervals:
        if left > cursor:
            return False
        cursor = max(cursor, right)
        if cursor >= end:
            return True
    return False


def report(records: list[dict]) -> dict:
    if not records or records[0]["kind"] != "window":
        raise ValueError("No cutover window")
    boundaries = {r["name"]: _utc(r["at"]) for r in records if r["kind"] == "boundary"}
    blockers: list[str] = []
    if "source-stopped" not in boundaries or "destination-started" not in boundaries or "ended" not in boundaries:
        blockers.append("window_boundaries_incomplete")
    start = _utc(records[0]["startedAt"])
    end = boundaries.get("ended")
    if end:
        for provider in PROVIDERS:
            for scope in SCOPES:
                if not _covered(records, provider, scope, start, end):
                    blockers.append(f"{provider}_{scope}_coverage_incomplete")
    deliveries = [r for r in records if r["kind"] == "delivery"]
    summaries = []
    for delivery in deliveries:
        provider, delivery_id = delivery["provider"], delivery["id"]
        related = [r for r in records if r.get("provider") == provider and r.get("id") == delivery_id]
        attempts = [r for r in related if r["kind"] == "attempt"]
        effects = [r for r in related if r["kind"] == "evidence" and r["account"] == DESTINATION_ACCOUNT and r["state"] == "present"]
        resolutions = [r for r in related if r["kind"] == "resolution"]
        missing = []
        if delivery["expectedOwner"] == "unknown":
            missing.append("owner_unresolved")
        outcome = resolutions[-1]["outcome"] if resolutions else "unresolved"
        required_account = SOURCE_ACCOUNT if outcome == "migrated" else DESTINATION_ACCOUNT
        if not any(r["account"] == required_account and r["httpStatus"] is not None and 200 <= r["httpStatus"] < 300 for r in attempts):
            missing.append("source_delivery_unproved" if outcome == "migrated" else "destination_delivery_unproved")
        required_effects = EFFECTS[provider] if delivery["effectExpected"] else (NON_ACTIONABLE_EFFECT,)
        for effect in required_effects:
            if not any(r["effect"] == effect for r in effects):
                missing.append(f"{effect}_unproved")
        if outcome not in {"reconciled", "replayed", "migrated"}:
            missing.append("resolution_unproved")
        if end and not start <= _utc(delivery["firstObservedAt"]) <= end:
            missing.append("observed_outside_window")
        if "source-stopped" in boundaries and any(
            r["account"] == SOURCE_ACCOUNT and _utc(r["receivedAt"]) > boundaries["source-stopped"] for r in attempts
        ):
            missing.append("source_received_after_stop")
        if "destination-started" in boundaries and any(
            r["account"] == DESTINATION_ACCOUNT and _utc(r["receivedAt"]) < boundaries["destination-started"] for r in attempts
        ):
            missing.append("destination_received_before_start")
        if missing:
            blockers.append(f"{provider}_{delivery_id}_unresolved")
        summaries.append({"provider": provider, "id": delivery_id, "missing": missing})
    if not deliveries:
        blockers.append("no_delivery_inventory_or_authoritative_zero_event_evidence")
    return {
        "status": "NO_GO" if blockers else "EVIDENCE_REVIEW_REQUIRED",
        "sourceAccount": SOURCE_ACCOUNT,
        "destinationAccount": DESTINATION_ACCOUNT,
        "windowStartedAt": records[0]["startedAt"],
        "windowEndedAt": next((r["at"] for r in records if r["kind"] == "boundary" and r["name"] == "ended"), None),
        "deliveryCount": len(deliveries),
        "deliveries": summaries,
        "blockers": sorted(set(blockers)),
        "note": "Evidence ledger only. Provider coverage and delivery outcomes require independent review; this is never a cutover authorization.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--started-at", required=True)
    record = commands.add_parser("record")
    record.add_argument("--json", type=Path, required=True, help="Mode-0600 file containing exactly one metadata-only record")
    commands.add_parser("report")
    args = parser.parse_args()
    try:
        if args.command == "init":
            append(args.ledger, {
                "kind": "window", "startedAt": args.started_at,
                "sourceAccount": SOURCE_ACCOUNT, "destinationAccount": DESTINATION_ACCOUNT,
                "stripeEndpointId": "we_1UHW7fA7YzCs1pRZGFtVDD4J", "githubAppId": "4931494",
            }, create=True)
            print("Private provider ledger initialized")
        elif args.command == "record":
            fd = os.open(args.json, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
                    raise ValueError("Input metadata file must have mode 0600")
                with os.fdopen(fd, "r") as stream:
                    fd = -1
                    value = json.load(stream)
            finally:
                if fd >= 0:
                    os.close(fd)
            append(args.ledger, value)
            print("Metadata record appended")
        else:
            print(json.dumps(report(load(args.ledger)), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Do not echo provider payloads, paths, or low-level error messages.
        print(f"Provider ledger failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
