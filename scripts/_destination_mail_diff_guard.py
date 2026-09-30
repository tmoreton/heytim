"""Fail closed on unreviewed full-backend changes in a private CDK diff."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

RESOURCE = re.compile(r"^\[([+~-])\] (AWS::[A-Za-z0-9:]+) (\S+)")


def _reviewed_mail_change(kind: str, resource_type: str, path: str) -> bool:
    if kind == "+":
        return (
            path.startswith("FrogBotApp/BotEmailQuarantine")
            and resource_type in {"AWS::S3::Bucket", "AWS::S3::BucketPolicy"}
        ) or (
            path.startswith("FrogBotApp/BotEmailInboundCapture")
            and resource_type in {"AWS::SQS::Queue", "AWS::SQS::QueuePolicy"}
        ) or (
            path == "FrogBotApp/BotEmailInboundCaptureSubscription"
            and resource_type == "AWS::SNS::Subscription"
        )
    if kind == "~":
        return (
            resource_type == "AWS::CloudFormation::Stack"
            and path.startswith("FrogBotApp.NestedStack/")
        ) or (resource_type, path) in {
            ("AWS::Lambda::Function", "FrogBotApp/BotEmailReceiver"),
            ("AWS::SNS::Subscription", "FrogBotApp/BotEmailReceiver/IncomingBotMailTopic"),
            ("AWS::SES::ReceiptRule", "FrogBotApp/BotEmailReceiptRule"),
            ("AWS::IAM::Policy", "FrogBotApp/BotEmailSesDeliveryRole/DefaultPolicy"),
        }
    return False


def summarize(value: str) -> dict[str, object]:
    changes: Counter[str] = Counter()
    changed_types: Counter[str] = Counter()
    unrelated = False
    replacement = False
    for line in value.splitlines():
        match = RESOURCE.match(line)
        if match:
            changes[match.group(1)] += 1
            changed_types[f"{match.group(1)}:{match.group(2)}"] += 1
            if not _reviewed_mail_change(*match.groups()):
                unrelated = True
            if match.group(1) == "~" and line.rstrip().endswith(" replace"):
                replacement = True
        if "(requires replacement)" in line:
            replacement = True
    iam_changes = "IAM Statement Changes" in value
    blockers = []
    if changes["-"]:
        blockers.append("cloudformation_resource_removal")
    if replacement:
        blockers.append("cloudformation_resource_replacement")
    if iam_changes:
        # A reviewer must classify any policy change; the preview never
        # labels a widening safe based on a text rendering alone.
        blockers.append("iam_statement_change_requires_review")
    if unrelated:
        blockers.append("unreviewed_resource_change")
    if not changes:
        blockers.append("no_cloudformation_resource_diff_parsed")
    return {
        "status": "NO_GO" if blockers else "REVIEW_REQUIRED",
        "resource_changes": dict(sorted(changes.items())),
        "resource_types": dict(sorted(changed_types.items())),
        "blockers": blockers,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: _destination_mail_diff_guard.py <private-diff> <private-summary>", file=sys.stderr)
        return 2
    source, destination = map(Path, sys.argv[1:])
    if destination.exists() or source.stat().st_mode & 0o077:
        print("Diff or summary path is not private", file=sys.stderr)
        return 2
    result = summarize(source.read_text())
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    destination.chmod(0o600)
    return 3 if result["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
