from __future__ import annotations

from typing import Any

from shared.memory_identity import memory_actor_id


def _memory_pages(
    agentcore: Any,
    memory_id: str | None,
    operation: str,
    result_key: str,
    **request,
) -> list[dict]:
    if not memory_id:
        return []
    items = []
    while True:
        try:
            response = getattr(agentcore, operation)(
                memoryId=memory_id, maxResults=100, **request
            )
        except agentcore.exceptions.ResourceNotFoundException:
            return items
        items.extend(response.get(result_key, []))
        next_token = response.get("nextToken")
        if not isinstance(next_token, str) or not next_token:
            return items
        request["nextToken"] = next_token


def delete_user_memory(
    agentcore: Any, memory_id: str | None, user_id: str
) -> dict[str, int]:
    """Delete raw events and extracted records for one hashed actor."""
    if not memory_id:
        return {"events": 0, "records": 0}
    actor_id = memory_actor_id(user_id)
    sessions = _memory_pages(
        agentcore, memory_id, "list_sessions", "sessionSummaries", actorId=actor_id
    )
    events = []
    for session in sessions:
        session_id = session.get("sessionId")
        if not isinstance(session_id, str):
            continue
        events.extend(
            _memory_pages(
                agentcore,
                memory_id,
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
                memoryId=memory_id,
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
            agentcore,
            memory_id,
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
            memoryId=memory_id,
            records=records[offset : offset + 100],
        )
        failures = response.get("failedRecords", [])
        if failures:
            raise RuntimeError(
                f"AgentCore Memory did not delete {len(failures)} records"
            )
    return {"events": len(events), "records": len(records)}
