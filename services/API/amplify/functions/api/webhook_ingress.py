"""Verified, bounded Pebble Index multipart and generic JSON webhook ingress."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from email.parser import BytesParser
from email.policy import default

from shared.account_state import (
    AccountInactiveError,
    UserItemConflictError,
    UserItemGuardFailedError,
    account_accepts_writes,
    put_user_item_while_account_active,
)
from shared.job_envelope import send_job
from shared.webhooks import (
    EVENT_RETENTION_SECONDS,
    MAX_TEXT,
    WebhookError,
    event_key,
    get_source,
    owner_key,
    source_key,
    text_at_path,
)

from .support import QUEUE_URL, ApiError, _now, _response, catalog, sqs, table

MAX_BODY_BYTES = 3_000_000  # Fits Lambda's synchronous event limit after base64 expansion.


def headers(event: dict) -> dict:
    return {str(key).lower(): value for key, value in (event.get("headers") or {}).items()
            if isinstance(value, str)}


def raw_body(event: dict) -> bytes:
    body = event.get("body")
    if not isinstance(body, str) or len(body) > MAX_BODY_BYTES * 4 // 3 + 4:
        raise WebhookError(413, "Webhook body exceeds the size limit")
    try:
        raw = base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body.encode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise WebhookError(400, "Webhook body is invalid") from exc
    if len(raw) > MAX_BODY_BYTES:
        raise WebhookError(413, "Webhook body exceeds the size limit")
    return raw


def _fresh_timestamp(value: str) -> None:
    if not re.fullmatch(r"[0-9]{10,12}", value) or abs(int(value) - int(time.time())) > 300:
        raise WebhookError(401, "Webhook signature timestamp is stale")


def authenticate(source: dict, secret: dict, raw: bytes, hs: dict) -> tuple[str | None, bool]:
    mode = source.get("authentication", "either")
    pebble = source["kind"] == "pebble"
    signature_header = "x-index-signature" if pebble else "x-webhook-signature"
    signature = hs.get(signature_header)
    # Any partial signed request must fail verification; bearer never downgrades it.
    signed = signature is not None or any(key in hs for key in (
        ("x-index-timestamp", "x-index-delivery") if pebble else ("x-webhook-timestamp",)))
    delivery = hs.get("x-index-delivery" if pebble else "x-webhook-id")
    is_test = hs.get("x-index-test", "false").lower() == "true" if pebble else False
    if signed:
        if mode == "bearer":
            raise WebhookError(401, "This source requires bearer authentication")
        timestamp = hs.get("x-index-timestamp" if pebble else "x-webhook-timestamp", "")
        _fresh_timestamp(timestamp)
        if pebble:
            trigger = hs.get("x-index-trigger", "")
            if (hs.get("x-index-webhook-version") != "1"
                    or trigger not in {"single-click-hold", "double-click-hold", "test-event"}
                    or not delivery or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", delivery)):
                raise WebhookError(401, "Pebble webhook signature metadata is invalid")
            prefix = f"v1\n{timestamp}\n{delivery}\n{trigger}\n{int(is_test)}\n".encode()
            expected = hmac.new(secret["signingSecret"].encode(), prefix + raw, hashlib.sha256).hexdigest()
            valid = isinstance(signature, str) and bool(re.fullmatch(r"[a-f0-9]{64}", signature)) and hmac.compare_digest(expected, signature)
        else:
            expected = hmac.new(secret["signingSecret"].encode(), timestamp.encode() + b"." + raw,
                                hashlib.sha256).hexdigest()
            valid = isinstance(signature, str) and bool(re.fullmatch(r"sha256=[a-f0-9]{64}", signature)) and hmac.compare_digest(f"sha256={expected}", signature)
        if not valid:
            raise WebhookError(401, "Webhook signature is invalid")
    else:
        if mode == "hmac":
            raise WebhookError(401, "This source requires a signed webhook")
        authorization = hs.get("authorization", "")
        if not hmac.compare_digest(authorization.encode("utf-8"), f"Bearer {secret['credential']}".encode()):
            raise WebhookError(401, "Webhook credential is invalid")
    return delivery, is_test


def normalize(source: dict, raw: bytes, hs: dict) -> tuple[str, str | None, object]:
    content_type = hs.get("content-type", "").lower()
    if source["kind"] == "pebble":
        if not content_type.startswith("multipart/form-data;"):
            raise WebhookError(415, "Pebble sends multipart/form-data")
        if len(hs.get("content-type", "")) > 500 or any(c in hs.get("content-type", "") for c in "\r\n"):
            raise WebhookError(400, "Multipart content type is invalid")
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + hs["content-type"].encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw)
        if not message.is_multipart() or message.defects:
            raise WebhookError(400, "Multipart body is invalid")
        values = {}
        parts = list(message.iter_parts())
        if len(parts) > 8:
            raise WebhookError(400, "Too many multipart fields")
        for part in parts:
            name = part.get_param("name", header="content-disposition")
            if name in {"transcription", "recordedAt", "client"}:
                if name in values:
                    raise WebhookError(400, "Duplicate multipart fields")
                data = part.get_payload(decode=True) or b""
                if len(data) > MAX_TEXT * 4:
                    raise WebhookError(413, "Webhook text exceeds the size limit")
                try:
                    values[name] = data.decode("utf-8")
                except UnicodeError as exc:
                    raise WebhookError(400, "Webhook text must be UTF-8") from exc
        text = values.get("transcription", "")
        recorded_at = values.get("recordedAt")
        if not isinstance(recorded_at, str) or not re.fullmatch(r"[0-9]{10,16}", recorded_at):
            raise WebhookError(400, "Pebble recordedAt must be a Unix millisecond timestamp")
        event_id = None
    else:
        if not content_type.startswith("application/json"):
            raise WebhookError(415, "Generic webhooks require application/json")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise WebhookError(400, "Webhook JSON is invalid") from exc
        if not isinstance(value, dict):
            raise WebhookError(400, "Webhook JSON must be an object")
        text = (text_at_path(value, source["textPath"]) if source.get("textPath")
                else value.get("text", value.get("transcript", value.get("transcription"))))
        event_id = value.get("eventId", value.get("id"))
        recorded_at = value.get("recordedAt")
    try:
        text_bytes = text.encode("utf-8") if isinstance(text, str) else b""
    except UnicodeError as exc:
        raise WebhookError(400, "Webhook text must contain valid Unicode") from exc
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or len(text_bytes) > 16_000:
        raise WebhookError(422, f"A transcript/text of 1 to {MAX_TEXT} characters is required")
    if event_id is not None and (not isinstance(event_id, str) or not 1 <= len(event_id) <= 200):
        raise WebhookError(400, "Webhook event identity is invalid")
    if recorded_at is not None and (isinstance(recorded_at, bool) or not isinstance(recorded_at, (str, int)) or len(str(recorded_at)) > 80):
        raise WebhookError(400, "recordedAt is invalid")
    return text.strip(), event_id, recorded_at


def _rate_limit(user_id: str, source_id: str) -> None:
    now = int(time.time())
    for scope, limit in ((f"source:{source_id}", 30), (f"user:{user_id}", 120)):
        try:
            table.update_item(Key={"pk": f"USER#{user_id}", "sk": f"WEBHOOK_RATE#{scope}#{now // 60}"},
                              UpdateExpression="SET expiresAt = :ttl ADD requestCount :one",
                              ConditionExpression="attribute_not_exists(requestCount) OR requestCount < :limit",
                              ExpressionAttributeValues={":ttl": now + 120, ":one": 1, ":limit": limit})
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise WebhookError(429, "Webhook rate limit reached") from exc


def ingest(event: dict, source_id: str) -> dict:
    owner = table.get_item(Key=owner_key(source_id), ConsistentRead=True).get("Item", {})
    user_id = owner.get("userId")
    if not isinstance(user_id, str) or not account_accepts_writes(table, user_id):
        raise WebhookError(404, "Webhook source not found")
    source = get_source(table, user_id, source_id, enabled=True)
    raw, hs = raw_body(event), headers(event)
    secret = catalog._secret_document(source["secretArn"])
    delivery_id, is_test = authenticate(source, secret, raw, hs)
    text, json_id, recorded_at = normalize(source, raw, hs)
    # Multipart retry boundaries/audio framing change even for one legacy recording.
    digest = hashlib.sha256(json.dumps([text, recorded_at, is_test], separators=(",", ":")).encode()).hexdigest()
    # Generic optional HTTP IDs are not covered by its signature; use signed JSON identity.
    delivery_id = (delivery_id or digest) if source["kind"] == "pebble" else (json_id or hashlib.sha256(raw).hexdigest())
    if not 1 <= len(delivery_id) <= 200:
        raise WebhookError(400, "Webhook delivery identity is invalid")
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"heytim:{source_id}:{delivery_id}"))
    key = event_key(user_id, event_id)
    existing = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if existing:
        if existing.get("payloadDigest") != digest:
            raise WebhookError(409, "Delivery identity was reused with different content")
        # Recover a failed queue handoff without creating another event/turn.
        if existing.get("status") == "dispatch_pending":
            send_job(sqs, QUEUE_URL, {"type": "WEBHOOK_DISPATCH", "userId": user_id, "eventId": event_id})
        return {"accepted": True, "eventId": event_id, "status": existing["status"]}
    _rate_limit(user_id, source_id)
    now = _now()
    item = {**key, "entity": "WEBHOOK_EVENT", "id": event_id, "userId": user_id,
            "sourceId": source_id, "sourceName": source["name"], "sourceKind": source["kind"],
            "text": text, "payloadDigest": digest, "deliveryId": delivery_id,
            "status": "test" if is_test else ("dispatch_pending" if source["routingMode"] == "fixed" else "awaiting_routing"),
            "isTest": is_test, "createdAt": now,
            "expiresAt": int(time.time()) + EVENT_RETENTION_SECONDS,
            **({"recordedAt": str(recorded_at)} if recorded_at is not None else {})}
    if item["status"] == "dispatch_pending":
        item.update(webhookDispatchPk="PENDING", webhookDispatchSk=f"{now}#{event_id}")
        item["routingDecision"] = {"botId": source["fallbackBotId"], "method": "fixed",
                                    "sourceId": source_id, "eventId": event_id, "confidence": 1}
    try:
        put_user_item_while_account_active(table, user_id, item, require_absent=True,
            required_item_condition={"Key": source_key(user_id, source_id),
                "ConditionExpression": "enabled = :enabled AND credentialVersion = :version",
                "ExpressionAttributeValues": {":enabled": True, ":version": source["credentialVersion"]}})
    except UserItemConflictError:
        return ingest(event, source_id)
    except (AccountInactiveError, UserItemGuardFailedError) as exc:
        raise WebhookError(409, "Webhook source changed; retry with its current credential") from exc
    if item["status"] == "dispatch_pending":
        send_job(sqs, QUEUE_URL, {"type": "WEBHOOK_DISPATCH", "userId": user_id, "eventId": event_id})
    return {"accepted": True, "eventId": event_id, "status": item["status"]}


def incoming_webhook(event: dict, source_id: str) -> dict:
    try:
        return _response(202, ingest(event, source_id))
    except WebhookError as exc:
        raise ApiError(exc.status, str(exc)) from exc
