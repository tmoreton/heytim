"""Replay-safe, one-target handoffs from Chief into a saved teammate's chat."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from shared.browser_sessions import ensure_browser_send_allowed
from shared.client_contract import MESSAGE_MAX_LENGTH
from shared.job_envelope import send_job
from shared.work_state import is_in_flight

from .support import QUEUE_URL, _bot_key, _turn_pk, sqs, table


def _direct_chat_api():
    from api import direct_chat

    return direct_chat


def route_bot_task(
    user_id: str, chief: dict, parent_turn: dict, mutation_id: str, value: dict
) -> None:
    if set(value) != {"botId", "task"}:
        raise ValueError("Bot routing fields are invalid")
    target_id = value.get("botId")
    task = value.get("task")
    if not isinstance(target_id, str) or not target_id:
        raise ValueError("The routing target bot is invalid")
    if not isinstance(task, str) or not task.strip() or len(task) > MESSAGE_MAX_LENGTH:
        raise ValueError(f"The routed task must be nonempty text up to {MESSAGE_MAX_LENGTH} characters")
    chief_id = chief.get("id")
    parent_id = parent_turn.get("id")
    created_at = parent_turn.get("createdAt")
    if (
        chief.get("systemRole") != "chief"
        or not isinstance(chief_id, str)
        or parent_turn.get("botId") != chief_id
        or parent_turn.get("userId") != user_id
        or parent_turn.get("pk") != _turn_pk(user_id, chief_id)
        or not isinstance(parent_id, str) or not parent_id
        or parent_turn.get("source") not in {None, "app"}
        or not isinstance(created_at, str) or len(created_at) > 40
    ):
        raise ValueError("Bot routing is available only from a direct Chief chat")
    try:
        if datetime.fromisoformat(created_at.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("missing timezone")
    except ValueError as exc:
        raise ValueError("The Chief routing turn time is invalid") from exc
    live_parent = table.get_item(
        Key={"pk": parent_turn["pk"], "sk": parent_turn.get("sk", "")}, ConsistentRead=True,
    ).get("Item")
    if (
        not live_parent or live_parent.get("id") != parent_id
        or live_parent.get("botId") != chief_id or live_parent.get("userId") != user_id
        or live_parent.get("status") != "RUNNING"
    ):
        raise ValueError("The Chief request is no longer running; its task was not routed")

    direct = _direct_chat_api()
    direct.require_request_consent(user_id)
    current_chief = direct._get_bot(user_id, chief_id)
    target = direct._get_bot(user_id, target_id)
    if current_chief.get("systemRole") != "chief":
        raise ValueError("Chief no longer has permission to route work")
    if target_id == chief_id or target.get("systemRole") == "chief":
        raise ValueError("Choose an existing teammate other than Chief")
    digest = hashlib.sha256(json.dumps(
        [chief_id, parent_id, target_id, task.strip()], ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    marker_key = {"pk": _bot_key(user_id, chief_id)["pk"], "sk": f"BOT_ROUTE#{mutation_id}"}
    identity_fields = (
        "entity", "id", "botId", "userId", "userText", "createdAt", "source",
        "routedFromBotId", "routedFromTurnId",
    )
    lease = direct._claim_send_lease(user_id, target_id)
    try:
        marker = table.get_item(Key=marker_key, ConsistentRead=True).get("Item")
        if not marker:
            marker = {
                **marker_key, "entity": "BOT_ROUTE", "requestDigest": digest,
                "createdAt": direct._now(),
            }
            try:
                table.put_item(Item=marker, ConditionExpression="attribute_not_exists(pk)")
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                marker = table.get_item(Key=marker_key, ConsistentRead=True).get("Item")
        if not marker or marker.get("entity") != "BOT_ROUTE" or marker.get("requestDigest") != digest:
            raise ValueError("This bot routing identity was reused with a different task")
        routed_at = marker["createdAt"]
        item = {
            "pk": _turn_pk(user_id, target_id),
            "sk": f"TURN#{routed_at}#{mutation_id}",
            "entity": "TURN", "id": mutation_id,
            "botId": target_id, "userId": user_id,
            "userText": task.strip(), "createdAt": routed_at, "status": "PENDING",
            "source": "bot_route", "routedFromBotId": chief_id,
            "routedFromTurnId": parent_id,
        }
        key = {"pk": item["pk"], "sk": item["sk"]}
        existing = table.get_item(Key=key, ConsistentRead=True).get("Item")
        if existing:
            if any(existing.get(field) != item[field] for field in identity_fields):
                raise ValueError("This bot routing identity was reused with a different task")
            retry_dispatch = existing.get("status") == "ERROR" and existing.get("handoffDispatchFailed") is True
            if existing.get("handoffQueuedAt") or (existing.get("status") != "PENDING" and not retry_dispatch):
                return
        ensure_browser_send_allowed(table, user_id, target_id)
        active = direct._partition_items(_turn_pk(user_id, target_id))
        if any(is_in_flight(turn.get("status")) and turn.get("id") != mutation_id for turn in active):
            raise ValueError("That teammate is already working. Wait for its current reply before routing another task")
        if not existing:
            try:
                table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                current = table.get_item(Key=key, ConsistentRead=True).get("Item")
                if not current or any(current.get(field) != item[field] for field in identity_fields):
                    raise ValueError("This bot routing identity was reused with a different task") from None
                if current.get("handoffQueuedAt") or current.get("status") != "PENDING":
                    return
        elif retry_dispatch:
            table.update_item(
                Key=key,
                UpdateExpression="SET #status = :pending REMOVE assistantText, completedAt, handoffDispatchFailed",
                ConditionExpression="#status = :error AND handoffDispatchFailed = :failed",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":pending": "PENDING", ":error": "ERROR", ":failed": True},
            )

        queued_at = direct._now()
        table.update_item(
            Key=_bot_key(user_id, target_id),
            UpdateExpression="SET lastMessage = :message, lastMessageAt = :now, updatedAt = :now",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={":message": task.strip(), ":now": queued_at},
        )
        # Save an explicit failed dispatch if the queue is unavailable. A retry
        # reuses this same turn; a worker that already claimed it wins the condition.
        try:
            send_job(sqs, QUEUE_URL, {
                "type": "AGENT_REPLY", "userId": user_id,
                "botId": target_id, "turnKey": item["sk"],
            })
        except Exception:
            try:
                table.update_item(
                    Key=key,
                    UpdateExpression="SET #status = :error, assistantText = :text, completedAt = :now, handoffDispatchFailed = :failed",
                    ConditionExpression="#status = :pending AND attribute_not_exists(leaseOwner)",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":pending": "PENDING", ":error": "ERROR", ":failed": True,
                        ":text": "Chief could not queue this task. Please try again.", ":now": direct._now(),
                    },
                )
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                pass
            raise
        table.update_item(
            Key=key, UpdateExpression="SET handoffQueuedAt = :now",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={":now": queued_at},
        )
    finally:
        direct._release_send_lease(user_id, target_id, lease)


__all__ = ["route_bot_task"]
