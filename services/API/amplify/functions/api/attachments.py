from __future__ import annotations

import logging
import urllib.parse
import uuid
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Attr
from shared.client_contract import (
    DOCUMENT_MAX_BYTES,
    IMAGE_MAX_BYTES,
    MAX_ATTACHMENTS_PER_MESSAGE,
)
from shared.memory_identity import memory_actor_id

from .support import (
    ATTACHMENT_FORMATS,
    FILES_BUCKET_NAME,
    ApiError,
    _file_key,
    _group_pk,
    _now,
    _validate_string,
    s3,
    table,
)

logger = logging.getLogger(__name__)


def _attachment_spec(filename: Any, size: Any) -> dict:
    clean_name = _validate_string(filename, "filename", 200)
    clean_name = clean_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not clean_name or clean_name in {".", ".."} or any(
        ord(char) < 32 or ord(char) == 127 for char in clean_name
    ):
        raise ApiError(400, "filename is invalid")
    extension = f".{clean_name.rsplit('.', 1)[-1].lower()}" if "." in clean_name else ""
    format_spec = ATTACHMENT_FORMATS.get(extension)
    if not format_spec:
        raise ApiError(
            400,
            "Attach a PDF, document, spreadsheet, text file, or supported image.",
        )
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise ApiError(400, "size must be a positive whole number")
    kind, file_format, content_type = format_spec
    maximum = IMAGE_MAX_BYTES if kind == "image" else DOCUMENT_MAX_BYTES
    if size > maximum:
        label = "Images" if kind == "image" else "Documents"
        raise ApiError(400, f"{label} must be smaller than {maximum // 1_000_000} MB")
    return {
        "name": clean_name,
        "size": size,
        "kind": kind,
        "format": file_format,
        "contentType": content_type,
        "extension": extension,
        "maximum": maximum,
    }


def _public_file(item: dict) -> dict:
    return {
        key: item[key]
        for key in (
            "id",
            "name",
            "size",
            "kind",
            "format",
            "contentType",
            "createdAt",
        )
        if key in item
    }


def _get_file(user_id: str, file_id: str, *, ready: bool = False) -> dict:
    file_id = _validate_string(file_id, "fileId", 64)
    item = table.get_item(Key=_file_key(user_id, file_id), ConsistentRead=True).get(
        "Item"
    )
    if not item or item.get("entity") != "FILE":
        raise ApiError(404, "File not found")
    if ready and item.get("status") != "READY":
        raise ApiError(409, "This file has not finished uploading")
    return item


def _create_upload(user_id: str, value: dict) -> dict:
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "File uploads are not configured")
    spec = _attachment_spec(value.get("filename"), value.get("size"))
    file_id = str(uuid.uuid4())
    actor_id = memory_actor_id(user_id)
    object_key = f"users/{actor_id}/uploads/{file_id}{spec['extension']}"
    current = _now()
    item = {
        **_file_key(user_id, file_id),
        "entity": "FILE",
        "id": file_id,
        "status": "UPLOADING",
        "objectKey": object_key,
        "createdAt": current,
        "expiresAt": int(datetime.now(UTC).timestamp()) + 24 * 60 * 60,
        **{key: spec[key] for key in ("name", "size", "kind", "format", "contentType")},
    }
    table.put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
    try:
        upload = s3.generate_presigned_post(
            Bucket=FILES_BUCKET_NAME,
            Key=object_key,
            Fields={
                "Content-Type": spec["contentType"],
                "success_action_status": "204",
            },
            Conditions=[
                {"Content-Type": spec["contentType"]},
                {"success_action_status": "204"},
                ["content-length-range", 1, spec["maximum"]],
            ],
            ExpiresIn=600,
        )
    except Exception:
        table.delete_item(Key=_file_key(user_id, file_id))
        raise
    return {"file": _public_file(item), "upload": upload}


