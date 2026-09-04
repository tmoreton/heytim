from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.request
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config

from shared.agent_stream import ProgressCallback, read_agent_stream
from shared.catalog import CatalogService
from shared.group_chat import group_history_from_items, group_round_step, group_runtime_context

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
AGENT_RUNTIME_QUALIFIER = os.environ.get("AGENT_RUNTIME_QUALIFIER", "DEFAULT")
QUEUE_URL = os.environ["QUEUE_URL"]

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"

table = boto3.resource("dynamodb").Table(TABLE_NAME)
catalog = CatalogService(table)
agentcore = boto3.client(
    "bedrock-agentcore",
    config=Config(
        retries={"total_max_attempts": 5, "mode": "adaptive"},
        connect_timeout=5,
        read_timeout=260,
    ),
)
sqs = boto3.client(
    "sqs",
    config=Config(
        retries={"total_max_attempts": 5, "mode": "adaptive"},
        connect_timeout=3,
        read_timeout=10,
    ),
)


def _bot_key(user_id: str, bot_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"BOT#{bot_id}"}


def _turn_pk(user_id: str, bot_id: str) -> str:
    return f"CHAT#{user_id}#{bot_id}"


def _group_pk(group_id: str) -> str:
    return f"GROUP#{group_id}"


def _push_token_key(user_id: str, token_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"PUSH#{token_id}"}


def _push_owner_key(token_id: str) -> dict:
    return {"pk": f"PUSH_TOKEN#{token_id}", "sk": "OWNER"}


def _get_history(user_id: str, bot_id: str) -> list[dict]:
    turns = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _turn_pk(user_id, bot_id), ":prefix": "TURN#"},
        ScanIndexForward=False,
        Limit=20,
    ).get("Items", [])
    messages = []
    for turn in reversed(turns):
        if turn.get("userText"):
            messages.append({"role": "user", "content": [{"text": turn["userText"]}]})
        if turn.get("assistantText") and turn.get("status") == "COMPLETE":
            messages.append({"role": "assistant", "content": [{"text": turn["assistantText"]}]})
    return messages


def _get_group_history(group_id: str, bot_id: str) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _group_pk(group_id), ":prefix": "MESSAGE#"},
        ScanIndexForward=False,
        Limit=40,
        ConsistentRead=True,
    ).get("Items", [])
    return group_history_from_items(items, bot_id)


def _get_group_context(group_id: str, bot_id: str, round_position: int, round_size: int) -> dict:
    meta = table.get_item(Key={"pk": _group_pk(group_id), "sk": "META"}, ConsistentRead=True).get("Item")
    if not meta:
        raise ValueError("Group no longer exists")
    items = [meta]
    for prefix in ("BOT#", "USER#"):
        items.extend(
            table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={":pk": _group_pk(group_id), ":prefix": prefix},
                ConsistentRead=True,
            ).get("Items", [])
        )
    return group_runtime_context(meta, items, bot_id, round_position, round_size)


def _invoke(
    user_id: str,
    bot_id: str,
    bot: dict,
    *,
    history: list[dict] | None = None,
    session_scope: str | None = None,
    group_context: dict | None = None,
    on_progress: ProgressCallback | None = None,
) -> str:
    session_id = hashlib.sha256((session_scope or f"{user_id}:{bot_id}").encode()).hexdigest()
    skill_versions = bot.get("skillVersions")
    if not isinstance(skill_versions, dict):
        catalog.sync_official()
        skill_versions = catalog.validate_and_pin(user_id, bot.get("skillIds", []))
        table.update_item(
            Key=_bot_key(user_id, bot_id),
            UpdateExpression="SET skillVersions = :versions",
            ExpressionAttributeValues={":versions": skill_versions},
        )
    resolved_skills = catalog.resolve_for_runtime(skill_versions)
    tool_ids = list(dict.fromkeys(bot.get("toolIds", [])))
    for skill in resolved_skills:
        tool_ids.extend(tool_id for tool_id in skill.get("requiredToolIds", []) if tool_id not in tool_ids)
    resolved_tools = catalog.resolve_tools_for_runtime(tool_ids)
    payload = {
        "messages": history if history is not None else _get_history(user_id, bot_id),
        "bot": {
            "name": bot["name"],
            "prompt": bot["prompt"],
            "toolIds": tool_ids,
            "tools": resolved_tools,
            "skillIds": bot.get("skillIds", []),
            "skills": resolved_skills,
        },
    }
    if group_context is not None:
        payload["group"] = group_context
    response = agentcore.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        qualifier=AGENT_RUNTIME_QUALIFIER,
        runtimeSessionId=session_id,
        contentType="application/json",
        accept="text/event-stream",
        payload=json.dumps(payload).encode("utf-8"),
    )
    return read_agent_stream(response["response"].iter_lines(), on_progress)


