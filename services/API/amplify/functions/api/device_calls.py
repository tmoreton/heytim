"""Short-lived Apple client capability leases and exact device-call callbacks."""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from shared.device_tools import (
    DEVICE_LEASE_SECONDS,
    DEVICE_OPERATION_PLATFORMS,
    DEVICE_TOOL_OPERATIONS,
)

from .support import QUEUE_URL, ApiError, _body, _now, _response, sqs, table

DEVICE_ID_PATTERN = re.compile(r"^[a-f0-9-]{36}$")
CALL_ID_PATTERN = re.compile(r"^[a-f0-9]{64}$")
MAX_DEVICE_RESULT_BYTES = 64_000


def _device_id(value: Any) -> str:
    if not isinstance(value, str) or not DEVICE_ID_PATTERN.fullmatch(value):
        raise ApiError(400, "Device id is invalid")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ApiError(400, "Device id is invalid") from exc
    if str(parsed) != value:
        raise ApiError(400, "Device id is invalid")
    return value


def _call_id(value: Any) -> str:
    if not isinstance(value, str) or not CALL_ID_PATTERN.fullmatch(value):
        raise ApiError(400, "Device call id is invalid")
    return value


def _device_key(user_id: str, device_id: str) -> dict[str, str]:
    return {"pk": f"USER#{user_id}", "sk": f"DEVICE#{device_id}"}


def _call_key(user_id: str, call_id: str) -> dict[str, str]:
    return {"pk": f"USER#{user_id}", "sk": f"DEVICE_CALL#{call_id}"}


def _validated_tools(value: Any, platform: str) -> list[dict]:
    if not isinstance(value, list) or len(value) > 4:
        raise ApiError(400, "Device tools are invalid")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"id", "operations"}:
            raise ApiError(400, "Device tool is invalid")
        tool_id = item.get("id")
        operations = item.get("operations")
        allowed = DEVICE_TOOL_OPERATIONS.get(tool_id) if isinstance(tool_id, str) else None
        if (
            not isinstance(tool_id, str)
            or tool_id in seen
            or not allowed
            or not isinstance(operations, list)
            or not operations
            or not all(isinstance(operation, str) for operation in operations)
            or len(operations) != len(set(operations))
            or not set(operations).issubset(allowed)
            or any(DEVICE_OPERATION_PLATFORMS[operation] != platform for operation in operations)
        ):
            raise ApiError(400, "Device tool operations are invalid")
        seen.add(tool_id)
        result.append({"id": tool_id, "operations": operations})
    return result


def _validated_grants(value: Any, tool_ids: set[str]) -> list[dict]:
    if not isinstance(value, list) or len(value) > 100:
        raise ApiError(400, "Device bot grants are invalid")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"botId", "toolIds"}:
            raise ApiError(400, "Device bot grant is invalid")
        bot_id = item.get("botId")
        grant_tools = item.get("toolIds")
        try:
            valid_bot = isinstance(bot_id, str) and str(uuid.UUID(bot_id)) == bot_id
        except ValueError:
            valid_bot = False
        if (
            not valid_bot
            or bot_id in seen
            or not isinstance(grant_tools, list)
            or not grant_tools
            or not all(isinstance(tool_id, str) for tool_id in grant_tools)
            or len(grant_tools) != len(set(grant_tools))
            or not set(grant_tools).issubset(tool_ids)
        ):
            raise ApiError(400, "Device bot grant is invalid")
        seen.add(bot_id)
        result.append({"botId": bot_id, "toolIds": grant_tools})
    return result


def register_device_capabilities(
    user_id: str, device_id: str, value: dict
) -> dict:
    device_id = _device_id(device_id)
    if value.get("schemaVersion") != 1:
        raise ApiError(400, "Device capability schema is unsupported")
    platform = value.get("platform")
    if platform not in {"ios", "macos"}:
        raise ApiError(400, "Device platform is invalid")
    app_version = value.get("appVersion")
    if not isinstance(app_version, str) or not app_version.strip() or len(app_version) > 40:
        raise ApiError(400, "Device app version is invalid")
    tools = _validated_tools(value.get("tools"), platform)
    grants = _validated_grants(value.get("botGrants"), {item["id"] for item in tools})
    current = int(datetime.now(UTC).timestamp())
    item = {
        **_device_key(user_id, device_id),
        "entity": "DEVICE_CAPABILITIES",
        "deviceId": device_id,
        "platform": platform,
        "schemaVersion": 1,
        "appVersion": app_version.strip(),
        "tools": tools,
        "botGrants": grants,
        "lastSeenAt": _now(),
        "leaseExpiresAt": current + DEVICE_LEASE_SECONDS,
        "expiresAt": current + 24 * 60 * 60,
    }
    table.put_item(Item=item)
    return {
        "registered": True,
        "deviceId": device_id,
        "leaseExpiresAt": item["leaseExpiresAt"],
    }


def unregister_device_capabilities(user_id: str, device_id: str) -> dict:
    table.delete_item(Key=_device_key(user_id, _device_id(device_id)))
    return {"unregistered": True}


def _active_device(user_id: str, device_id: str) -> dict:
    item = table.get_item(
        Key=_device_key(user_id, _device_id(device_id)), ConsistentRead=True
    ).get("Item")
    if (
        not item
        or item.get("entity") != "DEVICE_CAPABILITIES"
        or int(item.get("leaseExpiresAt", 0)) <= int(datetime.now(UTC).timestamp())
    ):
        raise ApiError(409, "This device capability lease expired")
    return item


