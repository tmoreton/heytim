"""Sanitized read-only inventory of the bucket selected by source AgentCore."""

from __future__ import annotations

from typing import Any

from _source_writer_preflight_core import (
    ABSENT,
    BUCKET_DENY,
    NO_LIFECYCLE_CODES,
    NO_POLICY_CODES,
    NO_REPLICATION_CODES,
    SOURCE_ACCOUNT,
    SOURCE_REGION,
    Report,
    fingerprint,
    has_freeze_deny,
    read,
)


def inspect_runtime_bucket(
    report: Report, s3: Any, name: str | None, known_buckets: dict[str, str]
) -> None:
    if not name or not isinstance(name, str):
        report.block("agentcore_runtime_files_bucket_missing")
        return
    known_label = next(
        (label for label, known in known_buckets.items() if known == name), None
    )
    if known_label:
        report.add(
            "agentcore_runtime_bucket", state="KNOWN_STACK_BUCKET", source=known_label
        )
        return
    report.block("agentcore_runtime_bucket_outside_stack")
    owner = {"Bucket": name, "ExpectedBucketOwner": SOURCE_ACCOUNT}
    if read(report, "runtime_bucket_owner", lambda: s3.head_bucket(**owner)) is None:
        return
    location = read(
        report, "runtime_bucket_location", lambda: s3.get_bucket_location(**owner)
    )
    version = read(
        report, "runtime_bucket_versioning", lambda: s3.get_bucket_versioning(**owner)
    )
    lifecycle = read(
        report,
        "runtime_bucket_lifecycle",
        lambda: s3.get_bucket_lifecycle_configuration(**owner),
        NO_LIFECYCLE_CODES,
    )
    replication = read(
        report,
        "runtime_bucket_replication",
        lambda: s3.get_bucket_replication(**owner),
        NO_REPLICATION_CODES,
    )
    policy = read(
        report,
        "runtime_bucket_policy",
        lambda: s3.get_bucket_policy(**owner),
        NO_POLICY_CODES,
    )
    if any(x is None for x in (location, version, lifecycle, replication, policy)):
        return

    def count_versions() -> dict[str, int]:
        if not s3.can_paginate("list_object_versions"):
            raise ValueError("PaginatorUnavailable")
        counts = {
            "versions": 0,
            "delete_markers": 0,
            "users": 0,
            "groups": 0,
            "meme_templates": 0,
            "other": 0,
        }
        for page in s3.get_paginator("list_object_versions").paginate(**owner):
            versions = page.get("Versions", [])
            markers = page.get("DeleteMarkers", [])
            counts["versions"] += len(versions)
            counts["delete_markers"] += len(markers)
            for entry in (*versions, *markers):
                key = entry.get("Key", "")
                if key.startswith("users/"):
                    counts["users"] += 1
                elif key.startswith("groups/"):
                    counts["groups"] += 1
                elif key.startswith("meme-templates/"):
                    counts["meme_templates"] += 1
                else:
                    counts["other"] += 1
        return counts

    try:
        counts = read(report, "runtime_bucket_versions", count_versions)
    except ValueError:
        report.block("runtime_bucket_versions_unreadable")
        counts = None
    arn = f"arn:aws:s3:::{name}/*"
    frozen = policy is not ABSENT and has_freeze_deny(
        policy.get("Policy"), arn, BUCKET_DENY
    )
    lifecycle_rules = [] if lifecycle is ABSENT else lifecycle.get("Rules", [])
    replication_rules = (
        []
        if replication is ABSENT
        else replication.get("ReplicationConfiguration", {}).get("Rules", [])
    )
    enabled_lifecycle = sum(r.get("Status") == "Enabled" for r in lifecycle_rules)
    enabled_replication = sum(r.get("Status") == "Enabled" for r in replication_rules)
    region_matches = (
        location.get("LocationConstraint") or "us-east-1"
    ) == SOURCE_REGION
    report.add(
        "agentcore_runtime_bucket",
        state="OBSERVED",
        id_sha256_12=fingerprint(name),
        source_owner=True,
        region_matches=region_matches,
        versioning=version.get("Status", "Unversioned"),
        lifecycle_enabled=enabled_lifecycle,
        replication_enabled=enabled_replication,
        freeze_deny=frozen,
        version_counts=counts,
    )
    if not region_matches or not frozen or enabled_lifecycle or enabled_replication:
        report.block("agentcore_runtime_bucket_not_frozen")
    if version.get("Status") != "Enabled":
        report.block("agentcore_runtime_bucket_version_history_unavailable")