def _complete_upload(user_id: str, file_id: str) -> dict:
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "File uploads are not configured")
    item = _get_file(user_id, file_id)
    if item.get("status") == "READY":
        return _public_file(item)
    try:
        uploaded = s3.head_object(
            Bucket=FILES_BUCKET_NAME,
            Key=item["objectKey"],
        )
    except Exception as exc:
        error = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if error in {"404", "NoSuchKey", "NotFound"}:
            raise ApiError(409, "Upload the file before marking it complete") from exc
        raise
    if (
        uploaded.get("ContentLength") != item["size"]
        or uploaded.get("ContentType") != item["contentType"]
    ):
        s3.delete_object(Bucket=FILES_BUCKET_NAME, Key=item["objectKey"])
        table.delete_item(Key=_file_key(user_id, file_id))
        raise ApiError(400, "The uploaded file did not match the requested file")
    try:
        table.update_item(
            Key=_file_key(user_id, file_id),
            UpdateExpression="SET #status = :ready, readyAt = :now REMOVE expiresAt",
            ConditionExpression="#status = :uploading",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":uploading": "UPLOADING",
                ":ready": "READY",
                ":now": _now(),
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(409, "This upload is no longer active") from exc
    return _public_file({**item, "status": "READY"})


def _resolve_attachments(user_id: str, value: Any) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ApiError(400, "attachmentIds must be a list of file IDs")
    file_ids = list(dict.fromkeys(value))
    if len(file_ids) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise ApiError(
            400, f"Attach up to {MAX_ATTACHMENTS_PER_MESSAGE} files per message"
        )
    attachments = [_get_file(user_id, file_id, ready=True) for file_id in file_ids]
    for item in attachments:
        table.update_item(
            Key=_file_key(user_id, item["id"]),
            UpdateExpression=(
                "SET lastUsedAt = :now, referenceCount = "
                "if_not_exists(referenceCount, :zero) + :one"
            ),
            ExpressionAttributeValues={":now": _now(), ":zero": 0, ":one": 1},
        )
    return [
        {
            **_public_file(item),
            "objectKey": item["objectKey"],
        }
        for item in attachments
    ]


def _resolve_group_attachments(
    user_id: str, group_id: str, value: Any
) -> list[dict]:
    """Copy caller-owned uploads into the room before sharing them with members."""
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "File uploads are not configured")
    try:
        uuid.UUID(group_id)
    except (ValueError, AttributeError) as exc:
        raise ApiError(400, "groupId is invalid") from exc
    attachments = _resolve_attachments(user_id, value)
    copied_keys: list[str] = []
    group_attachments: list[dict] = []
    try:
        for item in attachments:
            extension = (
                f".{item['name'].rsplit('.', 1)[-1].lower()}"
                if "." in item["name"]
                else ""
            )
            object_key = f"groups/{group_id}/uploads/{item['id']}{extension}"
            s3.copy_object(
                Bucket=FILES_BUCKET_NAME,
                CopySource={"Bucket": FILES_BUCKET_NAME, "Key": item["objectKey"]},
                Key=object_key,
                ContentType=item["contentType"],
                MetadataDirective="REPLACE",
            )
            copied_keys.append(object_key)
            group_attachments.append(
                {
                    **item,
                    "pk": _group_pk(group_id),
                    "sk": f"FILE#{item['id']}",
                    "entity": "FILE",
                    "status": "READY",
                    "source": "uploaded",
                    "uploadedBy": user_id,
                    "objectKey": object_key,
                    "readyAt": _now(),
                }
            )
    except Exception:
        for object_key in copied_keys:
            try:
                s3.delete_object(Bucket=FILES_BUCKET_NAME, Key=object_key)
            except Exception:
                logger.warning("Could not remove a partially copied group attachment", exc_info=True)
        raise
    return group_attachments


def _download_file(user_id: str, file_id: str) -> dict:
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "File downloads are not configured")
    item = _get_file(user_id, file_id, ready=True)
    return _download_item(item)


def _download_group_file(user_id: str, group_id: str, file_id: str) -> dict:
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "File downloads are not configured")
    member = table.get_item(
        Key={"pk": _group_pk(group_id), "sk": f"USER#{user_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not member or member.get("entity") != "GROUP_USER":
        raise ApiError(404, "File not found")
    file_id = _validate_string(file_id, "fileId", 64)
    item = table.get_item(
        Key={"pk": _group_pk(group_id), "sk": f"FILE#{file_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not item or item.get("entity") != "FILE":
        raise ApiError(404, "File not found")
    if item.get("status") != "READY":
        raise ApiError(409, "This file has not finished generating")
    return _download_item(item)


def _download_item(item: dict) -> dict:
    safe_name = urllib.parse.quote(item["name"], safe="")
    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": FILES_BUCKET_NAME,
            "Key": item["objectKey"],
            "ResponseContentDisposition": f"attachment; filename*=UTF-8''{safe_name}",
            "ResponseContentType": item["contentType"],
        },
        ExpiresIn=300,
    )
    return {"url": url, "expiresIn": 300}
