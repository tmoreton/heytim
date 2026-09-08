from __future__ import annotations

import json
import uuid

from shared.group_chat import (
    ALL_BOTS_REPLY_TARGET,
    plan_group_reply_round,
    select_group_reply_targets,
)

from .attachments import _public_file, _resolve_group_attachments
from .bots import _get_bot
from .groups import _require_group_member
from .support import (
    QUEUE_URL,
    ApiError,
    _bot_color,
    _group_message_sk,
    _group_pk,
    _now,
    _validate_string,
    catalog,
    sqs,
    table,
)


def _list_group_messages(user_id: str, group_id: str, limit: int = 100) -> list[dict]:
    _, group_items = _require_group_member(user_id, group_id)
    group_bots = {
        item["botId"]: item
        for item in group_items
        if item.get("entity") == "GROUP_BOT" and isinstance(item.get("botId"), str)
    }
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _group_pk(group_id), ":prefix": "MESSAGE#"},
        ScanIndexForward=False,
        Limit=limit,
        ConsistentRead=True,
    ).get("Items", [])
    messages = []
    for item in reversed(items):
        messages.append(
            {
                key: value
                for key, value in {
                    "id": item.get("id"),
                    "role": "assistant" if item.get("authorType") == "bot" else "user",
                    "authorType": item.get("authorType"),
                    "authorId": item.get("authorId"),
                    "authorName": item.get("authorName"),
                    "authorColor": _bot_color(
                        group_bots.get(item.get("authorId"), item)
                    )
                    if item.get("authorType") == "bot"
                    else None,
                    "isMine": item.get("authorType") == "user"
                    and item.get("authorId") == user_id,
                    "text": item.get("text", ""),
                    "createdAt": item.get("createdAt"),
                    "status": str(item.get("status", "COMPLETE")).lower(),
                    "activity": item.get("activity", []),
                    "roundId": item.get("roundId"),
                    "roundPosition": item.get("roundPosition"),
                    "roundSize": item.get("roundSize"),
                    "roundRole": item.get("roundRole"),
                    "attachments": [
                        _public_file(file)
                        for source in ("attachments", "artifacts")
                        for file in item.get(source, [])
                        if isinstance(file, dict)
                    ],
                }.items()
                if value is not None
            }
        )
    return messages


def _send_group_message(
    user_id: str, display_name: str, group_id: str, value: dict
) -> dict:
    meta, items = _require_group_member(user_id, group_id)
    reply_bot_id = value.get("replyBotId")
    if reply_bot_id is not None and (
        not isinstance(reply_bot_id, str) or not reply_bot_id
    ):
        raise ApiError(400, "replyBotId must identify a bot in this group")
    selected_reply_bots = select_group_reply_targets(items, reply_bot_id)
    if reply_bot_id and not selected_reply_bots:
        raise ApiError(400, "Choose a bot that belongs to this group")
    coordinated = reply_bot_id == ALL_BOTS_REPLY_TARGET and len(selected_reply_bots) > 1
    try:
        reply_bots = plan_group_reply_round(selected_reply_bots, coordinated)
    except ValueError as exc:
        raise ApiError(409, "Add Chief before asking the full bot team") from exc
    for group_bot in reply_bots:
        source_bot = _get_bot(group_bot["botOwnerId"], group_bot["botId"])
        if catalog.approval_tool_names(
            group_bot["botOwnerId"], source_bot.get("toolIds", [])
        ):
            raise ApiError(
                409,
                "Interactive tools currently require approval in a direct chat.",
            )
    attachments = _resolve_group_attachments(
        user_id, group_id, value.get("attachmentIds")
    )
    raw_text = value.get("text", "")
    if attachments and isinstance(raw_text, str) and not raw_text.strip():
        raw_text = "Please review the attached files."
    text = _validate_string(raw_text, "text", 8_000)
    coordinator_bot_id = reply_bots[0]["botId"] if reply_bots else None

    current = _now()
    message_id = str(uuid.uuid4())
    message = {
        "pk": _group_pk(group_id),
        "sk": _group_message_sk(current, message_id),
        "entity": "GROUP_MESSAGE",
        "id": message_id,
        "authorType": "user",
        "authorId": user_id,
        "authorName": display_name,
        "text": text,
        "createdAt": current,
        "status": "COMPLETE",
    }
    if attachments:
        message["attachments"] = attachments
        message["uploadedBy"] = user_id
    replies = []
    for order, group_bot in enumerate(reply_bots, start=1):
        reply_id = str(uuid.uuid4())
        replies.append(
            {
                "pk": _group_pk(group_id),
                "sk": _group_message_sk(current, reply_id, order),
                "entity": "GROUP_MESSAGE",
                "id": reply_id,
                "authorType": "bot",
                "authorId": group_bot["botId"],
                "authorName": group_bot["name"],
                "authorColor": _bot_color(group_bot),
                "botOwnerId": group_bot["botOwnerId"],
                "roundId": message_id,
                "roundPosition": order,
                "roundSize": len(reply_bots),
                "roundRole": group_bot["roundRole"],
                "coordinatorBotId": coordinator_bot_id,
                "text": "",
                "createdAt": current,
                "status": "PENDING" if order == 1 else "WAITING",
            }
        )
    with table.batch_writer() as batch:
        batch.put_item(Item=message)
        for attachment in attachments:
            batch.put_item(Item=attachment)
        for reply in replies:
            batch.put_item(Item=reply)
        batch.put_item(
            Item={
                **meta,
                "lastMessage": text,
                "lastMessageAt": current,
                "updatedAt": current,
            }
        )

    if replies:
        try:
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps(
                    {
                        "type": "GROUP_AGENT_ROUND",
                        "requestedBy": user_id,
                        "groupId": group_id,
                        "messageId": message_id,
                        "userText": text,
                        "replyTarget": ALL_BOTS_REPLY_TARGET
                        if reply_bot_id == ALL_BOTS_REPLY_TARGET
                        else "bot",
                        "replies": [
                            {
                                "botId": reply["authorId"],
                                "botOwnerId": reply["botOwnerId"],
                                "replyKey": reply["sk"],
                                "roundRole": reply["roundRole"],
                                "coordinatorBotId": reply["coordinatorBotId"],
                            }
                            for reply in replies
                        ],
                    }
                ),
            )
        except Exception:
            with table.batch_writer() as batch:
                for reply in replies:
                    batch.put_item(
                        Item={
                            **reply,
                            "status": "ERROR",
                            "text": "I could not start that request. Please try again.",
                        }
                    )
            raise
    return {
        "messageId": message_id,
        "replyId": replies[0]["id"] if replies else None,
        "replyIds": [reply["id"] for reply in replies],
    }