def _progress_updater(item_key: dict) -> ProgressCallback:
    def update(progress: list[str]) -> None:
        try:
            table.update_item(
                Key=item_key,
                UpdateExpression="SET activity = :activity",
                ConditionExpression="#status = :pending",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":activity": progress, ":pending": "PENDING"},
            )
        except Exception:
            logger.exception("Could not publish agent activity for %s", item_key.get("sk", "unknown"))

    return update


def _post_json(url: str, payload: Any) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": "FrogBot/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expo push service returned an invalid response")
    return value


def _remove_push_token(user_id: str, token_id: str) -> None:
    owner_key = _push_owner_key(token_id)
    owner = table.get_item(Key=owner_key, ConsistentRead=True).get("Item", {}).get("userId")
    with table.batch_writer() as batch:
        batch.delete_item(Key=_push_token_key(user_id, token_id))
        if owner == user_id:
            batch.delete_item(Key=owner_key)


def _push_tokens(user_id: str) -> list[dict]:
    now = int(datetime.now(UTC).timestamp())
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": f"USER#{user_id}", ":prefix": "PUSH#"},
        Limit=100,
    ).get("Items", [])
    tokens = []
    for item in items:
        token_id = item.get("tokenId")
        token = item.get("expoPushToken")
        if not isinstance(token_id, str) or not isinstance(token, str) or int(item.get("expiresAt", 0)) <= now:
            continue
        owner = table.get_item(Key=_push_owner_key(token_id), ConsistentRead=True).get("Item", {}).get("userId")
        if owner == user_id:
            tokens.append({"tokenId": token_id, "token": token})
    return tokens


def _notification_copy(answer: str) -> str:
    clean = " ".join(answer.split())
    return clean if len(clean) <= 180 else f"{clean[:177]}..."


def _send_push_notification(request: dict) -> None:
    user_id = request["userId"]
    tokens = _push_tokens(user_id)
    if not tokens:
        return
    notification_data = {
        "botId": request["botId"],
        "messageId": request.get("messageId") or request.get("turnId", ""),
    }
    if isinstance(request.get("groupId"), str):
        notification_data["groupId"] = request["groupId"]
    messages = [
        {
            "to": item["token"],
            "sound": "default",
            "title": f"{request['botName']} replied",
            "body": _notification_copy(request["answer"]),
            "data": notification_data,
            "channelId": "agent-replies",
        }
        for item in tokens
    ]
    response = _post_json(EXPO_PUSH_URL, messages)
    tickets = response.get("data", [])
    if isinstance(tickets, dict):
        tickets = [tickets]
    if not isinstance(tickets, list):
        raise ValueError("Expo push service returned invalid tickets")

    receipts = []
    for item, ticket in zip(tokens, tickets, strict=False):
        if not isinstance(ticket, dict):
            continue
        if ticket.get("status") == "ok" and isinstance(ticket.get("id"), str):
            receipts.append({"id": ticket["id"], "tokenId": item["tokenId"]})
            continue
        error = ticket.get("details", {}).get("error")
        if error == "DeviceNotRegistered":
            _remove_push_token(user_id, item["tokenId"])
        else:
            logger.warning("Expo rejected a push ticket: %s", error or ticket.get("message", "unknown error"))

    if receipts:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            DelaySeconds=900,
            MessageBody=json.dumps({"type": "PUSH_RECEIPTS", "userId": user_id, "receipts": receipts}),
        )


