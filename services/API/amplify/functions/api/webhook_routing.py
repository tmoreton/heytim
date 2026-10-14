"""Authenticated Mac routing leases, bounded results, and manual inbox routing."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from datetime import UTC, datetime

from shared.account_state import account_accepts_writes, put_user_item_while_account_active
from shared.job_envelope import send_job
from shared.webhooks import (DEVICE_LEASE_SECONDS, MODEL_ID, MODEL_REVISION, ROUTING_LEASE_SECONDS,
                             WebhookError, eligible_bots, event_key, get_event, get_source, identifier,
                             number, partition, public_event, request_digest, routing_device_key,
                             validate_choice, reasoning_decision)
from .ai_consent import require_request_consent
from .support import ApiError, QUEUE_URL, _body, _now, _response, sqs, table
from .webhook_sources import delete_source, list_sources, rotate_source, save_source


def register_router(user_id: str, device_id: str, value: dict) -> dict:
    identifier(device_id)
    if (value.get("schemaVersion") != 1 or value.get("modelId") != MODEL_ID
            or value.get("modelRevision") != MODEL_REVISION):
        raise WebhookError(400, "Routing model/schema version is unsupported")
    version = value.get("appVersion")
    if not isinstance(version, str) or not 1 <= len(version) <= 80:
        raise WebhookError(400, "appVersion is invalid")
    now = int(time.time())
    item = {**routing_device_key(user_id, device_id), "entity": "ROUTING_DEVICE",
            "deviceId": device_id, "platform": "macos", "modelId": MODEL_ID,
            "modelRevision": MODEL_REVISION, "appVersion": version,
            "leaseExpiresAt": now + DEVICE_LEASE_SECONDS, "expiresAt": now + 86400}
    put_user_item_while_account_active(table, user_id, item)
    return {"registered": True, "deviceId": device_id, "leaseExpiresAt": item["leaseExpiresAt"]}


def _active_router(user_id: str, device_id: str, *, allow_expired: bool = False) -> dict:
    item = table.get_item(Key=routing_device_key(user_id, device_id), ConsistentRead=True).get("Item", {})
    if (item.get("entity") != "ROUTING_DEVICE" or (not allow_expired and int(item.get("leaseExpiresAt", 0)) <= int(time.time()))
            or item.get("modelId") != MODEL_ID or item.get("modelRevision") != MODEL_REVISION):
        raise WebhookError(409, "Routing device registration expired")
    return item


def list_requests(user_id: str, device_id: str) -> dict:
    _active_router(user_id, device_id)
    now = int(time.time())
    items = sorted(partition(table, user_id, "WEBHOOK_EVENT#"), key=lambda item: item["createdAt"])
    for item in items:
        if item.get("status") not in {"awaiting_routing", "routing"} or int(item.get("expiresAt", 0)) <= now:
            continue
        try:
            source = get_source(table, user_id, item["sourceId"], enabled=True)
        except WebhookError:
            continue
        if item.get("status") == "routing" and int(item.get("routingLeaseExpiresAt", 0)) > now:
            if item.get("routingDeviceId") != device_id:
                continue
            bots = item["routingBots"]
        else:
            bots = eligible_bots(table, user_id, source)
            if not bots or len(bots) > 32:
                table.update_item(Key=event_key(user_id, item["id"]),
                    UpdateExpression="SET #status = :review, reviewReason = :reason",
                    ConditionExpression="#status = :awaiting OR (#status = :routing AND routingLeaseExpiresAt <= :now)",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={":review": "needs_review", ":reason": "no_eligible_bots" if not bots else "too_many_candidates",
                        ":awaiting": "awaiting_routing", ":routing": "routing", ":now": now})
                continue
            item = {**item, "status": "routing", "routingDeviceId": device_id,
                    "routingLeaseToken": secrets.token_urlsafe(24),
                    "routingLeaseExpiresAt": now + ROUTING_LEASE_SECONDS,
                    "routingBots": bots, "requestDigest": request_digest(item, bots)}
            try:
                table.update_item(Key=event_key(user_id, item["id"]),
                    UpdateExpression=("SET #status = :routing, routingDeviceId = :device, "
                        "routingLeaseToken = :token, routingLeaseExpiresAt = :expires, "
                        "routingBots = :bots, requestDigest = :digest"),
                    ConditionExpression=("#status = :awaiting OR (#status = :routing AND routingLeaseExpiresAt <= :now)"),
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={":routing": "routing", ":awaiting": "awaiting_routing",
                        ":device": device_id, ":token": item["routingLeaseToken"], ":expires": item["routingLeaseExpiresAt"],
                        ":bots": bots, ":digest": item["requestDigest"], ":now": now})
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                continue
        return {"requests": [{"id": item["id"], "text": item["text"], "bots": bots,
            "requestDigest": item["requestDigest"], "leaseToken": item["routingLeaseToken"],
            "expiresAt": datetime.fromtimestamp(int(item["routingLeaseExpiresAt"]), UTC).isoformat(),
            "modelId": MODEL_ID, "modelRevision": MODEL_REVISION}]}
    return {"requests": []}


def _queue_event(user_id: str, event_id: str) -> None:
    send_job(sqs, QUEUE_URL, {"type": "WEBHOOK_DISPATCH", "userId": user_id, "eventId": event_id})


def submit_result(user_id: str, device_id: str, event_id: str, value: dict) -> dict:
    _active_router(user_id, device_id, allow_expired=True)
    item = get_event(table, user_id, event_id)
    if value.get("modelId") != MODEL_ID or value.get("modelRevision") != MODEL_REVISION:
        raise WebhookError(400, "Routing model identity does not match")
    if (not isinstance(value.get("leaseToken"), str) or not isinstance(value.get("requestDigest"), str)
            or item.get("routingDeviceId") != device_id
            or not secrets.compare_digest(value["leaseToken"], item.get("routingLeaseToken", ""))
            or not secrets.compare_digest(value["requestDigest"], item.get("requestDigest", ""))):
        raise WebhookError(409, "Routing request does not match this device lease")
    confidence = number(value.get("confidence"), "confidence")
    probabilities = value.get("probabilities", {})
    if not isinstance(probabilities, dict) or len(probabilities) > 100 or any(not isinstance(key, str) or len(key) > 100 for key in probabilities):
        raise WebhookError(400, "Routing probabilities are invalid")
    probabilities = {key: number(probability, "probability") for key, probability in probabilities.items()}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    if item.get("routingResultDigest") == digest:
        if item["status"] == "dispatch_pending":
            _queue_event(user_id, event_id)
        return {"accepted": True, "eventId": event_id, "status": item["status"]}
    if item.get("status") != "routing" or int(item.get("routingLeaseExpiresAt", 0)) <= int(time.time()):
        raise WebhookError(409, "Routing lease expired or was already consumed")
    source = get_source(table, user_id, item["sourceId"], enabled=True)
    bots = eligible_bots(table, user_id, source)
    if request_digest(item, bots) != item["requestDigest"]:
        table.update_item(Key=event_key(user_id, event_id),
            UpdateExpression="SET #status = :awaiting REMOVE routingLeaseExpiresAt",
            ConditionExpression="routingLeaseToken = :token",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":awaiting": "awaiting_routing", ":token": value["leaseToken"]})
        raise WebhookError(409, "The bot catalog changed; obtain a new routing request")
    candidate_ids = {bot["id"] for bot in bots} | {"clarify"}
    empty_abstention = not probabilities and value.get("botId") is None and confidence == 0
    if not empty_abstention:
        if set(probabilities) != candidate_ids or abs(sum(probabilities.values()) - 1) > number(.0001 * len(candidate_ids), "tolerance"):
            raise WebhookError(400, "Routing probabilities must describe every eligible bot and clarify and sum to one")
        count = len(candidate_ids)
        concentration = max(number(0, "floor"), (count * max(probabilities.values()) - 1) / (count - 1))
        if abs(concentration - confidence) > number(.0002, "tolerance"):
            raise WebhookError(400, "Routing confidence must match official choice concentration")
    bot_id = value.get("botId")
    effort = value.get("reasoningEffort")
    if not isinstance(effort, str) or effort not in {"low", "high", "max"}:
        raise WebhookError(400, "reasoningEffort must be low, high, or max")
    selected_bot = validate_choice(table, user_id, source, bot_id, effort) if bot_id is not None else None
    reasoning = reasoning_decision(value, selected_bot)
    effort = reasoning["reasoningEffort"]
    decision = {"method": "local", "botId": bot_id, **reasoning,
                "confidence": confidence, "probabilities": probabilities,
                "modelId": MODEL_ID, "modelRevision": MODEL_REVISION,
                "sourceId": item["sourceId"], "eventId": event_id}
    status = "needs_review"
    if bot_id is not None:
        chosen = probabilities.get(bot_id, number(0, "probability"))
        runner_up = max((prob for key, prob in probabilities.items() if key != bot_id), default=number(0, "probability"))
        if chosen == max(probabilities.values()) and confidence >= number(0.8, "confidence") and chosen - runner_up >= number(.15, "margin"):
            require_request_consent(user_id)
            status = "dispatch_pending"
    outbox = ", webhookDispatchPk = :outbox, webhookDispatchSk = :sort" if status == "dispatch_pending" else " REMOVE webhookDispatchPk, webhookDispatchSk"
    table.update_item(Key=event_key(user_id, event_id),
        UpdateExpression="SET #status = :status, routingDecision = :decision, routingResultDigest = :result, reviewReason = :reason" + outbox,
        ConditionExpression="#status = :routing AND routingLeaseToken = :token AND routingLeaseExpiresAt > :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":status": status, ":decision": decision, ":result": digest,
            ":reason": "low_confidence" if bot_id is not None else "no_match", ":routing": "routing",
            ":token": value["leaseToken"], ":now": int(time.time()),
            **({":outbox": "PENDING", ":sort": f"{item['createdAt']}#{event_id}"} if status == "dispatch_pending" else {})})
    if status == "dispatch_pending":
        _queue_event(user_id, event_id)
    return {"accepted": True, "eventId": event_id, "status": status}


def manual_route(user_id: str, event_id: str, value: dict) -> dict:
    require_request_consent(user_id)
    item = get_event(table, user_id, event_id)
    if item.get("status") in {"queued", "test"}:
        raise WebhookError(409, "This event was already routed or is a test")
    source = get_source(table, user_id, item["sourceId"], enabled=True)
    bot_id = value.get("botId")
    raw_bot = table.get_item(Key={"pk": f"USER#{user_id}", "sk": f"BOT#{bot_id}"}, ConsistentRead=True).get("Item", {})
    effort = value.get("reasoningEffort", raw_bot.get("reasoningEffort", "high"))
    validate_choice(table, user_id, source, bot_id, effort)
    decision = {"method": "manual", "botId": bot_id, "reasoningEffort": effort,
                "confidence": 1, "sourceId": item["sourceId"], "eventId": event_id}
    try:
        table.update_item(Key=event_key(user_id, event_id),
            UpdateExpression="SET #status = :pending, routingDecision = :decision, webhookDispatchPk = :outbox, webhookDispatchSk = :sort REMOVE routingLeaseExpiresAt, routingResultDigest",
            ConditionExpression="attribute_exists(pk) AND #status <> :queued AND #status <> :dispatching AND #status <> :pending AND #status <> :test",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":pending": "dispatch_pending", ":decision": decision,
                ":queued": "queued", ":dispatching": "dispatching", ":test": "test",
                ":outbox": "PENDING", ":sort": f"{item['createdAt']}#{event_id}"})
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise WebhookError(409, "This event is already being dispatched") from exc
    _queue_event(user_id, event_id)
    return {"accepted": True, "eventId": event_id, "status": "dispatch_pending"}


def webhook_route(user_id: str, _display_name: str, method: str, path: str, params: dict, event: dict) -> dict | None:
    try:
        if path == "/webhook-sources":
            return _response(200 if method == "GET" else 201,
                list_sources(user_id, event) if method == "GET" else save_source(user_id, _body(event), event))
        if path.startswith("/webhook-sources/"):
            source_id = params.get("sourceId", "")
            if method == "DELETE":
                return _response(200, delete_source(user_id, source_id))
            if path.endswith("/rotate"):
                return _response(200, rotate_source(user_id, source_id, event))
            return _response(200, save_source(user_id, _body(event), event, source_id))
        if path == "/webhook-events":
            items = sorted(partition(table, user_id, "WEBHOOK_EVENT#"), key=lambda item: item["createdAt"], reverse=True)
            return _response(200, {"events": [public_event(item) for item in items[:200]]})
        if path.startswith("/webhook-events/"):
            return _response(202, manual_route(user_id, params.get("eventId", ""), _body(event)))
        device_id = params.get("deviceId", "")
        if path.endswith("/routing"):
            if method == "DELETE":
                table.delete_item(Key=routing_device_key(user_id, device_id))
                return _response(200, {"registered": False})
            return _response(200, register_router(user_id, device_id, _body(event)))
        if path.endswith("/routing-requests"):
            return _response(200, list_requests(user_id, device_id))
        if path.endswith("/result"):
            return _response(200, submit_result(user_id, device_id, params.get("requestId", ""), _body(event)))
        return None
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(409, "The webhook request changed; refresh and try again") from exc
    except WebhookError as exc:
        raise ApiError(exc.status, str(exc)) from exc
