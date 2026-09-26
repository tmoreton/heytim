from __future__ import annotations

import re
from decimal import Decimal

from .support import table


def _workspace_payload_files(value: list[dict] | None) -> list[dict]:
    selected = []
    for item in value or []:
        if not isinstance(item, dict) or item.get("source") != "workspace":
            continue
        if not all(key in item for key in ("workspaceFileId", "name", "size", "objectKey")):
            raise ValueError("Workspace attachment metadata is incomplete")
        size = item["size"]
        if isinstance(size, Decimal):
            if size != size.to_integral_value():
                raise ValueError("Workspace file size is invalid")
            size = int(size)
        if type(size) is not int:
            raise ValueError("Workspace file size is invalid")
        selected.append({
            "workspaceFileId": item["workspaceFileId"],
            "name": item["name"],
            "size": size,
            "objectKey": item["objectKey"],
        })
    return selected


def _workspace_asset_manifest(
    user_id: str,
    bot_id: str,
    attachment_prefix: str | None,
) -> list[dict]:
    if attachment_prefix is not None:
        match = re.fullmatch(r"groups/([a-f0-9-]{36})/uploads/", attachment_prefix)
        if not match:
            raise ValueError("Workspace asset scope is invalid")
        partition_key = f"GROUP#{match.group(1)}"
        sort_prefix = "WORKSPACE_FILE#"
    else:
        partition_key = f"USER#{user_id}"
        sort_prefix = f"WORKSPACE_FILE#BOT#{bot_id}#"
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": partition_key, ":prefix": sort_prefix},
        ConsistentRead=True,
    ).get("Items", [])
    manifest = []
    for item in items:
        revision = item.get("revision")
        if isinstance(revision, Decimal):
            if revision != revision.to_integral_value():
                continue
            revision = int(revision)
        if (
            item.get("entity") != "WORKSPACE_FILE"
            or not isinstance(item.get("assetKey"), str)
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("name"), str)
            or type(revision) is not int
            or revision < 1
            or not isinstance(item.get("objectKey"), str)
        ):
            continue
        manifest.append(
            {
                "id": item["id"],
                "assetKey": item["assetKey"],
                "name": item["name"],
                "revision": revision,
                "objectKey": item["objectKey"],
                **(
                    {"sourceObjectKey": item["sourceObjectKey"]}
                    if isinstance(item.get("sourceObjectKey"), str)
                    else {}
                ),
                **(
                    {"updatedAt": item["updatedAt"]}
                    if isinstance(item.get("updatedAt"), str)
                    else {}
                ),
            }
        )
    return sorted(manifest, key=lambda item: item["assetKey"])