def _check_push_receipts(request: dict) -> None:
    receipt_items = request.get("receipts", [])
    receipt_ids = [item.get("id") for item in receipt_items if isinstance(item, dict) and isinstance(item.get("id"), str)]
    if not receipt_ids:
        return
    response = _post_json(EXPO_RECEIPTS_URL, {"ids": receipt_ids})
    receipts = response.get("data", {})
    if not isinstance(receipts, dict):
        raise ValueError("Expo push service returned invalid receipts")
    tokens_by_receipt = {item["id"]: item.get("tokenId") for item in receipt_items if isinstance(item, dict) and "id" in item}
    for receipt_id, receipt in receipts.items():
        if not isinstance(receipt, dict) or receipt.get("status") != "error":
            continue
        error = receipt.get("details", {}).get("error")
        token_id = tokens_by_receipt.get(receipt_id)
        if error == "DeviceNotRegistered" and isinstance(token_id, str):
            _remove_push_token(request["userId"], token_id)
        else:
            logger.warning("Expo reported a push receipt error: %s", error or receipt.get("message", "unknown error"))

    missing = [item for item in receipt_items if isinstance(item, dict) and item.get("id") not in receipts]
    attempt = int(request.get("attempt", 1))
    if missing and attempt < 3:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            DelaySeconds=300,
            MessageBody=json.dumps(
                {"type": "PUSH_RECEIPTS", "userId": request["userId"], "receipts": missing, "attempt": attempt + 1}
            ),
        )
    elif missing:
        logger.warning("Expo did not return %s push receipts after three checks", len(missing))


def _queue_reply_notification(user_id: str, bot_id: str, turn_key: dict, turn: dict, bot: dict, answer: str) -> None:
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(
            {
                "type": "PUSH_NOTIFICATION",
                "userId": user_id,
                "botId": bot_id,
                "botName": bot["name"],
                "messageId": turn["id"],
                "answer": answer,
            }
        ),
    )
    table.update_item(
        Key=turn_key,
        UpdateExpression="SET notificationQueued = :queued",
        ExpressionAttributeValues={":queued": True},
    )


def _process_agent_reply(record: dict, request: dict) -> None:
    user_id = request["userId"]
    bot_id = request["botId"]
    turn_key = {"pk": _turn_pk(user_id, bot_id), "sk": request["turnKey"]}
    turn = table.get_item(Key=turn_key, ConsistentRead=True).get("Item")
    if not turn:
        return
    bot = table.get_item(Key=_bot_key(user_id, bot_id), ConsistentRead=True).get("Item")
    if not bot:
        raise ValueError("Bot no longer exists")
    if turn.get("status") in {"COMPLETE", "ERROR"} and not turn.get("notificationQueued") and turn.get("assistantText"):
        _queue_reply_notification(user_id, bot_id, turn_key, turn, bot, turn["assistantText"])
        return
    if turn.get("status") != "PENDING":
        return

    try:
        answer = _invoke(user_id, bot_id, bot, on_progress=_progress_updater(turn_key))
    except Exception:
        logger.exception("Agent request failed for turn %s", turn.get("id"))
        receive_count = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
        if receive_count < 3:
            raise
        failed_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        failure_answer = "I could not finish that request. Please try again."
        table.update_item(
            Key=turn_key,
            UpdateExpression="SET #status = :error, assistantText = :answer, completedAt = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":error": "ERROR",
                ":answer": failure_answer,
                ":now": failed_at,
            },
        )
        _queue_reply_notification(user_id, bot_id, turn_key, turn, bot, failure_answer)
        return

    completed_at = datetime.now(UTC).isoformat(timespec="milliseconds")
    table.update_item(
        Key=turn_key,
        UpdateExpression="SET #status = :complete, assistantText = :answer, completedAt = :now",
        ConditionExpression="#status = :pending",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":complete": "COMPLETE",
            ":pending": "PENDING",
            ":answer": answer,
            ":now": completed_at,
        },
    )
    try:
        table.update_item(
            Key=_bot_key(user_id, bot_id),
            UpdateExpression="SET lastMessage = :answer, lastMessageAt = :now, updatedAt = :now",
            ExpressionAttributeValues={":answer": answer[:280], ":now": completed_at},
        )
    except Exception:
        logger.exception("Could not update the bot preview for turn %s", turn.get("id"))
    _queue_reply_notification(user_id, bot_id, turn_key, turn, bot, answer)


def _queue_group_reply_notifications(group_id: str, reply_key: dict, reply: dict, bot: dict, answer: str) -> None:
    members = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _group_pk(group_id), ":prefix": "USER#"},
        Limit=100,
    ).get("Items", [])
    for member in members:
        user_id = member.get("userId")
        if not isinstance(user_id, str):
            continue
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(
                {
                    "type": "PUSH_NOTIFICATION",
                    "userId": user_id,
                    "groupId": group_id,
                    "botId": bot["id"],
                    "botName": bot["name"],
                    "messageId": reply["id"],
                    "answer": answer,
                }
            ),
        )
    table.update_item(
        Key=reply_key,
        UpdateExpression="SET notificationQueued = :queued",
        ExpressionAttributeValues={":queued": True},
    )