def list_device_calls(user_id: str, device_id: str) -> dict:
    _active_device(user_id, device_id)
    now = int(datetime.now(UTC).timestamp())
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"USER#{user_id}",
            ":prefix": "DEVICE_CALL#",
        },
        ConsistentRead=True,
    ).get("Items", [])
    calls = []
    for item in items:
        proposal = item.get("proposal")
        if (
            item.get("entity") != "DEVICE_CALL"
            or item.get("status") != "PENDING"
            or item.get("deviceId") != device_id
            or int(item.get("expiresAt", 0)) <= now
            or not isinstance(proposal, dict)
        ):
            continue
        calls.append(
            {
                "id": item["id"],
                "turnId": item["turnId"],
                "botId": item["botId"],
                "botName": item.get("botName", "HeyTim"),
                "toolId": proposal["toolId"],
                "operation": proposal["toolName"],
                "arguments": proposal["input"],
                "requestDigest": proposal["digest"],
                "expiresAt": proposal["expiresAt"],
            }
        )
    return {"calls": sorted(calls, key=lambda item: item["expiresAt"])}


def _storable_json(value: Any) -> Any:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise ApiError(400, "Device result must be valid JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_DEVICE_RESULT_BYTES:
        raise ApiError(413, "Device result is too large")
    return json.loads(encoded, parse_float=Decimal)


def _result_response(proposal: dict, value: dict) -> dict:
    if value.get("requestDigest") != proposal.get("digest"):
        raise ApiError(409, "Device call changed before its result arrived")
    status = value.get("status")
    if status == "success" and set(value) == {"requestDigest", "status", "result"}:
        return {
            "id": proposal["id"],
            "digest": proposal["digest"],
            "toolUseId": proposal["toolUseId"],
            "status": "success",
            "result": _storable_json(value["result"]),
        }
    if status == "error" and set(value) == {"requestDigest", "status", "error"}:
        error = value.get("error")
        if not isinstance(error, str) or not error.strip() or len(error) > 1_000:
            raise ApiError(400, "Device error is invalid")
        return {
            "id": proposal["id"],
            "digest": proposal["digest"],
            "toolUseId": proposal["toolUseId"],
            "status": "error",
            "error": error.strip(),
        }
    raise ApiError(400, "Device result outcome is invalid")


def _queue_resume(call: dict) -> None:
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(
            {
                "type": "AGENT_REPLY",
                "userId": call["userId"],
                "botId": call["botId"],
                "turnKey": call["turnKey"],
            }
        ),
    )


def submit_device_call_result(
    user_id: str, device_id: str, call_id: str, value: dict
) -> dict:
    device_id = _device_id(device_id)
    call_id = _call_id(call_id)
    call_key = _call_key(user_id, call_id)
    call = table.get_item(Key=call_key, ConsistentRead=True).get("Item")
    if not call or call.get("entity") != "DEVICE_CALL" or call.get("deviceId") != device_id:
        raise ApiError(404, "Device call not found")
    proposal = call.get("proposal")
    if not isinstance(proposal, dict):
        raise ApiError(409, "Device call is invalid")
    response = _result_response(proposal, value)
    turn_key = {"pk": call["turnPk"], "sk": call["turnKey"]}
    turn = table.get_item(Key=turn_key, ConsistentRead=True).get("Item")
    if not turn:
        raise ApiError(409, "The associated response no longer exists")
    if turn.get("deviceResult") == response:
        _queue_resume(call)
        return {"accepted": True, "turnId": call["turnId"]}
    if (
        call.get("status") != "PENDING"
        or int(call.get("expiresAt", 0)) <= int(datetime.now(UTC).timestamp())
    ):
        raise ApiError(409, "Device call is no longer active")
    try:
        received_at = _now()
        table.update_item(
            Key=turn_key,
            UpdateExpression=(
                "SET #status = :pending, deviceResult = :result, "
                "deviceResultReceivedAt = :now, activity = :activity, "
                "activityUpdatedAt = :now "
                "REMOVE leaseOwner, leaseExpiresAt, runtimeResult"
            ),
            ConditionExpression="#status = :awaiting AND deviceRequest = :request",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":awaiting": "AWAITING_DEVICE",
                ":request": call["request"],
                ":result": response,
                ":activity": ["Received result from authorized device"],
                ":now": received_at,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        current = table.get_item(Key=turn_key, ConsistentRead=True).get("Item")
        if not current or current.get("deviceResult") != response:
            raise ApiError(409, "Device call is no longer active") from exc
    table.update_item(
        Key=call_key,
        UpdateExpression="SET #status = :complete, completedAt = :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":complete": "COMPLETE", ":now": _now()},
    )
    _queue_resume(call)
    return {"accepted": True, "turnId": call["turnId"]}


def device_route(
    user_id: str,
    _display_name: str,
    method: str,
    path: str,
    params: dict,
    event: dict,
) -> dict | None:
    device_id = params.get("deviceId", "")
    if method == "PUT" and path.endswith("/capabilities"):
        return _response(200, register_device_capabilities(user_id, device_id, _body(event)))
    if method == "DELETE" and path.endswith("/capabilities"):
        return _response(200, unregister_device_capabilities(user_id, device_id))
    if method == "GET" and path.endswith("/calls"):
        return _response(200, list_device_calls(user_id, device_id))
    if method == "POST" and path.endswith("/result") and "/calls/" in path:
        return _response(
            202,
            submit_device_call_result(
                user_id, device_id, params.get("callId", ""), _body(event)
            ),
        )
    return None


__all__ = [
    "device_route",
    "list_device_calls",
    "register_device_capabilities",
    "submit_device_call_result",
    "unregister_device_capabilities",
]
