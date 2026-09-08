from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

from shared.memory_cleanup import delete_user_memory
from shared.memory_identity import (
    direct_session_id,
    group_memory_actor_id,
    memory_actor_id,
)

from .support import (
    FILES_BUCKET_NAME,
    FROGBOT_MEMORY_ID,
    ApiError,
    _partition_items,
    _user_pk,
    agentcore,
    s3,
)

MAX_MEMORY_CHARS = 16_000
EDITABLE_MEMORY_KINDS = {"fact": "facts", "preference": "preferences"}
_TOPIC_PATTERN = re.compile(
    r'^\s*<topic\s+name="([^"]+)">\s*(.*?)\s*</topic>\s*$', re.DOTALL
)


def _memory_pages(operation: str, result_key: str, **request) -> list[dict]:
    if not FROGBOT_MEMORY_ID:
        return []
    items = []
    while True:
        try:
            response = getattr(agentcore, operation)(
                memoryId=FROGBOT_MEMORY_ID, maxResults=100, **request
            )
        except agentcore.exceptions.ResourceNotFoundException:
            return items
        items.extend(response.get(result_key, []))
        next_token = response.get("nextToken")
        if not isinstance(next_token, str) or not next_token:
            return items
        request["nextToken"] = next_token


def _delete_user_memory(user_id: str) -> dict[str, int]:
    return delete_user_memory(agentcore, FROGBOT_MEMORY_ID, user_id)


def _namespace_kind(namespace: str, actor_id: str) -> str | None:
    for plural, kind in (
        ("facts", "fact"),
        ("preferences", "preference"),
        ("summaries", "summary"),
    ):
        prefix = f"/{plural}/{actor_id}/"
        if namespace.startswith(prefix):
            return kind
    return None


def _readable_content(kind: str, content: str) -> str:
    if kind == "summary":
        match = _TOPIC_PATTERN.fullmatch(content)
        if match:
            return f"{match.group(1).strip()}\n\n{match.group(2).strip()}"
    if kind == "preference":
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            return content.strip()
        if isinstance(value, dict) and isinstance(value.get("preference"), str):
            preference = value["preference"].strip()
            context = value.get("context")
            if isinstance(context, str) and context.strip():
                return f"{preference}\n\nWhy this was learned: {context.strip()}"
            return preference
    return content.strip()


def _created_at(value) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value) if value is not None else ""


def _metadata_string(record: dict, key: str) -> str | None:
    value = record.get("metadata", {}).get(key, {})
    text = value.get("stringValue") if isinstance(value, dict) else None
    return text if isinstance(text, str) and text else None


def _bot_sessions(user_id: str) -> dict[str, dict[str, str]]:
    sessions = {}
    for item in _partition_items(_user_pk(user_id), "BOT#"):
        bot_id = item.get("id")
        name = item.get("name")
        if isinstance(bot_id, str) and isinstance(name, str):
            sessions[direct_session_id(user_id, bot_id)] = {
                "botId": bot_id,
                "botName": name,
            }
    return sessions


def _list_user_memories(user_id: str) -> dict:
    if not FROGBOT_MEMORY_ID:
        return {"records": [], "rawConversationRetentionDays": 30}
    actor_id = memory_actor_id(user_id)
    bot_sessions = _bot_sessions(user_id)
    records = []
    for plural, kind in (
        ("facts", "fact"),
        ("preferences", "preference"),
        ("summaries", "summary"),
    ):
        for record in _memory_pages(
            "list_memory_records",
            "memoryRecordSummaries",
            namespacePath=f"/{plural}/{actor_id}/",
        ):
            record_id = record.get("memoryRecordId")
            content = record.get("content", {}).get("text")
            namespaces = record.get("namespaces", [])
            if (
                not isinstance(record_id, str)
                or not isinstance(content, str)
                or not isinstance(namespaces, list)
            ):
                continue
            namespace = next(
                (
                    value
                    for value in namespaces
                    if isinstance(value, str)
                    and _namespace_kind(value, actor_id) == kind
                ),
                None,
            )
            if namespace is None:
                continue
            item = {
                "id": record_id,
                "kind": kind,
                "content": _readable_content(kind, content),
                "createdAt": _created_at(record.get("createdAt")),
                "scope": "personal",
                "source": _metadata_string(record, "frogbotSource") or "learned",
            }
            if kind == "summary":
                parts = namespace.strip("/").split("/")
                if len(parts) >= 3:
                    item.update(bot_sessions.get(parts[2], {}))
            records.append(item)
    records.sort(key=lambda item: item["createdAt"], reverse=True)
    return {"records": records, "rawConversationRetentionDays": 30}


