"""Private, reviewed SES overlap reconciliation for the HeyTim account move.

Snapshot and plan have no persistent AWS writes. Apply, dispatch, and ack are
separate guarded steps so a crash can be retried from the marker and outbox.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from _bot_email_replay_apply import apply_group, apply_rejection, verify_rejection
from _bot_email_replay_aws import Account, capture_snapshot, read_private, write_private
from _bot_email_replay_dispatch import (
    _ack_ledger_key,
    acknowledge_message,
    dispatch_group,
    dispatch_import,
    verify_persisted,
)
from _bot_email_replay_imported import apply_import, verify_import
from _bot_email_replay_plan import (
    DESTINATION_ACCOUNT,
    SOURCE_ACCOUNT,
    ReplayError,
    reviewed_plan,
    validate_snapshot,
)
from botocore.exceptions import BotoCoreError, ClientError


def _profiles(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-profile", required=True)
    parser.add_argument("--destination-profile", required=True)


def _review(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)


def _write(parser: argparse.ArgumentParser) -> None:
    _review(parser)
    _profiles(parser)
    parser.add_argument("--expected-plan-digest", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    snapshot = actions.add_parser("snapshot", help="Capture an owner-only inventory; never delete queue messages")
    _profiles(snapshot)
    snapshot.add_argument("--source-app-stack", required=True)
    snapshot.add_argument("--source-capture-stack", required=True)
    snapshot.add_argument("--destination-app-stack", required=True)
    snapshot.add_argument("--destination-capture-stack", required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument("--max-messages", type=int, default=1000)
    plan = actions.add_parser("plan", help="Validate every per-recipient review decision offline")
    _review(plan)
    plan.add_argument("--output", type=Path, required=True)
    apply = actions.add_parser("apply", help="Copy selected MIME and atomically write replay state")
    _write(apply)
    status = actions.add_parser("status", help="Read replay, outbox, ack, and queue state without writes")
    _write(status)
    dispatch = actions.add_parser("dispatch", help="Resume automatic outbox delivery to the destination worker")
    _write(dispatch)
    dispatch.add_argument("--canonical-id", help="Optional one reviewed canonical UUID")
    ack = actions.add_parser("ack", help="Delete one captured SQS notification after transaction verification")
    _write(ack)
    ack.add_argument("--account", choices=(SOURCE_ACCOUNT, DESTINATION_ACCOUNT), required=True)
    ack.add_argument("--sqs-message-id", required=True)
    return parser


def _accounts(snapshot: dict, args: argparse.Namespace) -> dict[str, Account]:
    accounts = {}
    for account, profile in (
        (SOURCE_ACCOUNT, args.source_profile),
        (DESTINATION_ACCOUNT, args.destination_profile),
    ):
        details = snapshot["accounts"][account]
        instance = Account(
            profile=profile,
            expected_account=account,
            app_stack=details["appStack"],
            capture_stack=details["captureStack"],
        )
        instance.verify_manifest(details)
        accounts[account] = instance
    return accounts


def _reviewed(args: argparse.Namespace) -> tuple[dict, dict]:
    snapshot = read_private(args.snapshot)
    decisions = read_private(args.decisions)
    plan = reviewed_plan(snapshot, decisions)
    return snapshot, plan


def _expected(plan: dict, args: argparse.Namespace) -> None:
    if args.expected_plan_digest != plan["planDigest"]:
        raise ReplayError("Expected digest differs from the private reviewed plan")


def _approval(name: str) -> None:
    if os.environ.get(name) != "true":
        raise ReplayError(f"Set {name}=true for this guarded cutover step")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            source = Account(
                profile=args.source_profile,
                expected_account=SOURCE_ACCOUNT,
                app_stack=args.source_app_stack,
                capture_stack=args.source_capture_stack,
            )
            destination = Account(
                profile=args.destination_profile,
                expected_account=DESTINATION_ACCOUNT,
                app_stack=args.destination_app_stack,
                capture_stack=args.destination_capture_stack,
            )
            result = capture_snapshot(source, destination, args.max_messages)
            write_private(args.output, result)
            print({
                "snapshotDigest": result["snapshotDigest"],
                "notifications": len(result["messages"]),
                "observations": len(validate_snapshot(result)),
                "queueCountsAfter": result["queueCountsAfter"],
                "status": "INVENTORY_ONLY",
            })
            return 0
        snapshot, plan = _reviewed(args)
        if args.command == "plan":
            write_private(args.output, plan)
            print({
                "planDigest": plan["planDigest"],
                "reviewedDeliveries": len(plan["groups"]),
                "reviewedImports": len(plan["imports"]),
                "reviewedRejections": len(plan["rejects"]),
                "heldObservations": plan["holds"],
                "status": "REVIEWED_DRY_RUN_ONLY",
            })
            return 0
        _expected(plan, args)
        if args.command == "status":
            accounts = _accounts(snapshot, args)
            destination = accounts[DESTINATION_ACCOUNT]
            missing = 0
            pending = 0
            observed = 0
            for group in plan["groups"]:
                try:
                    _marker, _inbox, outbox = verify_persisted(snapshot, group, destination)
                except ReplayError:
                    missing += 1
                    continue
                if outbox:
                    pending += outbox.get("state") == "pending"
                    observed += outbox.get("state") == "observed"
            for imported in plan["imports"]:
                try:
                    _marker, _inbox, outbox = verify_import(snapshot, imported, accounts)
                except ReplayError:
                    missing += 1
                    continue
                if outbox:
                    pending += outbox.get("state") == "pending"
                    observed += outbox.get("state") == "observed"
            for rejection in plan["rejects"]:
                try:
                    verify_rejection(snapshot, rejection, accounts)
                except ReplayError:
                    missing += 1
            unacknowledged = 0
            for entry in snapshot["messages"]:
                key = _ack_ledger_key(entry["account"], entry["sqsMessageId"])
                receipt = destination.table.get_item(Key=key, ConsistentRead=True).get("Item")
                if not receipt or receipt.get("state") != "deleted":
                    unacknowledged += 1
            queues = {name: account.queue_counts() for name, account in accounts.items()}
            print({
                "status": "POINT_IN_TIME_ONLY",
                "reviewedDeliveries": len(plan["groups"]),
                "reviewedImports": len(plan["imports"]),
                "reviewedRejections": len(plan["rejects"]),
                "heldObservations": plan["holds"],
                "missingOrDivergentReplay": missing,
                "pendingAutomaticOutbox": pending,
                "observedAutomaticOutbox": observed,
                "unacknowledgedSnapshotNotifications": unacknowledged,
                "captureQueueCounts": queues,
            })
            return 0
        flag = {
            "apply": "HEYTIM_MAIL_REPLAY_APPLY_APPROVED",
            "dispatch": "HEYTIM_MAIL_REPLAY_DISPATCH_APPROVED",
            "ack": "HEYTIM_MAIL_REPLAY_ACK_APPROVED",
        }[args.command]
        _approval("HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED")
        _approval(flag)
        accounts = _accounts(snapshot, args)
        if args.command == "apply":
            completed = [apply_group(snapshot, group, accounts) for group in plan["groups"]]
            imported = [apply_import(snapshot, item, accounts) for item in plan["imports"]]
            rejected = [apply_rejection(snapshot, item, accounts) for item in plan["rejects"]]
            print({
                "recorded": len(completed),
                "alreadyImported": len(imported),
                "rejected": len(rejected),
                "automaticPending": sum(item["automaticPending"] for item in completed + imported),
                "heldObservations": plan["holds"],
                "status": "RECORDED_NOT_DISPATCHED_OR_ACKED",
            })
            return 0
        if args.command == "dispatch":
            if plan["holds"]:
                raise ReplayError("Held observations block automatic outbox dispatch")
            selected = [group for group in plan["groups"] if not args.canonical_id
                        or group["canonicalId"] == args.canonical_id]
            imported = [group for group in plan["imports"] if not args.canonical_id
                        or group["canonicalId"] == args.canonical_id]
            if args.canonical_id and len(selected) + len(imported) != 1:
                raise ReplayError("Canonical ID is absent from reviewed plan")
            states = [dispatch_group(snapshot, group, accounts[DESTINATION_ACCOUNT])
                      for group in selected]
            states.extend(dispatch_import(snapshot, group, accounts) for group in imported)
            print({"outboxStates": {state: states.count(state) for state in sorted(set(states))}})
            return 0
        entry = next((item for item in snapshot["messages"]
                      if item["account"] == args.account
                      and item["sqsMessageId"] == args.sqs_message_id), None)
        if entry is None:
            raise ReplayError("Requested SQS message is absent from private snapshot")
        state = acknowledge_message(snapshot, plan, entry, accounts)
        print({"acknowledgement": state})
        return 0
    except (ReplayError, BotoCoreError, ClientError, OSError, ValueError, KeyError) as error:
        # Never print SNS bodies, MIME, addresses, credentials, or AWS responses.
        detail = str(error) if isinstance(error, ReplayError) else type(error).__name__
        print({"status": "NO_GO", "error": detail}, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
