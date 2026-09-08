from __future__ import annotations

import urllib.parse
import uuid
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Attr
from shared.memory_identity import memory_actor_id

from .support import (
    FILES_BUCKET_NAME,
    GENERATED_ARTIFACT_FORMATS,
    MAX_GENERATED_ARTIFACT_BYTES,
    MAX_GENERATED_ARTIFACTS,
    s3,
    table,
)


def _attachment_blocks(turn: dict, user_id: str) -> list[dict]:
    attachments = turn.get("attachments", [])
    if not isinstance(attachments, list):
        raise TypeError("Turn attachments must be a list")
    blocks = []
    user_prefix = f"users/{memory_actor_id(user_id)}/uploads/"
    for index, attachment in enumerate(attachments, start=1):
        if not isinstance(attachment, dict):
            raise TypeError("Turn attachment must be an object")
        kind = attachment.get("kind")
        file_format = attachment.get("format")
        object_key = attachment.get("objectKey")
        if (
            kind not in {"image", "document"}
            or not isinstance(file_format, str)
            or not isinstance(object_key, str)
            or not object_key.startswith(user_prefix)
        ):
            raise ValueError("Turn attachment metadata is invalid")
        source = {"s3Location": {"uri": f"s3://{FILES_BUCKET_NAME}/{object_key}"}}
        if kind == "image":
            blocks.append({"image": {"format": file_format, "source": source}})
        else:
            blocks.append(
                {
                    "document": {
                        "format": file_format,
                        "name": f"Attachment {index}",
                        "source": source,
                    }
                }
            )
    return blocks


def _generated_artifact_prefix(user_id: str, bot_id: str, event_id: str) -> str:
    return f"users/{memory_actor_id(user_id)}/bots/{bot_id}/artifacts/{event_id}"


def _group_generated_artifact_prefix(group_id: str, event_id: str) -> str:
    return f"groups/{group_id}/artifacts/{event_id}"


def _collect_artifacts(
    prefix: str, partition_key: str, owner: dict[str, str] | None = None
) -> list[dict]:
    prefix = f"{prefix}/"
    objects = []
    continuation_token = None
    while True:
        request: dict[str, Any] = {
            "Bucket": FILES_BUCKET_NAME,
            "Prefix": prefix,
            "MaxKeys": 100,
        }
        if continuation_token:
            request["ContinuationToken"] = continuation_token
        response = s3.list_objects_v2(**request)
        objects.extend(response.get("Contents", []))
        if len(objects) > MAX_GENERATED_ARTIFACTS:
            raise ValueError(
                f"A reply can create at most {MAX_GENERATED_ARTIFACTS} artifacts"
            )
        if response.get("IsTruncated") is not True:
            break
        continuation_token = response.get("NextContinuationToken")
        if not isinstance(continuation_token, str) or not continuation_token:
            raise RuntimeError(
                "S3 artifact listing did not return a continuation token"
            )

    artifacts = []
    for stored in objects:
        object_key = stored.get("Key")
        size = stored.get("Size")
        if not isinstance(object_key, str) or not isinstance(size, int):
            continue
        leaf = object_key.rsplit("/", 1)[-1]
        if "--" not in leaf:
            continue
        file_id, encoded_name = leaf.split("--", 1)
        try:
            uuid.UUID(file_id)
        except (ValueError, AttributeError):
            continue
        name = urllib.parse.unquote(encoded_name)
        extension = f".{name.rsplit('.', 1)[-1].lower()}" if "." in name else ""
        format_spec = GENERATED_ARTIFACT_FORMATS.get(extension)
        if (
            not format_spec
            or not name
            or len(name) > 100
            or size > MAX_GENERATED_ARTIFACT_BYTES
        ):
            continue
        kind, file_format, content_type = format_spec
        created_at = _now_from_s3(stored.get("LastModified"))
        item = {
            "pk": partition_key,
            "sk": f"FILE#{file_id}",
            "entity": "FILE",
            "id": file_id,
            "status": "READY",
            "source": "generated",
            "name": name,
            "size": size,
            "kind": kind,
            "format": file_format,
            "contentType": content_type,
            "objectKey": object_key,
            "createdAt": created_at,
            "readyAt": created_at,
            **(owner or {}),
        }
        try:
            table.put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            existing = table.get_item(
                Key={"pk": item["pk"], "sk": item["sk"]}, ConsistentRead=True
            ).get("Item")
            if existing:
                item = existing
        artifacts.append(item)
    return artifacts


def _collect_generated_artifacts(
    user_id: str, bot_id: str, event_id: str
) -> list[dict]:
    return _collect_artifacts(
        _generated_artifact_prefix(user_id, bot_id, event_id),
        f"USER#{user_id}",
        {"botId": bot_id},
    )


def _collect_group_generated_artifacts(group_id: str, event_id: str) -> list[dict]:
    return _collect_artifacts(
        _group_generated_artifact_prefix(group_id, event_id), f"GROUP#{group_id}"
    )


def _delete_artifacts(prefix: str, partition_key: str) -> int:
    prefix = f"{prefix}/"
    objects = []
    continuation_token = None
    while True:
        request: dict[str, Any] = {
            "Bucket": FILES_BUCKET_NAME,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }
        if continuation_token:
            request["ContinuationToken"] = continuation_token
        response = s3.list_objects_v2(**request)
        objects.extend(
            {"Key": item["Key"]}
            for item in response.get("Contents", [])
            if isinstance(item.get("Key"), str)
        )
        if response.get("IsTruncated") is not True:
            break
        continuation_token = response.get("NextContinuationToken")
        if not isinstance(continuation_token, str) or not continuation_token:
            raise RuntimeError(
                "S3 artifact deletion did not return a continuation token"
            )

    for offset in range(0, len(objects), 1000):
        result = s3.delete_objects(
            Bucket=FILES_BUCKET_NAME,
            Delete={"Objects": objects[offset : offset + 1000], "Quiet": True},
        )
        errors = result.get("Errors", [])
        if errors:
            raise RuntimeError(f"S3 did not delete {len(errors)} partial artifacts")
    for stored in objects:
        leaf = stored["Key"].rsplit("/", 1)[-1]
        file_id = leaf.split("--", 1)[0]
        try:
            uuid.UUID(file_id)
        except (ValueError, AttributeError):
            continue
        table.delete_item(Key={"pk": partition_key, "sk": f"FILE#{file_id}"})
    return len(objects)


def _delete_generated_artifacts(user_id: str, bot_id: str, event_id: str) -> int:
    return _delete_artifacts(
        _generated_artifact_prefix(user_id, bot_id, event_id), f"USER#{user_id}"
    )


def _delete_group_generated_artifacts(group_id: str, event_id: str) -> int:
    return _delete_artifacts(
        _group_generated_artifact_prefix(group_id, event_id), f"GROUP#{group_id}"
    )


def _now_from_s3(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="milliseconds")
    return datetime.now(UTC).isoformat(timespec="milliseconds")