def _create_user_memory(user_id: str, body: dict) -> dict:
    if not FROGBOT_MEMORY_ID:
        raise ApiError(503, "Memory is unavailable")
    kind = body.get("kind")
    plural = EDITABLE_MEMORY_KINDS.get(kind)
    if plural is None:
        raise ApiError(400, "Memory kind must be fact or preference")
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(400, "Memory cannot be empty")
    content = content.strip()
    if len(content) > MAX_MEMORY_CHARS:
        raise ApiError(400, f"Memory must be {MAX_MEMORY_CHARS:,} characters or fewer")
    created_at = datetime.now(UTC)
    response = agentcore.batch_create_memory_records(
        memoryId=FROGBOT_MEMORY_ID,
        records=[
            {
                "requestIdentifier": str(uuid.uuid4()),
                "namespaces": [f"/{plural}/{memory_actor_id(user_id)}/"],
                "content": {"text": content},
                "timestamp": created_at,
                "metadata": {
                    "frogbotScope": {"stringValue": "personal"},
                    "frogbotSource": {"stringValue": "manual"},
                },
            }
        ],
    )
    successes = response.get("successfulRecords", [])
    if response.get("failedRecords") or not successes:
        raise ApiError(502, "Memory could not be saved")
    record_id = successes[0].get("memoryRecordId")
    if not isinstance(record_id, str):
        raise ApiError(502, "Memory could not be saved")
    return {
        "id": record_id,
        "kind": kind,
        "content": content,
        "createdAt": created_at.isoformat(),
        "scope": "personal",
        "source": "manual",
    }


def _require_group_memory_access(
    user_id: str, group_id: str, *, owner: bool = False
) -> None:
    from .groups import _require_group_member

    _require_group_member(user_id, group_id, owner=owner)


def _list_group_memories(user_id: str, group_id: str) -> dict:
    _require_group_memory_access(user_id, group_id)
    if not FROGBOT_MEMORY_ID:
        return {"records": [], "rawConversationRetentionDays": 30}
    actor_id = group_memory_actor_id(group_id)
    records = []
    for plural, kind in (
        ("facts", "fact"),
        ("preferences", "preference"),
        ("summaries", "summary"),
    ):
        for record in _memory_pages(
            "list_memory_records",
            "memoryRecordSummaries",
            namespacePath=f"/{plural}/{actor_id}/",
        ):
            record_id = record.get("memoryRecordId")
            content = record.get("content", {}).get("text")
            if not isinstance(record_id, str) or not isinstance(content, str):
                continue
            records.append(
                {
                    "id": record_id,
                    "kind": kind,
                    "content": _readable_content(kind, content),
                    "createdAt": _created_at(record.get("createdAt")),
                    "scope": "group",
                    "source": _metadata_string(record, "frogbotSource") or "learned",
                }
            )
    records.sort(key=lambda item: item["createdAt"], reverse=True)
    return {"records": records, "rawConversationRetentionDays": 30}


def _create_group_memory(user_id: str, group_id: str, body: dict) -> dict:
    _require_group_memory_access(user_id, group_id, owner=True)
    if not FROGBOT_MEMORY_ID:
        raise ApiError(503, "Memory is unavailable")
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(400, "Memory cannot be empty")
    content = content.strip()
    if len(content) > MAX_MEMORY_CHARS:
        raise ApiError(400, f"Memory must be {MAX_MEMORY_CHARS:,} characters or fewer")
    created_at = datetime.now(UTC)
    response = agentcore.batch_create_memory_records(
        memoryId=FROGBOT_MEMORY_ID,
        records=[
            {
                "requestIdentifier": str(uuid.uuid4()),
                "namespaces": [f"/facts/{group_memory_actor_id(group_id)}/"],
                "content": {"text": content},
                "timestamp": created_at,
                "metadata": {
                    "frogbotScope": {"stringValue": "group"},
                    "frogbotSource": {"stringValue": "manual"},
                },
            }
        ],
    )
    successes = response.get("successfulRecords", [])
    if response.get("failedRecords") or not successes:
        raise ApiError(502, "Group memory could not be saved")
    record_id = successes[0].get("memoryRecordId")
    if not isinstance(record_id, str):
        raise ApiError(502, "Group memory could not be saved")
    return {
        "id": record_id,
        "kind": "fact",
        "content": content,
        "createdAt": created_at.isoformat(),
        "scope": "group",
        "source": "manual",
    }


def _owned_group_memory_record(
    user_id: str, group_id: str, record_id: str
) -> tuple[dict, str, str]:
    _require_group_memory_access(user_id, group_id, owner=True)
    if not FROGBOT_MEMORY_ID or not record_id.startswith("mem-"):
        raise ApiError(404, "Memory not found")
    try:
        record = agentcore.get_memory_record(
            memoryId=FROGBOT_MEMORY_ID,
            memoryRecordId=record_id,
        ).get("memoryRecord", {})
    except agentcore.exceptions.ResourceNotFoundException as exc:
        raise ApiError(404, "Memory not found") from exc
    actor_id = group_memory_actor_id(group_id)
    for namespace in record.get("namespaces", []):
        if not isinstance(namespace, str):
            continue
        if namespace.startswith(f"/facts/{actor_id}/"):
            return record, namespace, "fact"
        if namespace.startswith(f"/preferences/{actor_id}/"):
            return record, namespace, "preference"
        if namespace.startswith(f"/summaries/{actor_id}/"):
            return record, namespace, "summary"
    raise ApiError(404, "Memory not found")


