from __future__ import annotations

import hashlib
import json
import logging
import urllib.request
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import BotoCoreError, ClientError
from shared.push_delivery import receipt_key, receipt_status, ticket_status

from .support import (
    EMAIL_QUEUE_URL,
    EXPO_PUSH_URL,
    EXPO_RECEIPTS_URL,
    QUEUE_URL,
    _push_owner_key,
    _push_token_key,
    _schedule_key,
    sns,
    sqs,
    table,
)

logger = logging.getLogger(__name__)
NOTIFICATION_DEDUP_SECONDS = 7 * 24 * 60 * 60


def _post_json(url: str, payload: Any) -> dict:
    if url not in {EXPO_PUSH_URL, EXPO_RECEIPTS_URL}:
        raise ValueError("Expo push service URL is not trusted")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": "HeyTim/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # nosec B310
        value = json.loads(response.read(500_001).decode("utf-8"))
    if not isinstance(value, dict):
        raise TypeError("Expo push service returned an invalid response")
    return value


def _remove_push_token(user_id: str, token_id: str) -> None:
    token_key = _push_token_key(user_id, token_id)
    token = table.get_item(Key=token_key, ConsistentRead=True).get("Item", {})
    owner_key = _push_owner_key(token_id)
    owner = (
        table.get_item(Key=owner_key, ConsistentRead=True).get("Item", {}).get("userId")
    )
    with table.batch_writer() as batch:
        batch.delete_item(Key=token_key)
        if owner == user_id:
            batch.delete_item(Key=owner_key)
    endpoint_arn = token.get("endpointArn")
    if isinstance(endpoint_arn, str) and endpoint_arn:
        try:
            sns.delete_endpoint(EndpointArn=endpoint_arn)
        except (BotoCoreError, ClientError):
            logger.warning("Could not delete an invalid native push endpoint")


def _push_tokens(user_id: str) -> list[dict]:
    now = int(datetime.now(UTC).timestamp())
    request = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {
            ":pk": f"USER#{user_id}",
            ":prefix": "PUSH#",
        },
    }
    items = []
    while True:
        response = table.query(**request)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        request["ExclusiveStartKey"] = last_key
    tokens = []
    for item in items:
        token_id = item.get("tokenId")
        provider = item.get("provider")
        if provider is None and isinstance(item.get("expoPushToken"), str):
            provider = "expo"
        token = item.get("pushToken") or item.get("expoPushToken")
        if (
            not isinstance(token_id, str)
            or not isinstance(token, str)
            or provider not in {"expo", "apns"}
            or int(item.get("expiresAt", 0)) <= now
        ):
            continue
        owner = (
            table.get_item(Key=_push_owner_key(token_id), ConsistentRead=True)
            .get("Item", {})
            .get("userId")
        )
        if owner == user_id:
            registration = {"tokenId": token_id, "token": token, "provider": provider}
            if provider == "apns":
                endpoint_arn = item.get("endpointArn")
                environment = item.get("environment")
                if not isinstance(endpoint_arn, str) or environment not in {
                    "sandbox",
                    "production",
                }:
                    continue
                registration.update(endpointArn=endpoint_arn, environment=environment)
            tokens.append(registration)
    return tokens


def _notification_copy(answer: str) -> str:
    clean = " ".join(answer.split())
    return clean if len(clean) <= 180 else f"{clean[:177]}..."


def _notification_key(request: dict) -> dict[str, str]:
    notification_id = request.get("notificationId")
    if not isinstance(notification_id, str) or not notification_id:
        notification_id = ":".join(
            str(request.get(field, ""))
            for field in ("userId", "groupId", "botId", "messageId", "turnId")
        )
    digest = hashlib.sha256(notification_id.encode("utf-8")).hexdigest()
    return {"pk": f"NOTIFICATION#{digest}", "sk": "DELIVERY"}


def _native_message(title: str, body: str, data: dict) -> dict:
    return {
        "aps": {"alert": {"title": title, "body": body}, "sound": "default"},
        **data,
    }


