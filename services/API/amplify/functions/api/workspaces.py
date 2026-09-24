"""Durable, scoped files that can be attached to later bot and room runs."""
from __future__ import annotations

import uuid
from typing import Any

from boto3.dynamodb.conditions import Attr
from shared.memory_identity import memory_actor_id
from shared.storage import delete_object_versions

from .attachments import _download_item, _get_file, _public_file
from .bots import _get_bot
from .groups import _require_group_member
from .support import (
    FILES_BUCKET_NAME,
    ApiError,
    _body,
    _group_pk,
    _now,
    _partition_items,
    _response,
    _user_pk,
    _validate_string,
    s3,
    table,
)

WORKSPACE_VERSION = 1
MAX_WORKSPACE_FILES = 50
MAX_WORKSPACE_BYTES = 100_000_000


def _scope(user_id: str, kind: str, scope_id: str) -> tuple[str, str, str]:
    if kind == "bot":
        _get_bot(user_id, scope_id)
        return (
            _user_pk(user_id),
            f"WORKSPACE_FILE#BOT#{scope_id}#",
            f"users/{memory_actor_id(user_id)}/bots/{scope_id}/workspace/",
        )
    if kind == "group":
        _require_group_member(user_id, scope_id)
        return (
            _group_pk(scope_id),
            "WORKSPACE_FILE#",
            f"groups/{scope_id}/workspace/",
        )
    raise ApiError(400, "Workspace scope is invalid")


def _workspace_items(user_id: str, kind: str, scope_id: str) -> list[dict]:
    pk, prefix, _ = _scope(user_id, kind, scope_id)
    return [
        item for item in _partition_items(pk, prefix)
        if item.get("entity") == "WORKSPACE_FILE"
    ]


def _quota_key(pk: str, kind: str, scope_id: str) -> dict[str, str]:
    return {
        "pk": pk,
        "sk": f"WORKSPACE#BOT#{scope_id}" if kind == "bot" else "WORKSPACE#META",
    }


def _adjust_quota(pk: str, kind: str, scope_id: str, size: int, *, reserve: bool) -> None:
    values = {
        ":entity": "WORKSPACE",
        ":one": 1 if reserve else -1,
        ":size": size if reserve else -size,
        ":zero": 0,
    }
    if reserve:
        values.update({
            ":maxFiles": MAX_WORKSPACE_FILES,
            ":remainingBytes": MAX_WORKSPACE_BYTES - size,
        })
    try:
        table.update_item(
            Key=_quota_key(pk, kind, scope_id),
            UpdateExpression=(
                "SET #entity = if_not_exists(#entity, :entity) "
                "ADD fileCount :one, totalBytes :size"
            ),
            ConditionExpression=(
                "(attribute_not_exists(fileCount) OR fileCount < :maxFiles) "
                "AND (attribute_not_exists(totalBytes) OR totalBytes <= :remainingBytes)"
                if reserve else "fileCount >= :zero"
            ),
            ExpressionAttributeNames={"#entity": "entity"},
            ExpressionAttributeValues=values,
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        if reserve:
            raise ApiError(409, "Workspace file limit reached") from exc
        raise


def _public_workspace_file(item: dict) -> dict:
    return {
        **_public_file(item),
        "workspaceVersion": WORKSPACE_VERSION,
        "uploadedBy": item.get("uploadedBy"),
    }


def _list_workspace_files(user_id: str, kind: str, scope_id: str) -> dict:
    items = _workspace_items(user_id, kind, scope_id)
    return {
        "workspaceVersion": WORKSPACE_VERSION,
        "files": [_public_workspace_file(item) for item in sorted(items, key=lambda item: item["createdAt"])],
        "fileCount": len(items),
        "totalBytes": sum(int(item.get("size", 0)) for item in items),
        "limits": {"files": MAX_WORKSPACE_FILES, "bytes": MAX_WORKSPACE_BYTES},
    }


def _export_workspace_files(user_id: str, kind: str, scope_id: str) -> dict:
    """Return a portable manifest and short-lived links for each owned file."""
    items = _workspace_items(user_id, kind, scope_id)
    return {
        "workspaceVersion": WORKSPACE_VERSION,
        "scope": kind,
        "files": [
            {**_public_workspace_file(item), **_download_item(item)}
            for item in sorted(items, key=lambda item: item["createdAt"])
        ],
    }


def _get_workspace_file(user_id: str, kind: str, scope_id: str, file_id: str) -> dict:
    file_id = _validate_string(file_id, "workspaceFileId", 64)
    pk, prefix, _ = _scope(user_id, kind, scope_id)
    item = table.get_item(
        Key={"pk": pk, "sk": f"{prefix}{file_id}"}, ConsistentRead=True
    ).get("Item")
    if not item or item.get("entity") != "WORKSPACE_FILE":
        raise ApiError(404, "Workspace file not found")
    return item


def _add_workspace_file(user_id: str, kind: str, scope_id: str, value: dict) -> dict:
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "File storage is not configured")
    pk, prefix, object_prefix = _scope(user_id, kind, scope_id)
    source = _get_file(user_id, value.get("fileId"), ready=True)
    if (
        source["name"] in {".", ".."}
        or "/" in source["name"] or "\\" in source["name"]
        or any(ord(char) < 32 or ord(char) == 127 for char in source["name"])
    ):
        raise ApiError(400, "Source filename is invalid")
    size = int(source["size"])
    if size > MAX_WORKSPACE_BYTES:
        raise ApiError(409, "Workspace file limit reached")
    file_id = str(uuid.uuid4())
    object_key = f"{object_prefix}{file_id}/{source['name']}"
    item = {
        "pk": pk,
        "sk": f"{prefix}{file_id}",
        "entity": "WORKSPACE_FILE",
        "workspaceVersion": WORKSPACE_VERSION,
        "id": file_id,
        "scope": kind,
        "scopeId": scope_id,
        "uploadedBy": user_id,
        "sourceFileId": source["id"],
        "objectKey": object_key,
        "createdAt": _now(),
        **{key: source[key] for key in ("name", "size", "kind", "format", "contentType")},
    }
    alias = {
        **item,
        "sk": f"FILE#{file_id}",
        "entity": "FILE",
        "status": "READY",
        "source": "workspace",
        **({"botId": scope_id} if kind == "bot" else {}),
    }
    _adjust_quota(pk, kind, scope_id, size, reserve=True)
    wrote_item = False
    wrote_alias = False
    try:
        s3.copy_object(
            Bucket=FILES_BUCKET_NAME,
            CopySource={"Bucket": FILES_BUCKET_NAME, "Key": source["objectKey"]},
            Key=object_key,
            ContentType=source["contentType"],
            MetadataDirective="REPLACE",
        )
        table.put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
        wrote_item = True
        table.put_item(Item=alias, ConditionExpression=Attr("pk").not_exists())
        wrote_alias = True
    except Exception:
        if wrote_item:
            table.delete_item(Key={"pk": pk, "sk": item["sk"]})
        if wrote_alias:
            table.delete_item(Key={"pk": pk, "sk": alias["sk"]})
        try:
            delete_object_versions(s3, FILES_BUCKET_NAME, f"{object_prefix}{file_id}/", resource_label="workspace file")
        finally:
            _adjust_quota(pk, kind, scope_id, size, reserve=False)
        raise
    return _public_workspace_file(item)


