"""Turn authenticated/routed external events into ordinary bot conversations."""
from __future__ import annotations

import time
import uuid

from shared.account_state import (AccountInactiveError, UserItemConflictError,
                                  UserItemGuardFailedError, account_accepts_writes,
                                  put_user_item_while_account_active)
from shared.ai_consent import ConsentRequired
from shared.browser_session_store import BrowserSessionError
from shared.browser_sessions import ensure_browser_send_allowed
from shared.job_envelope import send_job
from shared.webhooks import (WebhookError, event_key, get_event, get_source, source_key,
                             validate_choice)
from .ai_consent import grants_for_job
from .email_inbound_job import _active_turn_exists, _claim_send_lease, _release_send_lease
from .support import QUEUE_URL, _bot_key, _turn_pk, sqs, table


def _review(key: dict, owner: str, reason: str) -> None:
    table.update_item(Key=key,
        UpdateExpression="SET #status = :review, reviewReason = :reason REMOVE dispatchLeaseOwner, dispatchLeaseExpiresAt, webhookDispatchPk, webhookDispatchSk",
        ConditionExpression="dispatchLeaseOwner = :owner",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":review": "needs_review", ":reason": reason, ":owner": owner})


def _release(key: dict, owner: str) -> None:
    try:
        table.update_item(Key=key,
            UpdateExpression="SET #status = :pending REMOVE dispatchLeaseOwner, dispatchLeaseExpiresAt",
            ConditionExpression="dispatchLeaseOwner = :owner",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":pending": "dispatch_pending", ":owner": owner})
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def process_webhook_dispatch(record: dict, request: dict) -> None:
    user_id, event_id = request.get("userId"), request.get("eventId")
    if not isinstance(user_id, str) or not account_accepts_writes(table, user_id):
        return
    try:
        item = get_event(table, user_id, event_id)
    except WebhookError as exc:
        if exc.status == 404:
            return
        raise
    if item.get("status") not in {"dispatch_pending", "dispatching"}:
        return
    key, owner = event_key(user_id, event_id), record["messageId"]
    now = int(time.time())
    try:
        table.update_item(Key=key,
            UpdateExpression="SET #status = :running, dispatchLeaseOwner = :owner, dispatchLeaseExpiresAt = :expires",
            ConditionExpression="#status = :pending OR (#status = :running AND dispatchLeaseExpiresAt <= :now)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":running": "dispatching", ":pending": "dispatch_pending",
                ":owner": owner, ":expires": now + 60, ":now": now})
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return
    bot_id = None
    bot_lease = False
    try:
        source = get_source(table, user_id, item["sourceId"], enabled=True)
        decision = dict(item.get("routingDecision", {}))
        bot_id = decision.get("botId")
        bot = table.get_item(Key=_bot_key(user_id, bot_id), ConsistentRead=True).get("Item", {})
        effort = decision.get("reasoningEffort", bot.get("reasoningEffort", "high"))
        bot = validate_choice(table, user_id, source, bot_id, effort)
        if not bot or (decision.get("method") == "fixed" and source.get("fallbackBotId") != bot_id):
            raise WebhookError(409, "Source routing policy changed")
        grants_for_job(user_id, user_id, None, None)
        turn_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"heytim:webhook-turn:{user_id}:{event_id}"))
        bot_lease = _claim_send_lease(user_id, bot_id, owner)
        if not bot_lease or _active_turn_exists(user_id, bot_id, turn_id):
            attempt = int(request.get("waitAttempt", 0))
            if attempt >= 240:
                _review(key, owner, "bot_busy")
                return
            _release(key, owner)
            send_job(sqs, QUEUE_URL, {**request, "waitAttempt": attempt + 1}, delay_seconds=15)
            return
        ensure_browser_send_allowed(table, user_id, bot_id)
        decision.update(botId=bot_id, reasoningEffort=effort, eventId=event_id, sourceId=source["id"])
        turn = {"pk": _turn_pk(user_id, bot_id), "sk": f"TURN#{item['createdAt']}#{turn_id}",
                "entity": "TURN", "id": turn_id, "botId": bot_id, "userId": user_id,
                "userText": item["text"], "createdAt": item["createdAt"], "status": "PENDING",
                "source": "webhook", "webhookEventId": event_id,
                "eventSourceId": source["id"], "routingDecision": decision}
        try:
            put_user_item_while_account_active(table, user_id, turn, require_absent=True,
                required_item_condition={"Key": source_key(user_id, source["id"]),
                    "ConditionExpression": "enabled = :enabled AND updatedAt = :updated",
                    "ExpressionAttributeValues": {":enabled": True, ":updated": source["updatedAt"]}})
        except UserItemConflictError:
            stored = table.get_item(Key={"pk": turn["pk"], "sk": turn["sk"]}, ConsistentRead=True).get("Item", {})
            if stored.get("webhookEventId") != event_id or stored.get("eventSourceId") != source["id"]:
                raise WebhookError(409, "Webhook turn identity was already used")
            # Resume the exact persisted turn after an unknown queue outcome; a
            # later bot preference edit must not change its already pinned effort.
            decision = stored["routingDecision"]
            validate_choice(table, user_id, source, decision.get("botId"), decision.get("reasoningEffort"))
        table.update_item(Key=_bot_key(user_id, bot_id),
            UpdateExpression="SET lastMessage = :text, lastMessageAt = :now, updatedAt = :now",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={":text": item["text"][:280], ":now": item["createdAt"]})
        send_job(sqs, QUEUE_URL, {"type": "AGENT_REPLY", "userId": user_id,
                                "botId": bot_id, "turnKey": turn["sk"], "turnId": turn_id})
        table.update_item(Key=key,
            UpdateExpression=("SET #status = :queued, botId = :bot, turnId = :turn, "
                              "routingDecision = :decision REMOVE dispatchLeaseOwner, dispatchLeaseExpiresAt, reviewReason, webhookDispatchPk, webhookDispatchSk"),
            ConditionExpression="dispatchLeaseOwner = :owner",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":queued": "queued", ":bot": bot_id, ":turn": turn_id,
                ":decision": decision, ":owner": owner})
    except (WebhookError, ConsentRequired, BrowserSessionError, UserItemGuardFailedError) as exc:
        reason = "consent_required" if isinstance(exc, ConsentRequired) else "settings_changed"
        _review(key, owner, reason)
    except AccountInactiveError:
        return
    except Exception:
        _release(key, owner)
        raise
    finally:
        if bot_lease:
            _release_send_lease(user_id, bot_id, owner)


def recover_webhook_dispatches() -> None:
    """The existing five-minute watchdog drains the sparse durable outbox."""
    now = int(time.time())
    request = {"IndexName": "WebhookDispatch", "KeyConditionExpression": "webhookDispatchPk = :pending",
               "ExpressionAttributeValues": {":pending": "PENDING"}, "Limit": 100}
    # Bound each recovery sweep; completed rows disappear from the sparse index.
    for _ in range(10):
        response = table.query(**request)
        for item in response.get("Items", []):
            if item.get("status") == "dispatching" and int(item.get("dispatchLeaseExpiresAt", 0)) > now:
                continue
            if item.get("status") in {"dispatch_pending", "dispatching"}:
                send_job(sqs, QUEUE_URL, {"type": "WEBHOOK_DISPATCH", "userId": item["userId"], "eventId": item["id"]})
        if not response.get("LastEvaluatedKey"):
            break
        request["ExclusiveStartKey"] = response["LastEvaluatedKey"]