def _send_native_push(token: dict, title: str, body: str, data: dict) -> str:
    endpoint_arn = token["endpointArn"]
    platform_key = "APNS_SANDBOX" if token["environment"] == "sandbox" else "APNS"
    payload = _native_message(title, body, data)
    response = sns.publish(
        TargetArn=endpoint_arn,
        MessageStructure="json",
        MessageAttributes={
            "AWS.SNS.MOBILE.APNS.PUSH_TYPE": {
                "DataType": "String",
                "StringValue": "alert",
            },
            "AWS.SNS.MOBILE.APNS.PRIORITY": {
                "DataType": "String",
                "StringValue": "10",
            },
        },
        Message=json.dumps(
            {"default": body, platform_key: json.dumps(payload, separators=(",", ":"))},
            separators=(",", ":"),
        ),
    )
    message_id = response.get("MessageId")
    if not isinstance(message_id, str) or not message_id:
        raise TypeError("SNS did not return a native push message ID")
    return message_id


def _sns_error_code(value: Exception) -> str | None:
    response = getattr(value, "response", None)
    error = response.get("Error") if isinstance(response, dict) else None
    code = error.get("Code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def _claim_notification(request: dict) -> dict | None:
    key = _notification_key(request)
    now = int(datetime.now(UTC).timestamp())
    try:
        table.put_item(
            Item={
                **key,
                "entity": "NOTIFICATION_DELIVERY",
                "status": "CLAIMED",
                "userId": request["userId"],
                "claimedAt": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "expiresAt": now + NOTIFICATION_DEDUP_SECONDS,
            },
            ConditionExpression=Attr("pk").not_exists(),
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None
    return key


def _finish_notification(key: dict, status: str) -> None:
    table.update_item(
        Key=key,
        UpdateExpression="SET #status = :status, completedAt = :completed",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": status,
            ":completed": datetime.now(UTC).isoformat(timespec="milliseconds"),
        },
    )


def _send_push_notification(request: dict) -> None:
    delivery_key = _claim_notification(request)
    if delivery_key is None:
        _queue_receipt_check(_notification_key(request), request["userId"])
        return
    user_id = request["userId"]
    tokens = _push_tokens(user_id)
    if not tokens:
        _finish_notification(delivery_key, "NO_DEVICES")
        return
    notification_data = {
        "botId": request["botId"],
        "messageId": request.get("messageId") or request.get("turnId", ""),
    }
    if isinstance(request.get("scheduleId"), str):
        notification_data["scheduleId"] = request["scheduleId"]
    if isinstance(request.get("groupId"), str):
        notification_data["groupId"] = request["groupId"]
    task_name = request.get("scheduleName")
    title = (
        f"{request['botName']} finished {task_name}"
        if isinstance(task_name, str) and task_name
        else f"{request['botName']} replied"
    )
    expo_tokens = [item for item in tokens if item.get("provider", "expo") == "expo"]
    native_tokens = [item for item in tokens if item.get("provider") == "apns"]
    messages = [
        {
            "to": item["token"],
            "sound": "default",
            "title": title,
            "body": _notification_copy(request["answer"]),
            "data": notification_data,
            "channelId": "agent-replies",
        }
        for item in expo_tokens
    ]
    tickets = []
    expo_error: Exception | None = None
    if messages:
        try:
            response = _post_json(EXPO_PUSH_URL, messages)
        except Exception as error:
            # The remote service may have accepted the request even when the client
            # did not receive a response. Keep the claim to prevent duplicate pushes,
            # but still give independent native providers their delivery attempt.
            expo_error = error
            logger.warning("Expo push outcome is unknown", exc_info=True)
        else:
            tickets = response.get("data", [])
            if isinstance(tickets, dict):
                tickets = [tickets]
            if not isinstance(tickets, list):
                expo_error = TypeError("Expo push service returned invalid tickets")
                tickets = []
                logger.warning("Expo push service returned invalid tickets")

    receipts = []
    rejected = 0
    for item, ticket in zip(expo_tokens, tickets, strict=False):
        if not isinstance(ticket, dict):
            continue
        if ticket.get("status") == "ok" and isinstance(ticket.get("id"), str):
            receipts.append({"id": ticket["id"], "tokenId": item["tokenId"]})
            continue
        if ticket.get("status") != "error":
            continue
        rejected += 1
        details = ticket.get("details")
        error = details.get("error") if isinstance(details, dict) else None
        if error == "DeviceNotRegistered":
            _remove_push_token(user_id, item["tokenId"])
        else:
            logger.warning(
                "Expo rejected a push ticket: %s",
                error or ticket.get("message", "unknown error"),
            )

    unknown = max(0, len(expo_tokens) - len(receipts) - rejected)
    if len(tickets) != len(expo_tokens):
        unknown = max(1, unknown)
    receipt_states = {
        receipt_key(item["id"]): {**item, "status": "PENDING"} for item in receipts
    }
    accepted = len(receipts)
    for item in native_tokens:
        try:
            message_id = _send_native_push(
                item,
                title,
                _notification_copy(request["answer"]),
                notification_data,
            )
            accepted += 1
            receipt_states[f"native-{receipt_key(message_id)}"] = {
                "id": message_id,
                "tokenId": item["tokenId"],
                "status": "PROVIDER_ACCEPTED",
            }
        except Exception as exc:
            if _sns_error_code(exc) in {"EndpointDisabled", "NotFound"}:
                rejected += 1
                _remove_push_token(user_id, item["tokenId"])
            else:
                unknown += 1
                logger.warning("Native push outcome is unknown", exc_info=True)
    # Keep enough state to distinguish provider acceptance from device receipt.
    table.update_item(
        Key=delivery_key,
        UpdateExpression=(
            "SET receiptStates = :states, rejectedTickets = :rejected, "
            "unknownTickets = :unknown, receiptStatus = :status"
        ),
        ExpressionAttributeValues={
            ":states": receipt_states,
            ":rejected": rejected,
            ":unknown": unknown,
            ":status": "PENDING_RECEIPTS"
            if receipts
            else receipt_status(receipt_states, rejected, unknown),
        },
    )
    status = ticket_status(len(tokens), accepted, rejected)
    _finish_notification(
        delivery_key,
        status if accepted + rejected == len(tokens) and unknown == 0 else "UNKNOWN",
    )
    _queue_receipt_check(delivery_key, user_id)
    if expo_error is not None:
        # Preserve the worker's established retry/failure signal. The durable claim
        # makes that retry recovery-only, so successfully submitted pushes are not
        # duplicated.
        raise expo_error


def _queue_receipt_check(key: dict, user_id: str) -> None:
    """Recover a failed queue handoff without submitting the push again."""
    stored = table.get_item(Key=key, ConsistentRead=True).get("Item", {})
    if stored.get("userId") != user_id or stored.get("receiptCheckQueued"):
        return
    receipts = [
        {"id": item["id"], "tokenId": item["tokenId"]}
        for item in stored.get("receiptStates", {}).values()
        if item.get("status") == "PENDING"
    ]
    if not receipts:
        return
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        DelaySeconds=900,
        MessageBody=json.dumps(
            {
                "type": "PUSH_RECEIPTS",
                "userId": user_id,
                "receipts": receipts,
                "deliveryKey": key,
            }
        ),
    )
    table.update_item(
        Key=key,
        UpdateExpression="SET receiptCheckQueued = :queued",
        ExpressionAttributeValues={":queued": True},
    )


