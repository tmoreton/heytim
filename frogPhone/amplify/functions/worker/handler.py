from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
AGENT_RUNTIME_QUALIFIER = os.environ.get("AGENT_RUNTIME_QUALIFIER", "DEFAULT")

table = boto3.resource("dynamodb").Table(TABLE_NAME)
agentcore = boto3.client(
    "bedrock-agentcore",
    config=Config(
        retries={"total_max_attempts": 5, "mode": "adaptive"},
        connect_timeout=5,
        read_timeout=260,
    ),
)


def _bot_key(user_id: str, bot_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"BOT#{bot_id}"}


def _turn_pk(user_id: str, bot_id: str) -> str:
    return f"CHAT#{user_id}#{bot_id}"


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


def _event_text(value: Any) -> str:
    if isinstance(value, dict):
        event = value.get("event", value)
        delta = event.get("contentBlockDelta", {}).get("delta", {}) if isinstance(event, dict) else {}
        if isinstance(delta, dict) and isinstance(delta.get("text"), str):
            return delta["text"]
        if isinstance(value.get("data"), str):
            try:
                return _event_text(json.loads(value["data"]))
            except json.JSONDecodeError:
                return ""
    return ""


def _read_agent_text(response: dict) -> str:
    body = response["response"]
    chunks: list[str] = []
    for raw_line in body.iter_lines():
        if not raw_line:
            continue
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
        if line.startswith("data:"):
            line = line[5:].strip()
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = _event_text(event)
        if text:
            chunks.append(text)
    result = "".join(chunks).strip()
    if not result:
        raise ValueError("AgentCore returned no assistant text")
    return result


def _invoke(user_id: str, bot_id: str, bot: dict) -> str:
    session_id = hashlib.sha256(f"{user_id}:{bot_id}".encode()).hexdigest()
    payload = {
        "messages": _get_history(user_id, bot_id),
        "bot": {
            "name": bot["name"],
            "prompt": bot["prompt"],
            "toolIds": bot.get("toolIds", []),
            "skillIds": bot.get("skillIds", []),
        },
    }
    response = agentcore.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        qualifier=AGENT_RUNTIME_QUALIFIER,
        runtimeSessionId=session_id,
        contentType="application/json",
        accept="text/event-stream",
        payload=json.dumps(payload).encode("utf-8"),
    )
    return _read_agent_text(response)


def _process(record: dict) -> None:
    request = json.loads(record["body"])
    user_id = request["userId"]
    bot_id = request["botId"]
    turn_key = {"pk": _turn_pk(user_id, bot_id), "sk": request["turnKey"]}
    turn = table.get_item(Key=turn_key, ConsistentRead=True).get("Item")
    if not turn or turn.get("status") != "PENDING":
        return
    bot = table.get_item(Key=_bot_key(user_id, bot_id), ConsistentRead=True).get("Item")
    if not bot:
        raise ValueError("Bot no longer exists")

    try:
        answer = _invoke(user_id, bot_id, bot)
    except Exception:
        logger.exception("Agent request failed for turn %s", turn.get("id"))
        receive_count = int(record.get("attributes", {}).get("ApproximateReceiveCount", "1"))
        if receive_count < 3:
            raise
        failed_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        table.update_item(
            Key=turn_key,
            UpdateExpression="SET #status = :error, assistantText = :answer, completedAt = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":error": "ERROR",
                ":answer": "I could not finish that request. Please try again.",
                ":now": failed_at,
            },
        )
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


def handler(event: dict, _context: Any) -> dict:
    failures = []
    for record in event.get("Records", []):
        try:
            _process(record)
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
