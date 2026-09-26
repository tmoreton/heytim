"""Persist, expire, and clean up runtime device-call interrupts."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from shared.device_tools import (
    DEVICE_OPERATION_PLATFORMS,
    DEVICE_TOOL_OPERATIONS,
    select_device,
)
from shared.job_envelope import send_job
from shared.time import utc_now_iso

from .approval_job import delete_approval_snapshot
from .support import QUEUE_URL, _bot_key, sqs, table

DEVICE_CALL_EXPIRY_SECONDS = 5 * 60
MAX_DEVICE_INPUT_BYTES = 8_000
HEX_DIGEST = re.compile(r"^[a-f0-9]{64}$")


def _proposal(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "toolUseId",
        "toolName",
        "input",
        "platform",
        "toolId",
        "digest",
        "expiresAt",
    }:
        raise ValueError("Device proposal is invalid")
    if not all(
        isinstance(value.get(key), str) and value[key]
        for key in (
            "id",
            "toolUseId",
            "toolName",
            "platform",
            "toolId",
            "digest",
            "expiresAt",
        )
    ) or not isinstance(value.get("input"), dict):
        raise ValueError("Device proposal is invalid")
    if (
        value["platform"] not in {"ios", "macos"}
        or value["toolId"] not in DEVICE_TOOL_OPERATIONS
        or value["toolName"] not in DEVICE_TOOL_OPERATIONS[value["toolId"]]
        or DEVICE_OPERATION_PLATFORMS[value["toolName"]] != value["platform"]
        or not HEX_DIGEST.fullmatch(value["digest"])
    ):
        raise ValueError("Device proposal is invalid")
    try:
        input_size = len(
            json.dumps(
                value["input"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Device proposal input is invalid") from exc
    if input_size > MAX_DEVICE_INPUT_BYTES:
        raise ValueError("Device proposal input is too large")
    expires = datetime.fromisoformat(value["expiresAt"].replace("Z", "+00:00"))
    now = datetime.now(UTC)
    if (
        expires.tzinfo is None
        or expires <= now
        or expires > now + timedelta(seconds=DEVICE_CALL_EXPIRY_SECONDS + 30)
    ):
        raise ValueError("Device proposal expired")
    return value


def create_device_call(
    user_id: str,
    bot: dict,
    turn: dict,
    turn_key: dict,
    proposal_value: object,
) -> dict | None:
    proposal = _proposal(proposal_value)
    device = select_device(
        table,
        user_id,
        bot["id"],
        tool_id=proposal["toolId"],
        operation=proposal["toolName"],
        platform=proposal["platform"],
    )
    if not device:
        return None
    call_id = hashlib.sha256(
        json.dumps(
            [user_id, bot["id"], turn["id"], proposal["id"], proposal["digest"]],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request = {
        **proposal,
        "callId": call_id,
        "deviceId": device["deviceId"],
    }
    expires_at = int(
        datetime.fromisoformat(proposal["expiresAt"].replace("Z", "+00:00")).timestamp()
    )
    item = {
        "pk": f"USER#{user_id}",
        "sk": f"DEVICE_CALL#{call_id}",
        "entity": "DEVICE_CALL",
        "id": call_id,
        "status": "PENDING",
        "userId": user_id,
        "botId": bot["id"],
        "botName": bot.get("name", "HeyTim"),
        "turnId": turn["id"],
        "turnPk": turn_key["pk"],
        "turnKey": turn_key["sk"],
        "deviceId": device["deviceId"],
        "proposal": proposal,
        "request": request,
        "createdAt": utc_now_iso(),
        "expiresAt": expires_at,
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        existing = table.get_item(
            Key={"pk": item["pk"], "sk": item["sk"]}, ConsistentRead=True
        ).get("Item")
        if not existing or existing.get("request") != request:
            raise ValueError("Device call identity was reused with different input")
    send_job(
        sqs,
        QUEUE_URL,
        {
            "type": "DEVICE_CALL_EXPIRY",
            "itemKey": turn_key,
            "callId": call_id,
        },
        delay_seconds=DEVICE_CALL_EXPIRY_SECONDS,
    )
    return request


def unavailable_device_result(proposal_value: object) -> dict:
    proposal = _proposal(proposal_value)
    return {
        "id": proposal["id"],
        "digest": proposal["digest"],
        "toolUseId": proposal["toolUseId"],
        "status": "error",
        "error": "No currently authorized device is available for this tool.",
    }


def process_device_call_expiry(request: dict) -> None:
    key = request.get("itemKey")
    call_id = request.get("callId")
    if (
        not isinstance(key, dict)
        or set(key) != {"pk", "sk"}
        or not all(isinstance(value, str) for value in key.values())
        or not isinstance(call_id, str)
        or not HEX_DIGEST.fullmatch(call_id)
    ):
        raise ValueError("Device expiry identity is invalid")
    turn = table.get_item(Key=key, ConsistentRead=True).get("Item")
    active = turn.get("deviceRequest") if turn else None
    if (
        not isinstance(active, dict)
        or active.get("callId") != call_id
        or turn.get("status") != "AWAITING_DEVICE"
    ):
        return
    expires = datetime.fromisoformat(active["expiresAt"].replace("Z", "+00:00"))
    if expires > datetime.now(UTC):
        remaining = max(
            1,
            min(
                DEVICE_CALL_EXPIRY_SECONDS,
                int((expires - datetime.now(UTC)).total_seconds()) + 1,
            ),
        )
        send_job(sqs, QUEUE_URL, request, delay_seconds=remaining)
        return
    message = (
        "The authorized Apple device did not answer in time. No device action was "
        "reported as complete. Reopen Hey Tim on that device and try again."
    )
    try:
        table.update_item(
            Key=key,
            UpdateExpression=(
                "SET #status = :error, assistantText = :message, completedAt = :now "
                "REMOVE deviceRequest, deviceResult, deviceResultReceivedAt, "
                "deviceResultConsumedAt"
            ),
            ConditionExpression="#status = :awaiting AND deviceRequest = :request",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":error": "ERROR",
                ":awaiting": "AWAITING_DEVICE",
                ":message": message,
                ":now": utc_now_iso(),
                ":request": active,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return
    table.update_item(
        Key={"pk": f"USER#{turn['userId']}", "sk": f"DEVICE_CALL#{call_id}"},
        UpdateExpression="SET #status = :expired",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":expired": "EXPIRED"},
    )
    delete_approval_snapshot("direct", turn["userId"], turn["id"], turn["botId"])
    from .notifications import _queue_reply_notification, _update_schedule_result

    bot = table.get_item(
        Key=_bot_key(turn["userId"], turn["botId"]), ConsistentRead=True
    ).get("Item")
    _update_schedule_result(turn, "error", utc_now_iso())
    if bot:
        _queue_reply_notification(
            turn["userId"], turn["botId"], key, turn, bot, message
        )


__all__ = [
    "create_device_call",
    "process_device_call_expiry",
    "unavailable_device_result",
]
