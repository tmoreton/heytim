from __future__ import annotations

import hashlib
import re
import urllib.parse
import uuid
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Attr

from .support import FILES_BUCKET_NAME, MAX_GENERATED_ARTIFACT_BYTES, s3, table

WORKSPACE_VERSION = 2
MAX_WORKSPACE_FILES = 50
MAX_WORKSPACE_BYTES = 100_000_000
WORKSPACE_NAMESPACE = uuid.UUID("80ed5c86-4624-43f7-a794-7adb25599e24")
_ASSET_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")


def _workspace_scope(
    artifact_prefix: str, partition_key: str, owner: dict[str, str] | None
) -> tuple[str, str, str, str]:
    direct = re.fullmatch(
        r"(users/[a-f0-9]{64}/bots/([A-Za-z0-9][A-Za-z0-9_-]{0,63}))"
        r"/artifacts/[a-f0-9-]{32,64}",
        artifact_prefix,
    )
    if direct:
        bot_id = direct.group(2)
        if partition_key != partition_key.strip() or not partition_key.startswith("USER#"):
            raise ValueError("Workspace artifact owner is invalid")
        if owner is None or owner.get("botId") != bot_id:
            raise ValueError("Workspace artifact bot is invalid")
        return (
            "bot",
            bot_id,
            f"WORKSPACE_FILE#BOT#{bot_id}#",
            f"{direct.group(1)}/workspace/",
        )
    group = re.fullmatch(
        r"groups/([a-f0-9-]{36})/artifacts/[a-f0-9-]{32,64}",
        artifact_prefix,
    )
    if group and partition_key == f"GROUP#{group.group(1)}":
        group_id = group.group(1)
        return (
            "group",
            group_id,
            "WORKSPACE_FILE#",
            f"groups/{group_id}/workspace/",
        )
    raise ValueError("Workspace artifact scope is invalid")


def _workspace_quota_key(
    partition_key: str, scope_kind: str, scope_id: str
) -> dict[str, str]:
    return {
        "pk": partition_key,
        "sk": (
            f"WORKSPACE#BOT#{scope_id}"
            if scope_kind == "bot"
            else "WORKSPACE#META"
        ),
    }


def _adjust_workspace_quota(
    partition_key: str,
    scope_kind: str,
    scope_id: str,
    *,
    file_delta: int,
    byte_delta: int,
) -> None:
    values: dict[str, Any] = {
        ":entity": "WORKSPACE",
        ":files": file_delta,
        ":bytes": byte_delta,
    }
    conditions: list[str] = []
    if file_delta > 0:
        values[":maxFiles"] = MAX_WORKSPACE_FILES
        conditions.append("(attribute_not_exists(fileCount) OR fileCount < :maxFiles)")
    elif file_delta < 0:
        values[":minimumFiles"] = -file_delta
        conditions.append("fileCount >= :minimumFiles")
    if byte_delta > 0:
        values[":remainingBytes"] = MAX_WORKSPACE_BYTES - byte_delta
        conditions.append(
            "(attribute_not_exists(totalBytes) OR totalBytes <= :remainingBytes)"
        )
    elif byte_delta < 0:
        values[":minimumBytes"] = -byte_delta
        conditions.append("totalBytes >= :minimumBytes")
    table.update_item(
        Key=_workspace_quota_key(partition_key, scope_kind, scope_id),
        UpdateExpression=(
            "SET #entity = if_not_exists(#entity, :entity) "
            "ADD fileCount :files, totalBytes :bytes"
        ),
        **(
            {"ConditionExpression": " AND ".join(conditions)}
            if conditions
            else {}
        ),
        ExpressionAttributeNames={"#entity": "entity"},
        ExpressionAttributeValues=values,
    )