def _delete_workspace_file(user_id: str, kind: str, scope_id: str, file_id: str) -> dict:
    item = _get_workspace_file(user_id, kind, scope_id, file_id)
    if kind == "group":
        meta, _ = _require_group_member(user_id, scope_id)
        if item.get("uploadedBy") != user_id and meta.get("ownerId") != user_id:
            raise ApiError(403, "Only the uploader or group owner can remove this file")
    delete_object_versions(
        s3, FILES_BUCKET_NAME, item["objectKey"].rsplit("/", 1)[0] + "/",
        resource_label="workspace file",
    )
    deleted = table.delete_item(
        Key={"pk": item["pk"], "sk": item["sk"]}, ReturnValues="ALL_OLD"
    ).get("Attributes")
    if deleted:
        table.delete_item(Key={"pk": item["pk"], "sk": f"FILE#{file_id}"})
        _adjust_quota(item["pk"], kind, scope_id, int(item["size"]), reserve=False)
    return {"deleted": True}


def _download_workspace_file(user_id: str, kind: str, scope_id: str, file_id: str) -> dict:
    return _download_item(_get_workspace_file(user_id, kind, scope_id, file_id))


def _resolve_workspace_files(user_id: str, kind: str, scope_id: str, raw: Any) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(file_id, str) for file_id in raw):
        raise ApiError(400, "workspaceFileIds must be a list of file IDs")
    file_ids = list(dict.fromkeys(raw))
    if len(file_ids) > 5:
        raise ApiError(400, "Attach up to 5 workspace files per message")
    return [
        {
            **_public_file(item),
            "objectKey": item["objectKey"],
            "source": "workspace",
            "workspaceFileId": item["id"],
            **({"botId": scope_id} if kind == "bot" else {}),
        }
        for item in (
            _get_workspace_file(user_id, kind, scope_id, file_id)
            for file_id in file_ids
        )
    ]


def _workspace_route(
    user_id: str, _display_name: str, method: str, path: str, params: dict, event: dict
) -> dict | None:
    kind = "bot" if path.startswith("/bots/") else "group"
    scope_id = params.get("botId", "") if kind == "bot" else params.get("groupId", "")
    file_id = params.get("workspaceFileId", "")
    if method == "GET" and path.endswith("/export"):
        return _response(200, _export_workspace_files(user_id, kind, scope_id))
    if method == "GET" and path.endswith("/download"):
        return _response(200, _download_workspace_file(user_id, kind, scope_id, file_id))
    if method == "DELETE":
        return _response(200, _delete_workspace_file(user_id, kind, scope_id, file_id))
    if method == "GET":
        return _response(200, _list_workspace_files(user_id, kind, scope_id))
    if method == "POST":
        return _response(201, _add_workspace_file(user_id, kind, scope_id, _body(event)))
    return None
