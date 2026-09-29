"""Read-only AgentCore Memory inventory and exhaustive identity mapping."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
STRATEGY_TYPES = {"SEMANTIC", "USER_PREFERENCE", "SUMMARIZATION"}
PAGE_SIZE = 100


def canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(k): canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [canonical(v) for v in value]
    return value


def digest(value: Any) -> str:
    raw = json.dumps(
        canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def paged(client: Any, operation: str, result_key: str, **kwargs: Any) -> list[dict]:
    if not client.can_paginate(operation):
        raise ValueError(f"SDK does not support pagination for {operation}")
    result: list[dict] = []
    for page in client.get_paginator(operation).paginate(
        **kwargs, PaginationConfig={"PageSize": PAGE_SIZE}
    ):
        result.extend(page.get(result_key, []))
    return result


def strategy_map(source_memory: dict, destination_memory: dict) -> dict[str, str]:
    def keyed(memory: dict) -> dict[tuple[str, str], dict]:
        result = {}
        for strategy in memory.get("strategies", []):
            key = (strategy.get("type"), strategy.get("name"))
            if key[0] not in STRATEGY_TYPES or not all(key) or key in result:
                raise ValueError("Unexpected or duplicate AgentCore memory strategy")
            if strategy.get("status") != "ACTIVE":
                raise ValueError("AgentCore memory strategy is not ACTIVE")
            result[key] = strategy
        return result

    src, dst = keyed(source_memory), keyed(destination_memory)
    if not src or src.keys() != dst.keys():
        raise ValueError("Source and destination memory strategies differ")
    mapping = {}
    for key, original in src.items():
        target = dst[key]
        if sorted(original.get("namespaceTemplates", [])) != sorted(
            target.get("namespaceTemplates", [])
        ):
            raise ValueError("Source and destination namespace templates differ")
        mapping[original["strategyId"]] = target["strategyId"]
    return mapping


def inventory(client: Any, memory_id: str, strategy_ids: list[str]) -> dict:
    actors = paged(client, "list_actors", "actorSummaries", memoryId=memory_id)
    events: list[dict] = []
    sessions: list[tuple[str, str]] = []
    for actor in actors:
        actor_id = actor["actorId"]
        for session in paged(
            client,
            "list_sessions",
            "sessionSummaries",
            memoryId=memory_id,
            actorId=actor_id,
        ):
            session_id = session["sessionId"]
            sessions.append((actor_id, session_id))
            events.extend(
                paged(
                    client,
                    "list_events",
                    "events",
                    memoryId=memory_id,
                    actorId=actor_id,
                    sessionId=session_id,
                    includePayloads=True,
                )
            )

    listed_actor_ids = {item["actorId"] for item in actors}
    if len(listed_actor_ids) != len(actors) or len(set(sessions)) != len(sessions):
        raise ValueError("Duplicate actors or sessions in memory inventory")
    records_by_id: dict[str, dict] = {}
    for strategy_id in strategy_ids:
        # AgentCore interprets namespacePath as a hierarchy; '/' enumerates
        # every slash-rooted record, including record-only actors. The distinct
        # `namespace` prefix parameter does not behave this way in production.
        for record in paged(
            client,
            "list_memory_records",
            "memoryRecordSummaries",
            memoryId=memory_id,
            memoryStrategyId=strategy_id,
            namespacePath="/",
        ):
            if record.get("memoryStrategyId") != strategy_id:
                raise ValueError(
                    "Memory record strategy filter returned an unexpected ID"
                )
            record_id = record["memoryRecordId"]
            if record_id in records_by_id and records_by_id[record_id] != record:
                raise ValueError("Memory record changed during inventory")
            records_by_id[record_id] = record
    records = list(records_by_id.values())
    if len({e["eventId"] for e in events}) != len(events):
        raise ValueError("Duplicate event IDs in memory inventory")
    for event in events:
        if not isinstance(event.get("payload"), list) or not event["payload"]:
            raise ValueError("An event payload is absent; stopping to avoid data loss")
        if not isinstance(event.get("eventTimestamp"), datetime):
            raise TypeError("An event timestamp is absent")
    for record in records:
        namespaces = record.get("namespaces")
        namespace = (
            namespaces[0]
            if isinstance(namespaces, list) and len(namespaces) == 1
            else None
        )
        parts = namespace.split("/") if isinstance(namespace, str) else []
        if (
            not isinstance(record.get("content", {}).get("text"), str)
            or namespace is None
            or len(parts) < 4
            or parts[0]
            or not parts[2]
            or parts[1] not in {"facts", "preferences", "summaries"}
            or not isinstance(record.get("createdAt"), datetime)
        ):
            raise ValueError(
                "A memory record is incomplete or outside the namespace model"
            )
    actor_ids = listed_actor_ids | {
        record["namespaces"][0].split("/")[2] for record in records
    }
    for record in records:
        parts = record["namespaces"][0].split("/")
        if parts[1] == "summaries":
            if len(parts) < 5 or not parts[3]:
                raise ValueError("Summary record has no session namespace")
            sessions.append((parts[2], parts[3]))
    return {
        "actors": actor_ids,
        "sessions": set(sessions),
        "events": events,
        "records": records,
    }


def source_snapshot_digest(data: dict) -> str:
    return digest(
        {
            "actors": sorted(data["actors"]),
            "sessions": sorted(data["sessions"]),
            "events": sorted(
                [(e["eventId"], event_fields(e)) for e in data["events"]],
                key=lambda row: row[0],
            ),
            "records": sorted(
                [
                    (
                        r["memoryRecordId"],
                        record_fields(r, include_system_metadata=True),
                    )
                    for r in data["records"]
                ],
                key=lambda row: row[0],
            ),
        }
    )


def event_fields(event: dict) -> dict:
    return {
        key: event[key]
        for key in (
            "actorId",
            "sessionId",
            "eventTimestamp",
            "payload",
            "metadata",
            "branch",
        )
        if key in event
    }


def record_fields(record: dict, *, include_system_metadata: bool = False) -> dict:
    fields = {
        key: record[key]
        for key in (
            "content",
            "namespaces",
            "createdAt",
            "metadata",
            "memoryStrategyId",
        )
        if key in record
    }
    if not include_system_metadata and "metadata" in fields:
        # The service regenerates these keys and reserves dateTimeValue for them.
        # Keep them in the source digest, but never submit or compare them as
        # user-supplied record metadata.
        user_metadata = {
            key: value
            for key, value in fields["metadata"].items()
            if not key.startswith("x-amz-agentcore-memory-")
        }
        if user_metadata:
            fields["metadata"] = user_metadata
        else:
            fields.pop("metadata")
    return fields


def read_identity_map(
    path: Path, data: dict
) -> tuple[dict[str, str], dict[tuple[str, str], str], dict]:
    if path.stat().st_mode & 0o077:
        raise ValueError("Identity map must be readable only by its owner (mode 0600)")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return validate_identity_map(raw, data)


def validate_identity_map(
    raw: dict, data: dict
) -> tuple[dict[str, str], dict[tuple[str, str], str], dict]:
    if set(raw) != {"actors", "sessions", "decisions"} or not isinstance(
        raw["actors"], dict
    ):
        raise ValueError(
            "Identity map requires actors, sessions, and decisions objects"
        )
    actors = raw["actors"]
    if set(actors) != data["actors"] or len(set(actors.values())) != len(actors):
        raise ValueError("Actor map must cover every source actor exactly once")
    for value in (*actors.keys(), *actors.values()):
        if (
            not isinstance(value, str)
            or len(value) > 255
            or not ID_PATTERN.fullmatch(value)
        ):
            raise ValueError("Actor map contains an invalid identifier")
    if not isinstance(raw["sessions"], dict) or set(raw["sessions"]) != data["actors"]:
        raise ValueError("Session map must include every source actor")
    sessions = {}
    for actor_id in data["actors"]:
        entries = raw["sessions"][actor_id]
        expected = {s for a, s in data["sessions"] if a == actor_id}
        if not isinstance(entries, dict) or set(entries) != expected:
            raise ValueError("Session map must cover every source session exactly once")
        if len(set(entries.values())) != len(entries):
            raise ValueError("Session map contains a destination collision")
        for src, dest in entries.items():
            if (
                not isinstance(dest, str)
                or len(dest) > 100
                or not ID_PATTERN.fullmatch(dest)
            ):
                raise ValueError("Session map contains an invalid identifier")
            sessions[(actor_id, src)] = dest
    if len({(actors[a], dest) for (a, _), dest in sessions.items()}) != len(sessions):
        raise ValueError("Mapped actor/session pair collision")
    decisions = raw["decisions"]
    if (
        not isinstance(decisions, dict)
        or set(decisions)
        != {"orphanPreservedUnmapped", "historicalSessionsPreservedUnmapped"}
        or not all(isinstance(value, list) for value in decisions.values())
    ):
        raise ValueError("Identity-map preservation decisions are missing")
    seen = set()
    for kind, entries in decisions.items():
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "actorId",
                "sessionId",
                "events",
                "summaries",
            }:
                raise ValueError("Identity-map preservation decision is invalid")
            actor_id, session_id = entry["actorId"], entry["sessionId"]
            if (actor_id, session_id) not in sessions or (actor_id, session_id) in seen:
                raise ValueError(
                    "Identity-map preservation decision has an unknown session"
                )
            seen.add((actor_id, session_id))
            event_count = sum(
                event["actorId"] == actor_id and event["sessionId"] == session_id
                for event in data["events"]
            )
            summary_count = sum(
                record["namespaces"][0].startswith(
                    f"/summaries/{actor_id}/{session_id}/"
                )
                for record in data["records"]
            )
            if entry["events"] != event_count or entry["summaries"] != summary_count:
                raise ValueError("Identity-map preservation count differs from source")
            if kind == "orphanPreservedUnmapped":
                actor_records = [
                    record
                    for record in data["records"]
                    if record["namespaces"][0].split("/")[2] == actor_id
                ]
                actor_events = [
                    event for event in data["events"] if event["actorId"] == actor_id
                ]
                if (
                    len(actor_events) != 1
                    or len(actor_records) != 1
                    or event_count != 1
                    or summary_count != 1
                    or actors[actor_id] != actor_id
                    or sessions[(actor_id, session_id)] != session_id
                    or actor_events[0]
                    .get("metadata", {})
                    .get("heytimScope", {})
                    .get("stringValue")
                    != "personal"
                ):
                    raise ValueError(
                        "Orphan memory shape differs from reviewed exception"
                    )
            elif (
                sessions[(actor_id, session_id)] != session_id
                or not event_count
                or not summary_count
            ):
                raise ValueError(
                    "Historical session shape differs from reviewed exception"
                )
    if len(decisions["orphanPreservedUnmapped"]) > 1:
        raise ValueError("More than one orphan memory actor is not approved")
    return actors, sessions, decisions


def hashed_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verified_cognito_users(
    client: Any, pool_id: str, account: str, region: str
) -> dict[str, str]:
    pool = client.describe_user_pool(UserPoolId=pool_id)["UserPool"]
    if pool.get("Arn") != f"arn:aws:cognito-idp:{region}:{account}:userpool/{pool_id}":
        raise ValueError("Cognito pool belongs to an unexpected account")
    users = {}
    for page in client.get_paginator("list_users").paginate(
        UserPoolId=pool_id, PaginationConfig={"PageSize": 60}
    ):
        for user in page.get("Users", []):
            attributes = {
                item["Name"]: item["Value"] for item in user.get("Attributes", [])
            }
            email = attributes.get("email", "").casefold()
            subject = attributes.get("sub")
            if (
                not email
                or not subject
                or attributes.get("email_verified") != "true"
                or user.get("UserStatus") != "CONFIRMED"
            ):
                continue
            if email in users:
                raise ValueError("Cognito has duplicate verified email identities")
            users[email] = subject
    return users


def source_key_inventory(
    client: Any, table_name: str, account: str, region: str
) -> list[dict[str, str]]:
    table = client.describe_table(TableName=table_name)["Table"]
    if (
        table.get("TableArn")
        != f"arn:aws:dynamodb:{region}:{account}:table/{table_name}"
    ):
        raise ValueError("Source DynamoDB table belongs to an unexpected account")
    keys = []
    for page in client.get_paginator("scan").paginate(
        TableName=table_name,
        ProjectionExpression="#pk,#sk",
        ExpressionAttributeNames={"#pk": "pk", "#sk": "sk"},
        ConsistentRead=True,
        PaginationConfig={"PageSize": 100},
    ):
        for item in page.get("Items", []):
            if not isinstance(item.get("pk"), str) or not isinstance(
                item.get("sk"), str
            ):
                raise TypeError("DynamoDB key inventory contains an invalid item")
            keys.append({"pk": item["pk"], "sk": item["sk"]})
    return keys


def derive_identity_map(
    source_users: dict[str, str],
    destination_users: dict[str, str],
    keys: list[dict[str, str]],
    data: dict,
    *,
    expected_orphans: int = 0,
    expected_historical_sessions: int = 0,
) -> dict:
    if not source_users:
        raise ValueError("Source Cognito pool has no verified users")
    if not set(source_users) <= set(destination_users):
        raise ValueError(
            "A source Cognito user has no unique verified destination match"
        )
    actors: dict[str, str] = {}
    sessions: dict[str, dict[str, str]] = {}
    decisions: dict[str, list[dict]] = {
        "orphanPreservedUnmapped": [],
        "historicalSessionsPreservedUnmapped": [],
    }
    for email, old_subject in source_users.items():
        new_subject = destination_users[email]
        old_actor = hashed_identity(f"user:{old_subject}")
        new_actor = hashed_identity(f"user:{new_subject}")
        if old_actor not in data["actors"]:
            continue
        actors[old_actor] = new_actor
        direct_sessions = {}
        bot_ids = set()
        for item in keys:
            pk, sk = item["pk"], item["sk"]
            if pk == f"USER#{old_subject}" and sk.startswith("BOT#"):
                bot_ids.add(sk.removeprefix("BOT#"))
            chat_prefix = f"CHAT#{old_subject}#"
            if pk.startswith(chat_prefix):
                bot_ids.add(pk.removeprefix(chat_prefix))
        for bot_id in bot_ids:
            if not bot_id:
                continue
            old_session = hashed_identity(f"{old_subject}:{bot_id}")
            if (old_actor, old_session) in data["sessions"]:
                direct_sessions[old_session] = hashed_identity(
                    f"{new_subject}:{bot_id}"
                )
        historical = {
            session for actor, session in data["sessions"] if actor == old_actor
        } - set(direct_sessions)
        for session in sorted(historical):
            direct_sessions[session] = session
            decisions["historicalSessionsPreservedUnmapped"].append(
                preservation_marker(data, old_actor, session)
            )
        sessions[old_actor] = direct_sessions

    group_ids = set()
    for item in keys:
        if item["pk"].startswith("GROUP#") and item["sk"] == "META":
            group_ids.add(item["pk"].removeprefix("GROUP#"))
        if item["pk"].startswith("USER#") and item["sk"].startswith("GROUP#"):
            group_ids.add(item["sk"].removeprefix("GROUP#"))
    for group_id in group_ids:
        if not group_id:
            continue
        actor = hashed_identity(f"group:{group_id}")
        if actor not in data["actors"]:
            continue
        session = hashed_identity(f"group-session:{group_id}")
        actors[actor] = actor
        sessions[actor] = (
            {session: session} if (actor, session) in data["sessions"] else {}
        )

    orphans = data["actors"] - set(actors)
    if len(orphans) != expected_orphans or len(orphans) > 1:
        raise ValueError(
            "Unexplained memory actor count differs from reviewed exception"
        )
    for actor in sorted(orphans):
        actor_sessions = {
            session
            for source_actor, session in data["sessions"]
            if source_actor == actor
        }
        if len(actor_sessions) != 1:
            raise ValueError("Orphan memory actor has an unexpected session count")
        session = next(iter(actor_sessions))
        actors[actor] = actor
        sessions[actor] = {session: session}
        decisions["orphanPreservedUnmapped"].append(
            preservation_marker(data, actor, session)
        )
    if (
        len(decisions["historicalSessionsPreservedUnmapped"])
        != expected_historical_sessions
    ):
        raise ValueError("Historical session count differs from reviewed exception")
    raw = {"actors": actors, "sessions": sessions, "decisions": decisions}
    validate_identity_map(raw, data)
    return raw


def preservation_marker(data: dict, actor_id: str, session_id: str) -> dict:
    return {
        "actorId": actor_id,
        "sessionId": session_id,
        "events": sum(
            event["actorId"] == actor_id and event["sessionId"] == session_id
            for event in data["events"]
        ),
        "summaries": sum(
            record["namespaces"][0].startswith(f"/summaries/{actor_id}/{session_id}/")
            for record in data["records"]
        ),
    }