def _workspace_metadata(object_key: str) -> dict[str, str]:
    response = s3.head_object(Bucket=FILES_BUCKET_NAME, Key=object_key)
    raw = response.get("Metadata", {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(key).lower(): urllib.parse.unquote(str(value))
        for key, value in raw.items()
    }


def _verified_staged_checksum(object_key: str, expected: str) -> None:
    response = s3.get_object(Bucket=FILES_BUCKET_NAME, Key=object_key)
    stream = response.get("Body")
    if stream is None or not hasattr(stream, "read"):
        raise ValueError("Staged workspace asset is unavailable")
    try:
        body = stream.read(MAX_GENERATED_ARTIFACT_BYTES + 1)
    finally:
        stream.close()
    if (
        not body
        or len(body) > MAX_GENERATED_ARTIFACT_BYTES
        or hashlib.sha256(body).hexdigest() != expected
    ):
        raise ValueError("Staged workspace asset checksum is invalid")


def _promote_workspace_artifact(
    artifact_prefix: str,
    partition_key: str,
    owner: dict[str, str] | None,
    stored: dict,
    name: str,
    format_spec: tuple[str, str, str],
    metadata: dict[str, str],
) -> dict:
    asset_key = metadata.get("workspace-asset-key", "")
    checksum = metadata.get("workspace-sha256", "")
    expected_raw = metadata.get("workspace-expected-revision", "")
    if (
        not _ASSET_KEY.fullmatch(asset_key)
        or "//" in asset_key
        or any(part in {".", ".."} for part in asset_key.split("/"))
        or not re.fullmatch(r"[a-f0-9]{64}", checksum)
        or not re.fullmatch(r"0|[1-9]\d{0,8}", expected_raw)
    ):
        raise ValueError("Staged workspace asset metadata is invalid")
    expected_revision = int(expected_raw)
    object_key = stored["Key"]
    size = stored["Size"]
    _verified_staged_checksum(object_key, checksum)
    scope_kind, scope_id, sort_prefix, workspace_prefix = _workspace_scope(
        artifact_prefix, partition_key, owner
    )
    asset_id = str(
        uuid.uuid5(
            WORKSPACE_NAMESPACE,
            f"{partition_key}:{scope_kind}:{scope_id}:{asset_key}",
        )
    )
    workspace_key = {"pk": partition_key, "sk": f"{sort_prefix}{asset_id}"}
    existing = table.get_item(Key=workspace_key, ConsistentRead=True).get("Item")
    if existing and existing.get("assetKey") != asset_key:
        raise ValueError("Workspace asset identity collision")
    if existing and existing.get("checksum") == checksum:
        alias = {
            **existing,
            "sk": f"FILE#{asset_id}",
            "entity": "FILE",
            "status": "READY",
            "source": "workspace",
            **(owner or {}),
        }
        table.put_item(Item=alias)
        s3.delete_object(Bucket=FILES_BUCKET_NAME, Key=object_key)
        source_key = metadata.get("workspace-source-key")
        if source_key:
            s3.delete_object(Bucket=FILES_BUCKET_NAME, Key=source_key)
        return alias
    current_revision = int(existing.get("revision", 0)) if existing else 0
    if current_revision != expected_revision:
        raise ValueError(
            "Workspace asset changed while this revision was being prepared"
        )
    revision = current_revision + 1
    revision_prefix = f"{workspace_prefix}{asset_id}/revisions/{revision}/"
    content_prefix = f"{revision_prefix}{checksum[:16]}/"
    destination_key = f"{content_prefix}{name}"
    source_key = metadata.get("workspace-source-key")
    if source_key and not source_key.startswith(
        f"{artifact_prefix}/workspace-sources/"
    ):
        raise ValueError("Workspace asset source is outside its staging area")
    source_destination = f"{content_prefix}source.txt" if source_key else None
    kind, file_format, content_type = format_spec
    now = _now_from_s3(stored.get("LastModified"))
    item = {
        "pk": partition_key,
        "sk": workspace_key["sk"],
        "entity": "WORKSPACE_FILE",
        "workspaceVersion": WORKSPACE_VERSION,
        "id": asset_id,
        "assetKey": asset_key,
        "managedBy": "agent",
        "scope": scope_kind,
        "scopeId": scope_id,
        "uploadedBy": partition_key.removeprefix("USER#") if scope_kind == "bot" else "agent",
        "objectKey": destination_key,
        "name": name,
        "size": size,
        "kind": kind,
        "format": file_format,
        "contentType": content_type,
        "checksum": checksum,
        "revision": revision,
        "createdAt": existing.get("createdAt", now) if existing else now,
        "updatedAt": now,
        **({"sourceObjectKey": source_destination} if source_destination else {}),
    }
    alias = {
        **item,
        "sk": f"FILE#{asset_id}",
        "entity": "FILE",
        "status": "READY",
        "source": "workspace",
        "readyAt": now,
        **(owner or {}),
    }
    file_delta = 0 if existing else 1
    byte_delta = size - int(existing.get("size", 0)) if existing else size
    _adjust_workspace_quota(
        partition_key,
        scope_kind,
        scope_id,
        file_delta=file_delta,
        byte_delta=byte_delta,
    )
    copied_keys: list[str] = []
    wrote_workspace = False
    try:
        s3.copy_object(
            Bucket=FILES_BUCKET_NAME,
            CopySource={"Bucket": FILES_BUCKET_NAME, "Key": object_key},
            Key=destination_key,
            ContentType=content_type,
            MetadataDirective="REPLACE",
            Metadata={
                "workspace-asset-key": urllib.parse.quote(asset_key, safe="/-._~"),
                "workspace-revision": str(revision),
                "workspace-sha256": checksum,
            },
        )
        copied_keys.append(destination_key)
        if source_key and source_destination:
            s3.copy_object(
                Bucket=FILES_BUCKET_NAME,
                CopySource={"Bucket": FILES_BUCKET_NAME, "Key": source_key},
                Key=source_destination,
                ContentType="text/plain; charset=utf-8",
                MetadataDirective="REPLACE",
            )
            copied_keys.append(source_destination)
        if existing:
            table.update_item(
                Key=workspace_key,
                UpdateExpression=(
                    "SET workspaceVersion = :workspaceVersion, objectKey = :objectKey, "
                    "#name = :name, #size = :size, #kind = :kind, #format = :format, "
                    "contentType = :contentType, checksum = :checksum, revision = :next, "
                    "updatedAt = :updatedAt, sourceObjectKey = :sourceObjectKey"
                ),
                ConditionExpression=Attr("revision").eq(expected_revision),
                ExpressionAttributeNames={
                    "#name": "name",
                    "#size": "size",
                    "#kind": "kind",
                    "#format": "format",
                },
                ExpressionAttributeValues={
                    ":workspaceVersion": WORKSPACE_VERSION,
                    ":objectKey": destination_key,
                    ":name": name,
                    ":size": size,
                    ":kind": kind,
                    ":format": file_format,
                    ":contentType": content_type,
                    ":checksum": checksum,
                    ":next": revision,
                    ":updatedAt": now,
                    ":sourceObjectKey": source_destination,
                },
            )
            wrote_workspace = True
            refreshed = table.get_item(Key=workspace_key, ConsistentRead=True).get(
                "Item"
            )
            if refreshed:
                item = refreshed
                alias = {
                    **item,
                    "sk": f"FILE#{asset_id}",
                    "entity": "FILE",
                    "status": "READY",
                    "source": "workspace",
                    "readyAt": now,
                    **(owner or {}),
                }
        else:
            table.put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
            wrote_workspace = True
        table.put_item(Item=alias)
    except Exception:
        if wrote_workspace and existing:
            # The authoritative item already points at the new immutable revision.
            # A retry is checksum-idempotent and repairs the convenience FILE alias.
            raise
        if wrote_workspace and not existing:
            table.delete_item(Key=workspace_key)
        authoritative = table.get_item(
            Key=workspace_key, ConsistentRead=True
        ).get("Item")
        protected_keys = {
            value
            for value in (
                authoritative.get("objectKey") if authoritative else None,
                authoritative.get("sourceObjectKey") if authoritative else None,
            )
            if isinstance(value, str)
        }
        for copied_key in copied_keys:
            if copied_key not in protected_keys:
                s3.delete_object(Bucket=FILES_BUCKET_NAME, Key=copied_key)
        _adjust_workspace_quota(
            partition_key,
            scope_kind,
            scope_id,
            file_delta=-file_delta,
            byte_delta=-byte_delta,
        )
        raise
    s3.delete_object(Bucket=FILES_BUCKET_NAME, Key=object_key)
    if source_key:
        s3.delete_object(Bucket=FILES_BUCKET_NAME, Key=source_key)
    return alias



def _now_from_s3(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="milliseconds")
    return datetime.now(UTC).isoformat(timespec="milliseconds")
