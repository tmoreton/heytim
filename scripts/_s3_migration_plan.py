"""Private plan, inventory, and checkpoint helpers for the S3 migration CLI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CHUNK_SIZE = 8 * 1024 * 1024
ACCOUNT_ID = re.compile(r"^[0-9]{12}$")
KMS_ARN = re.compile(r"^arn:aws:kms:([a-z0-9-]+):([0-9]{12}):key/[^/]+$")
COPY_FIELDS = (
    "CacheControl",
    "ContentDisposition",
    "ContentEncoding",
    "ContentLanguage",
    "ContentType",
    "Expires",
    "WebsiteRedirectLocation",
)


class MigrationError(RuntimeError):
    """A safety check stopped the migration."""


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def write_private_json(path: Path, value: Any) -> None:
    """Atomically write a metadata-only checkpoint with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def load_private_json(path: Path) -> dict[str, Any]:
    if path.stat().st_mode & 0o077:
        raise MigrationError("Manifest permissions must be owner-only (0600).")
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise MigrationError("Manifest must be a JSON object.")
    return value


def load_key_map(path: Path | None) -> list[tuple[str, str]]:
    if path is None:
        return []
    if path.stat().st_mode & 0o077:
        raise MigrationError("Key map permissions must be owner-only (0600).")
    with path.open(encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise MigrationError("Key map must be an array of prefix mappings.")
    mappings: list[tuple[str, str]] = []
    for item in data:
        old = item.get("sourcePrefix")
        new = item.get("destinationPrefix")
        if not isinstance(old, str) or not isinstance(new, str) or not old or not new:
            raise MigrationError(
                "Every key map entry needs nonempty sourcePrefix and destinationPrefix."
            )
        if not old.endswith("/") or not new.endswith("/"):
            raise MigrationError("Mapped prefixes must end in '/'.")
        mappings.append((old, new))
    if len({old for old, _ in mappings}) != len(mappings):
        raise MigrationError("Duplicate source prefixes in key map.")
    return sorted(mappings, key=lambda pair: len(pair[0]), reverse=True)


def load_exact_keys(path: Path | None) -> list[str]:
    if path is None:
        return []
    if path.stat().st_mode & 0o077:
        raise MigrationError(
            "Exact-key allowlist permissions must be owner-only (0600)."
        )
    with path.open(encoding="utf-8") as source:
        keys = json.load(source)
    if (
        not isinstance(keys, list)
        or not keys
        or any(not isinstance(key, str) or not key for key in keys)
    ):
        raise MigrationError(
            "Exact-key allowlist must be a nonempty JSON array of keys."
        )
    if len(set(keys)) != len(keys):
        raise MigrationError("Exact-key allowlist contains duplicate keys.")
    return sorted(keys)


def destination_key(key: str, mappings: list[tuple[str, str]]) -> str:
    for old, new in mappings:
        if key.startswith(old):
            return new + key[len(old) :]
    return key


def validate_user_actor_mappings(
    source: list[dict[str, Any]],
    mappings: list[tuple[str, str]],
    source_users: dict[str, str],
    destination_users: dict[str, str],
) -> None:
    """Bind application-visible user paths to the verified Cognito identity map."""
    selected = {
        f"users/{item['sourceKey'].split('/', 2)[1]}/"
        for item in source
        if item["sourceKey"].startswith("users/")
    }
    if not selected:
        return
    expected = {}
    for email, old_subject in source_users.items():
        new_subject = destination_users.get(email)
        if new_subject is None:
            raise MigrationError("A source user has no verified destination identity.")
        old_actor = hashlib.sha256(f"user:{old_subject}".encode()).hexdigest()
        new_actor = hashlib.sha256(f"user:{new_subject}".encode()).hexdigest()
        expected[f"users/{old_actor}/"] = f"users/{new_actor}/"
    user_mappings = {old: new for old, new in mappings if old.startswith("users/")}
    if any(expected.get(old) != new for old, new in user_mappings.items()):
        raise MigrationError(
            "A user key mapping differs from verified Cognito actor identities."
        )
    if any(
        user_mappings.get(old) != expected.get(old) or old not in expected
        for old in selected
    ):
        raise MigrationError(
            "Selected user files lack the verified destination actor mapping."
        )


def inventory(
    client: Any,
    bucket: str,
    account: str,
    prefixes: list[str],
    exact_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return every version and marker, ordered oldest to newest per key."""
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    paginator = client.get_paginator("list_object_versions")
    selectors = [(prefix, False) for prefix in prefixes] + [
        (key, True) for key in (exact_keys or [])
    ]
    for prefix, exact in selectors:
        for page in paginator.paginate(
            Bucket=bucket, Prefix=prefix, ExpectedBucketOwner=account
        ):
            for field, is_delete in (("Versions", False), ("DeleteMarkers", True)):
                for item in page.get(field, []):
                    key = item["Key"]
                    if exact and key != prefix:
                        continue
                    identity = (key, item["VersionId"])
                    if identity in seen:
                        continue  # Overlapping prefix selections are intentional.
                    seen.add(identity)
                    by_key[key].append(
                        {
                            "sourceKey": key,
                            "sourceVersionId": item["VersionId"],
                            "deleteMarker": is_delete,
                            "lastModified": timestamp(item["LastModified"]),
                            "size": 0 if is_delete else item["Size"],
                            "isLatest": bool(item.get("IsLatest", False)),
                            "listingIndex": len(by_key[key]),
                        }
                    )
    ordered: list[dict[str, Any]] = []
    for key in sorted(by_key):
        versions = by_key[key]
        by_time: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for version in versions:
            by_time[version["lastModified"]].append(version)
        for tied in by_time.values():
            if len({item["deleteMarker"] for item in tied}) > 1:
                raise MigrationError(
                    "An object version and delete marker share a timestamp; "
                    "their order cannot be proven from ListObjectVersions."
                )
        # ListObjectVersions lists newest first for each item type. Reverse the
        # service order for ties of the same type; VersionId is not sortable.
        versions.sort(key=lambda item: (item["lastModified"], -item["listingIndex"]))
        if (
            sum(item["isLatest"] for item in versions) != 1
            or not versions[-1]["isLatest"]
        ):
            raise MigrationError("S3 version listing changed during inventory.")
        for version in versions:
            version.pop("listingIndex")
            version.pop("isLatest")
            ordered.append(version)
    return ordered


def make_plan(
    source: list[dict[str, Any]],
    scope: dict[str, Any],
    mappings: list[tuple[str, str]],
) -> dict[str, Any]:
    destination_sources: dict[str, str] = {}
    operations = []
    archive_prefix = scope.get("archivePrefix", "")
    for version in source:
        if not archive_prefix and version["sourceKey"].startswith("users/"):
            parts = version["sourceKey"].split("/", 2)
            if len(parts) < 3 or not re.fullmatch(r"[0-9a-f]{64}", parts[1]):
                raise MigrationError(
                    "A user object key does not have the expected hashed actor prefix."
                )
            actor_prefix = f"users/{parts[1]}/"
            if not any(
                old == actor_prefix and new != actor_prefix for old, new in mappings
            ):
                raise MigrationError(
                    "Every user actor needs an explicit destination prefix remap."
                )
        target = (
            archive_prefix + version["sourceKey"]
            if archive_prefix
            else destination_key(version["sourceKey"], mappings)
        )
        previous = destination_sources.setdefault(target, version["sourceKey"])
        if previous != version["sourceKey"]:
            raise MigrationError("Two source keys map to the same destination key.")
        operations.append({**version, "destinationKey": target, "state": "planned"})
    if not operations:
        raise MigrationError(
            "Selected prefixes contain no source versions or delete markers."
        )
    return {
        "format": 1,
        "scope": scope,
        "inventorySha256": canonical_hash(source),
        "operations": operations,
    }


def check_resume(existing: dict[str, Any], planned: dict[str, Any]) -> dict[str, Any]:
    if existing.get("format") != 1 or canonical_hash(
        existing.get("scope")
    ) != canonical_hash(planned["scope"]):
        raise MigrationError("Existing manifest targets a different migration scope.")
    if existing.get("inventorySha256") != planned["inventorySha256"]:
        raise MigrationError("Source inventory changed since the manifest was created.")
    old = existing.get("operations")
    new = planned["operations"]
    if not isinstance(old, list) or len(old) != len(new):
        raise MigrationError("Existing manifest operation count changed.")
    for prior, current in zip(old, new):
        if any(
            prior.get(field) != current[field] for field in current if field != "state"
        ):
            raise MigrationError("Existing manifest does not match the current plan.")
        if prior.get("state") not in ("planned", "pending", "done"):
            raise MigrationError("Existing manifest has an unknown operation state.")
        if prior["state"] == "done" and not (
            prior.get("destinationVersionId")
            and (prior["deleteMarker"] or prior.get("sha256"))
        ):
            raise MigrationError("Completed operation lacks verification metadata.")
        if prior["state"] == "pending" and prior.get("destinationVersionId"):
            raise MigrationError(
                "Pending operation already has a destination version ID."
            )
    if sum(op["state"] == "pending" for op in old) > 1:
        raise MigrationError("Only one operation may be pending in a serial migration.")
    return existing


def reviewed_plan(
    manifest_path: Path, planned: dict[str, Any], *, apply: bool
) -> dict[str, Any]:
    if not manifest_path.exists():
        if apply:
            raise MigrationError(
                "Apply requires the existing manifest from a reviewed dry run."
            )
        return planned
    return check_resume(load_private_json(manifest_path), planned)


def destination_versions(
    client: Any, bucket: str, account: str, keys: set[str]
) -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = defaultdict(list)
    paginator = client.get_paginator("list_object_versions")
    for key in sorted(keys):
        for page in paginator.paginate(
            Bucket=bucket, Prefix=key, ExpectedBucketOwner=account
        ):
            for field, is_delete in (("Versions", False), ("DeleteMarkers", True)):
                for item in page.get(field, []):
                    if item["Key"] == key:
                        found[key].append(
                            {
                                "versionId": item["VersionId"],
                                "deleteMarker": is_delete,
                                "size": 0 if is_delete else item["Size"],
                                "isLatest": bool(item.get("IsLatest", False)),
                            }
                        )
    return found


def assert_destination_is_owned(
    plan: dict[str, Any], versions: dict[str, list[dict[str, Any]]]
) -> None:
    """No replay may overwrite existing customer/template history or untracked writes."""
    expected: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for operation in plan["operations"]:
        if operation["state"] == "done":
            expected[operation["destinationKey"]][operation["destinationVersionId"]] = (
                operation
            )
    for key in {item["destinationKey"] for item in plan["operations"]}:
        actual = {item["versionId"]: item for item in versions.get(key, [])}
        if set(actual) != set(expected[key]):
            raise MigrationError(
                "Destination has an unexpected or missing version on a selected key."
            )
        for version_id, operation in expected[key].items():
            if actual[version_id]["deleteMarker"] != operation["deleteMarker"]:
                raise MigrationError(
                    "Destination version type differs from the manifest."
                )