def _record_receipts(request: dict, receipts: dict, exhausted: bool) -> None:
    key = request.get("deliveryKey")
    if not isinstance(key, dict) or key.get("sk") != "DELIVERY":
        return  # Compatibility with receipt jobs queued before delivery tracking.
    stored = table.get_item(Key=key, ConsistentRead=True).get("Item", {})
    if stored.get("userId") != request.get("userId"):
        return
    for item in request.get("receipts", []):
        digest = receipt_key(item["id"])
        previous = stored.get("receiptStates", {}).get(digest)
        if not previous or previous.get("status") != "PENDING":
            continue
        receipt = receipts.get(item["id"])
        outcome = receipt.get("status") if isinstance(receipt, dict) else None
        status = {"ok": "PROVIDER_ACCEPTED", "error": "FAILED"}.get(outcome)
        if status is None and not exhausted:
            continue
        try:
            table.update_item(
                Key=key,
                UpdateExpression="SET receiptStates.#receipt.#status = :status",
                ConditionExpression=Attr(f"receiptStates.{digest}.status").eq(
                    "PENDING"
                ),
                ExpressionAttributeNames={"#receipt": digest, "#status": "status"},
                ExpressionAttributeValues={":status": status or "UNKNOWN"},
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            continue  # Another delivery attempt already recorded this receipt.
    current = table.get_item(Key=key, ConsistentRead=True).get("Item", {})
    states = current.get("receiptStates", {})
    try:
        table.update_item(
            Key=key,
            UpdateExpression="SET receiptStatus = :status",
            ConditionExpression=Attr("receiptStates").eq(states),
            ExpressionAttributeValues={
                ":status": receipt_status(
                    states,
                    int(current.get("rejectedTickets", 0)),
                    int(current.get("unknownTickets", 0)),
                )
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return  # The concurrent poll will aggregate its newer state.


def _check_push_receipts(request: dict) -> None:
    receipt_items = request.get("receipts", [])
    receipt_ids = [
        item.get("id")
        for item in receipt_items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    if not receipt_ids:
        return
    response = _post_json(EXPO_RECEIPTS_URL, {"ids": receipt_ids})
    receipts = response.get("data", {})
    if not isinstance(receipts, dict):
        raise TypeError("Expo push service returned invalid receipts")
    tokens_by_receipt = {
        item["id"]: item.get("tokenId")
        for item in receipt_items
        if isinstance(item, dict) and "id" in item
    }
    for receipt_id, receipt in receipts.items():
        if not isinstance(receipt, dict) or receipt.get("status") != "error":
            continue
        details = receipt.get("details")
        error = details.get("error") if isinstance(details, dict) else None
        token_id = tokens_by_receipt.get(receipt_id)
        if error == "DeviceNotRegistered" and isinstance(token_id, str):
            _remove_push_token(request["userId"], token_id)
        else:
            logger.warning(
                "Expo reported a push receipt error: %s",
                error or receipt.get("message", "unknown error"),
            )

    missing = [
        item
        for item in receipt_items
        if isinstance(item, dict)
        and (
            not isinstance(receipts.get(item.get("id")), dict)
            or receipts[item["id"]].get("status") not in {"ok", "error"}
        )
    ]
    attempt = int(request.get("attempt", 1))
    _record_receipts(request, receipts, exhausted=attempt >= 3)
    if missing and attempt < 3:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            DelaySeconds=300,
            MessageBody=json.dumps(
                {
                    "type": "PUSH_RECEIPTS",
                    "userId": request["userId"],
                    "receipts": missing,
                    "deliveryKey": request.get("deliveryKey"),
                    "attempt": attempt + 1,
                }
            ),
        )
    elif missing:
        logger.warning(
            "Expo did not return %s push receipts after three checks", len(missing)
        )


def _queue_reply_notification(
    user_id: str, bot_id: str, turn_key: dict, turn: dict, bot: dict, answer: str
) -> None:
    payload = {
        "type": "PUSH_NOTIFICATION",
        "userId": user_id,
        "botId": bot_id,
        "botName": bot["name"],
        "messageId": turn["id"],
        "answer": answer,
        "notificationId": f"direct:{user_id}:{bot_id}:{turn['id']}",
    }
    if turn.get("source") == "schedule":
        payload.update(
            {
                "scheduleId": turn.get("scheduleId"),
                "scheduleName": turn.get("scheduleName"),
            }
        )
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(payload),
    )
    _queue_email_delivery(user_id, bot_id, turn, bot, event="reply")
    table.update_item(
        Key=turn_key,
        UpdateExpression="SET notificationQueued = :queued",
        ExpressionAttributeValues={":queued": True},
    )


def _queue_email_delivery(
    user_id: str,
    bot_id: str,
    turn: dict,
    bot: dict,
    *,
    event: str,
) -> None:
    mode = bot.get("emailDeliveryMode", "appOnly")
    schedule_email = (
        turn.get("source") == "schedule"
        and turn.get("scheduleDeliveryMode") == "email"
    )
    if (
        not EMAIL_QUEUE_URL
        or (
            not schedule_email
            and (
                mode == "appOnly"
                or (mode == "emailReplies" and turn.get("source") != "email")
            )
        )
        or not isinstance(bot.get("emailToken"), str)
        or not isinstance(bot.get("emailOwnerAddress"), str)
    ):
        return
    sqs.send_message(
        QueueUrl=EMAIL_QUEUE_URL,
        MessageBody=json.dumps(
            {
                "userId": user_id,
                "botId": bot_id,
                "turnId": turn["id"],
                "turnKey": turn["sk"],
                "event": event,
            }
        ),
    )


def _update_schedule_result(turn: dict, status: str, completed_at: str) -> None:
    schedule_id = turn.get("scheduleId")
    user_id = turn.get("userId")
    if (
        turn.get("source") != "schedule"
        or not isinstance(schedule_id, str)
        or not isinstance(user_id, str)
    ):
        return
    try:
        table.update_item(
            Key=_schedule_key(user_id, schedule_id),
            UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
            ConditionExpression=Attr("pk").exists(),
            ExpressionAttributeValues={":now": completed_at, ":status": status},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return