def _process_group_agent_reply(record: dict, request: dict, *, notify: bool = True) -> str | None:
    group_id = request["groupId"]
    bot_id = request["botId"]
    reply_key = {"pk": _group_pk(group_id), "sk": request["replyKey"]}
    reply = table.get_item(Key=reply_key, ConsistentRead=True).get("Item")
    if not reply:
        return
    bot_owner_id = reply.get("botOwnerId") or request["botOwnerId"]
    bot = table.get_item(Key=_bot_key(bot_owner_id, bot_id), ConsistentRead=True).get("Item")
    if not bot:
        raise ValueError("Source bot no longer exists")
    if reply.get("status") in {"COMPLETE", "ERROR"} and not reply.get("notificationQueued") and reply.get("text"):
        if notify:
            _queue_group_reply_notifications(group_id, reply_key, reply, bot, reply["text"])
        return reply["text"]
    if reply.get("status") != "PENDING":
        return None

    try:
        round_position = int(request.get("roundPosition", reply.get("roundPosition", 1)))
        round_size = int(request.get("roundSize", reply.get("roundSize", 1)))
        answer = _invoke(
            bot_owner_id,
            bot_id,
            bot,
            history=_get_group_history(group_id, bot_id),
            session_scope=f"group:{group_id}:bot:{bot_id}",
            group_context=_get_group_context(group_id, bot_id, round_position, round_size),
            on_progress=_progress_updater(reply_key),
        )
    except Exception:
        logger.exception("Agent request failed for group reply %s", reply.get("id"))
        receive_count = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
        if receive_count < 3:
            raise
        answer = "I could not finish that request. Please try again."
        table.update_item(
            Key=reply_key,
            UpdateExpression="SET #status = :error, #text = :answer, completedAt = :now",
            ExpressionAttributeNames={"#status": "status", "#text": "text"},
            ExpressionAttributeValues={":error": "ERROR", ":answer": answer, ":now": datetime.now(UTC).isoformat(timespec="milliseconds")},
        )
        if notify:
            _queue_group_reply_notifications(group_id, reply_key, reply, bot, answer)
        return answer

    completed_at = datetime.now(UTC).isoformat(timespec="milliseconds")
    table.update_item(
        Key=reply_key,
        UpdateExpression="SET #status = :complete, #text = :answer, completedAt = :now",
        ConditionExpression="#status = :pending",
        ExpressionAttributeNames={"#status": "status", "#text": "text"},
        ExpressionAttributeValues={":complete": "COMPLETE", ":pending": "PENDING", ":answer": answer, ":now": completed_at},
    )
    try:
        table.update_item(
            Key={"pk": _group_pk(group_id), "sk": "META"},
            UpdateExpression="SET lastMessage = :answer, lastMessageAt = :now, updatedAt = :now",
            ExpressionAttributeValues={":answer": answer[:280], ":now": completed_at},
        )
    except Exception:
        logger.exception("Could not update the group preview for reply %s", reply.get("id"))
    if notify:
        _queue_group_reply_notifications(group_id, reply_key, reply, bot, answer)
    return answer


def _process_group_agent_round(record: dict, request: dict) -> None:
    replies = request.get("replies")
    index = request.get("nextReplyIndex", 0)
    reply, final_reply = group_round_step(replies, index)
    _process_group_agent_reply(
        record,
        {
            **request,
            **reply,
            "roundPosition": index + 1,
            "roundSize": len(replies),
        },
        notify=final_reply,
    )
    if not final_reply:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({**request, "nextReplyIndex": index + 1}),
        )


def _process(record: dict) -> None:
    request = json.loads(record["body"])
    request_type = request.get("type", "AGENT_REPLY")
    if request_type == "PUSH_NOTIFICATION":
        _send_push_notification(request)
        return
    if request_type == "PUSH_RECEIPTS":
        _check_push_receipts(request)
        return
    if request_type == "GROUP_AGENT_REPLY":
        _process_group_agent_reply(record, request)
        return
    if request_type == "GROUP_AGENT_ROUND":
        _process_group_agent_round(record, request)
        return
    if request_type != "AGENT_REPLY":
        raise ValueError(f"Unknown job type: {request_type}")
    _process_agent_reply(record, request)


def handler(event: dict, _context: Any) -> dict:
    failures = []
    for record in event.get("Records", []):
        try:
            _process(record)
        except Exception:
            logger.exception("Job failed for message %s", record.get("messageId", "unknown"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
