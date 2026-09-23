from __future__ import annotations

import json
import uuid

from shared.client_contract import MESSAGE_MAX_LENGTH
from shared.group_chat import (
    ALL_BOTS_REPLY_TARGET,
    plan_group_reply_round,
    select_group_reply_targets,
)
from shared.workflows import group_run_record, task_metadata

from .attachments import _public_file, _resolve_group_attachments
from .bots import _get_bot
from .groups import _require_group_member
from .support import (
    QUEUE_URL,
    ApiError,
    _bot_color,
    _decode_page_cursor,
    _encode_page_cursor,
    _group_message_sk,
    _group_pk,
    _now,
    _validate_string,
    catalog,
    sqs,
    table,
)
from .workspaces import _resolve_workspace_files


def _list_group_message_page(
    user_id: str, group_id: str, cursor: object = None, limit: int = 50
) -> tuple[list[dict], str | None]:
    _, group_items = _require_group_member(user_id, group_id)
    group_bots = {
        item["botId"]: item
        for item in group_items
        if item.get("entity") == "GROUP_BOT" and isinstance(item.get("botId"), str)
    }
    partition_key = _group_pk(group_id)
    request = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {":pk": partition_key, ":prefix": "MESSAGE#"},
        "ScanIndexForward": False,
        "Limit": limit,
        "ConsistentRead": True,
    }
    start_key = _decode_page_cursor(cursor, partition_key, "MESSAGE#")
    if start_key:
        request["ExclusiveStartKey"] = start_key
    response = table.query(**request)
    items = response.get("Items", [])
    messages = []
    saved_message_ids = {
        item.get("sourceMessageId")
        for item in group_items
        if item.get("entity") == "GROUP_DECISION"
    }
    for item in reversed(items):
        can_save_decision = (
            item.get("authorType") == "bot"
            and item.get("status") == "COMPLETE"
            and item.get("roundRole") in {None, "solo", "synthesizer"}
            and item.get("id") not in saved_message_ids
        )
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
                    "startedAt": item.get("startedAt"),
                    "completedAt": item.get("completedAt"),
                    "activityUpdatedAt": item.get("activityUpdatedAt"),
                    "status": str(item.get("status", "COMPLETE")).lower(),
                    "allowedActions": (["approveOnce", "approveAlways", "reject"]
                                       if item.get("status") == "AWAITING_APPROVAL"
                                       and item.get("billingUserId") == user_id
                                       and item.get("botOwnerId") == user_id
                                       else ["saveDecision"] if can_save_decision else []),
                    "approvalTools": (item.get("approvalTools") if isinstance(item.get("approvalTools"), list)
                                      else [item["approvalRequest"].get("toolName")]
                                      if isinstance(item.get("approvalRequest"), dict) else None),
                    "approvalInput": (json.dumps(item["approvalRequest"].get("input"),
                                                 sort_keys=True, ensure_ascii=False, indent=2)
                                      if isinstance(item.get("approvalRequest"), dict) else None),
                    "activity": item.get("activity", []),
                    "roundId": item.get("roundId"),
                    "roundPosition": item.get("roundPosition"),
                    "roundSize": item.get("roundSize"),
                    "roundRole": item.get("roundRole"),
                    "runId": item.get("runId"),
                    "taskId": item.get("taskId"),
                    "taskRole": item.get("taskRole"),
                    "source": item.get("source"),
                    "routineId": item.get("routineId"),
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
    return messages, _encode_page_cursor(response.get("LastEvaluatedKey"))


def _list_group_messages(user_id: str, group_id: str, limit: int = 100) -> list[dict]:
    return _list_group_message_page(user_id, group_id, limit=limit)[0]


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
        if group_bot["botOwnerId"] != user_id and catalog.approval_tool_names(
            group_bot["botOwnerId"], source_bot.get("toolIds", [])
        ):
            raise ApiError(
                409,
                "A room can only approve actions for its requester's own bot.",
            )
    raw_text = value.get("text", "")
    if not isinstance(raw_text, str) or raw_text.strip():
        _validate_string(raw_text, "text", MESSAGE_MAX_LENGTH)
    raw_attachment_ids = value.get("attachmentIds") or []
    raw_workspace_ids = value.get("workspaceFileIds") or []
    if (isinstance(raw_attachment_ids, list) and isinstance(raw_workspace_ids, list)
        and len(raw_attachment_ids) + len(raw_workspace_ids) > 5):
        raise ApiError(400, "Attach up to 5 files per message")
    attachments = _resolve_group_attachments(
        user_id, group_id, value.get("attachmentIds")
    )
    uploaded_attachments = attachments
    attachments = attachments + _resolve_workspace_files(
        user_id, "group", group_id, value.get("workspaceFileIds")
    )
    if len(attachments) > 5:
        raise ApiError(400, "Attach up to 5 files per message")
    if attachments and isinstance(raw_text, str) and not raw_text.strip():
        raw_text = "Please review the attached files."
    text = _validate_string(raw_text, "text", MESSAGE_MAX_LENGTH)
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
        "billingUserId": user_id,
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
                "billingUserId": user_id,
                "roundId": message_id,
                "roundPosition": order,
                "roundSize": len(reply_bots),
                "roundRole": group_bot["roundRole"],
                **task_metadata(message_id, reply_id, group_bot["roundRole"]),
                "coordinatorBotId": coordinator_bot_id,
                "text": "",
                "createdAt": current,
                "status": "PENDING" if order == 1 else "WAITING",
            }
        )
    with table.batch_writer() as batch:
        batch.put_item(Item=message)
        for attachment in uploaded_attachments:
            batch.put_item(Item=attachment)
        for reply in replies:
            batch.put_item(Item=reply)
        if replies:
            batch.put_item(Item=group_run_record(
                _group_pk(group_id), message_id, user_id, "chat", current,
                [reply["id"] for reply in replies],
                [reply["sk"] for reply in replies],
            ))
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
