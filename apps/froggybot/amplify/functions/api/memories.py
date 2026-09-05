from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from shared.memory_identity import direct_session_id, memory_actor_id

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
    """Delete both raw events and extracted records for one hashed actor."""
    if not FROGBOT_MEMORY_ID:
        return {"events": 0, "records": 0}
    actor_id = memory_actor_id(user_id)
    sessions = _memory_pages("list_sessions", "sessionSummaries", actorId=actor_id)
    events = []
    for session in sessions:
        session_id = session.get("sessionId")
        if not isinstance(session_id, str):
            continue
        events.extend(
            _memory_pages(
                "list_events",
                "events",
                actorId=actor_id,
                sessionId=session_id,
                includePayloads=False,
            )
        )
    for event in events:
        session_id = event.get("sessionId")
        event_id = event.get("eventId")
        if isinstance(session_id, str) and isinstance(event_id, str):
            agentcore.delete_event(
                memoryId=FROGBOT_MEMORY_ID,
                actorId=actor_id,
                sessionId=session_id,
                eventId=event_id,
            )

    records_by_id = {}
    for namespace_path in (
        f"/facts/{actor_id}/",
        f"/preferences/{actor_id}/",
        f"/summaries/{actor_id}/",
    ):
        records = _memory_pages(
            "list_memory_records",
            "memoryRecordSummaries",
            namespacePath=namespace_path,
        )
        for record in records:
            record_id = record.get("memoryRecordId")
            if isinstance(record_id, str):
                records_by_id[record_id] = {"memoryRecordId": record_id}
    records = list(records_by_id.values())
    for offset in range(0, len(records), 100):
        response = agentcore.batch_delete_memory_records(
            memoryId=FROGBOT_MEMORY_ID,
            records=records[offset : offset + 100],
        )
        failures = response.get("failedRecords", [])
        if failures:
            raise RuntimeError(
                f"AgentCore Memory did not delete {len(failures)} records"
            )
    return {"events": len(events), "records": len(records)}


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
            }
            if kind == "summary":
                parts = namespace.strip("/").split("/")
                if len(parts) >= 3:
                    item.update(bot_sessions.get(parts[2], {}))
            records.append(item)
    records.sort(key=lambda item: item["createdAt"], reverse=True)
    return {"records": records, "rawConversationRetentionDays": 30}


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
        "memoryStrategyId": record.get("memoryStrategyId"),
    }
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