def _update_group_memory(
    user_id: str, group_id: str, record_id: str, body: dict
) -> dict:
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(400, "Memory cannot be empty")
    content = content.strip()
    if len(content) > MAX_MEMORY_CHARS:
        raise ApiError(400, f"Memory must be {MAX_MEMORY_CHARS:,} characters or fewer")
    record, namespace, kind = _owned_group_memory_record(user_id, group_id, record_id)
    update = {
        "memoryRecordId": record_id,
        "timestamp": datetime.now(UTC),
        "content": {"text": content},
        "namespaces": [namespace],
    }
    strategy_id = record.get("memoryStrategyId")
    if isinstance(strategy_id, str) and strategy_id:
        update["memoryStrategyId"] = strategy_id
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and metadata:
        update["metadata"] = metadata
    response = agentcore.batch_update_memory_records(
        memoryId=FROGBOT_MEMORY_ID,
        records=[update],
    )
    if response.get("failedRecords"):
        raise ApiError(502, "Group memory could not be updated")
    return {
        "id": record_id,
        "kind": kind,
        "content": content,
        "createdAt": _created_at(record.get("createdAt")),
        "scope": "group",
        "source": _metadata_string(record, "frogbotSource") or "learned",
    }


def _delete_group_memory_record(user_id: str, group_id: str, record_id: str) -> dict:
    _owned_group_memory_record(user_id, group_id, record_id)
    response = agentcore.batch_delete_memory_records(
        memoryId=FROGBOT_MEMORY_ID,
        records=[{"memoryRecordId": record_id}],
    )
    if response.get("failedRecords"):
        raise ApiError(502, "Group memory could not be forgotten")
    return {"deleted": True}


def _owned_memory_record(user_id: str, record_id: str) -> tuple[dict, str, str]:
    if not FROGBOT_MEMORY_ID or not record_id.startswith("mem-"):
        raise ApiError(404, "Memory not found")
    try:
        record = agentcore.get_memory_record(
            memoryId=FROGBOT_MEMORY_ID,
            memoryRecordId=record_id,
        ).get("memoryRecord", {})
    except agentcore.exceptions.ResourceNotFoundException as exc:
        raise ApiError(404, "Memory not found") from exc
    actor_id = memory_actor_id(user_id)
    for namespace in record.get("namespaces", []):
        if isinstance(namespace, str):
            kind = _namespace_kind(namespace, actor_id)
            if kind:
                return record, namespace, kind
    raise ApiError(404, "Memory not found")


def _update_user_memory(user_id: str, record_id: str, body: dict) -> dict:
    content = body.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ApiError(400, "Memory cannot be empty")
    content = content.strip()
    if len(content) > MAX_MEMORY_CHARS:
        raise ApiError(400, f"Memory must be {MAX_MEMORY_CHARS:,} characters or fewer")
    record, namespace, kind = _owned_memory_record(user_id, record_id)
    update = {
        "memoryRecordId": record_id,
        "timestamp": datetime.now(UTC),
        "content": {"text": content},
        "namespaces": [namespace],
    }
    strategy_id = record.get("memoryStrategyId")
    if isinstance(strategy_id, str) and strategy_id:
        update["memoryStrategyId"] = strategy_id
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and metadata:
        update["metadata"] = metadata
    response = agentcore.batch_update_memory_records(
        memoryId=FROGBOT_MEMORY_ID,
        records=[update],
    )
    if response.get("failedRecords"):
        raise ApiError(502, "Memory could not be updated")
    return {
        "id": record_id,
        "kind": kind,
        "content": content,
        "createdAt": _created_at(record.get("createdAt")),
        "scope": "personal",
        "source": _metadata_string(record, "frogbotSource") or "learned",
    }


def _delete_user_memory_record(user_id: str, record_id: str) -> dict:
    _owned_memory_record(user_id, record_id)
    response = agentcore.batch_delete_memory_records(
        memoryId=FROGBOT_MEMORY_ID,
        records=[{"memoryRecordId": record_id}],
    )
    if response.get("failedRecords"):
        raise ApiError(502, "Memory could not be forgotten")
    return {"deleted": True}


def _export_user_memories(user_id: str) -> dict:
    if not FILES_BUCKET_NAME:
        raise ApiError(503, "Memory export is unavailable")
    snapshot = _list_user_memories(user_id)
    exported_at = datetime.now(UTC)
    document = {
        "format": "FroggyBot memory export",
        "version": 1,
        "exportedAt": exported_at.isoformat(),
        "rawConversationRetentionDays": snapshot["rawConversationRetentionDays"],
        "memories": snapshot["records"],
    }
    key = f"users/{memory_actor_id(user_id)}/exports/froggybot-memory.json"
    s3.put_object(
        Bucket=FILES_BUCKET_NAME,
        Key=key,
        Body=json.dumps(document, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": FILES_BUCKET_NAME,
            "Key": key,
            "ResponseContentType": "application/json",
            "ResponseContentDisposition": 'attachment; filename="froggybot-memory.json"',
        },
        ExpiresIn=900,
    )
    return {"url": url, "expiresIn": 900}
