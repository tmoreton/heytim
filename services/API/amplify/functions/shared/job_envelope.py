"""Versioned queue messages shared by every AgentJobs producer and consumer."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

JOB_SCHEMA_VERSION = 1
KNOWN_JOB_TYPES = frozenset(
    {
        "AGENT_REPLY",
        "APPROVAL_EXPIRY",
        "BACKGROUND_WORK_POLL",
        "CATALOG_REFRESH",
        "DELETE_ACCOUNT",
        "DELETE_MEMORY_ACTOR",
        "DELETE_MEMORY_SESSION",
        "DEVICE_CALL_EXPIRY",
        "EMAIL_INBOUND",
        "EVENT_GROUP_ROUND",
        "GROUP_AGENT_CONTRIBUTOR",
        "GROUP_AGENT_REPLY",
        "GROUP_AGENT_ROUND",
        "GROUP_DECISION_EVENT",
        "PLAID_LEDGER_DELETE",
        "PLAID_SYNC",
        "PUSH_NOTIFICATION",
        "PUSH_RECEIPTS",
        "SCHEDULED_AGENT_REPLY",
        "SCHEDULED_GROUP_ROUND",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,255}$")
_METADATA_FIELDS = frozenset(
    {"schemaVersion", "correlationId", "idempotencyKey", "occurredAt"}
)


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Job payload must be JSON-compatible") from exc


def _correlation_id(payload: Mapping[str, Any]) -> str:
    existing = payload.get("correlationId")
    if isinstance(existing, str) and _IDENTIFIER.fullmatch(existing):
        return existing
    for field in ("runId", "executionId", "turnId", "callId", "messageId"):
        value = payload.get(field)
        if isinstance(value, str) and _IDENTIFIER.fullmatch(value):
            return value
    return str(uuid.uuid4())


def envelope_job(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise TypeError("Job payload must be an object")
    body = {key: value for key, value in payload.items() if key not in _METADATA_FIELDS}
    job_type = body.get("type", "AGENT_REPLY")
    if job_type not in KNOWN_JOB_TYPES:
        raise ValueError(f"Unknown job type: {job_type}")
    body["type"] = job_type
    correlation_id = _correlation_id(payload)
    digest_source = {**body, "correlationId": correlation_id}
    idempotency_key = hashlib.sha256(_canonical(digest_source)).hexdigest()
    return {
        "schemaVersion": JOB_SCHEMA_VERSION,
        "type": job_type,
        "correlationId": correlation_id,
        "idempotencyKey": idempotency_key,
        "occurredAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        **{key: value for key, value in body.items() if key != "type"},
    }


def decode_job(body: Any) -> dict[str, Any]:
    try:
        value = json.loads(body) if isinstance(body, str) else body
    except json.JSONDecodeError as exc:
        raise ValueError("Job body must be valid JSON") from exc
    if not isinstance(value, dict):
        raise TypeError("Job body must be an object")
    version = value.get("schemaVersion")
    if version is None:
        # Compatibility for messages already in the queue during rollout.
        legacy = dict(value)
        legacy.setdefault("type", "AGENT_REPLY")
        if legacy["type"] not in KNOWN_JOB_TYPES:
            raise ValueError(f"Unknown job type: {legacy['type']}")
        return legacy
    if version != JOB_SCHEMA_VERSION:
        raise ValueError(f"Unsupported job schema version: {version}")
    if value.get("type") not in KNOWN_JOB_TYPES:
        raise ValueError(f"Unknown job type: {value.get('type')}")
    for field in ("correlationId", "idempotencyKey"):
        if not isinstance(value.get(field), str) or not _IDENTIFIER.fullmatch(value[field]):
            raise ValueError(f"Job {field} is invalid")
    occurred_at = value.get("occurredAt")
    if not isinstance(occurred_at, str):
        raise TypeError("Job occurredAt is invalid")
    try:
        parsed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Job occurredAt is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("Job occurredAt is invalid")
    return value


def send_job(
    client: Any,
    queue_url: str,
    payload: Mapping[str, Any],
    *,
    delay_seconds: int | None = None,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "QueueUrl": queue_url,
        "MessageBody": json.dumps(envelope_job(payload), separators=(",", ":")),
    }
    if delay_seconds is not None:
        request["DelaySeconds"] = delay_seconds
    return client.send_message(**request)


__all__ = [
    "JOB_SCHEMA_VERSION",
    "KNOWN_JOB_TYPES",
    "decode_job",
    "envelope_job",
    "send_job",
]
