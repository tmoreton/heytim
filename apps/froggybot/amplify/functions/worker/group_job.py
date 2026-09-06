from __future__ import annotations

import json
import logging

from shared.group_chat import group_round_step
from shared.work_state import is_claimable

from .agent import _get_group_context, _get_group_history, _invoke, _progress_updater
from .artifacts import (
    _collect_group_generated_artifacts,
    _delete_group_generated_artifacts,
    _group_generated_artifact_prefix,
)
from .background_work import _queue_background_poll
from .support import (
    QUEUE_URL,
    _account_is_active,
    _bot_key,
    _group_pk,
    catalog,
    sqs,
    table,
)
from .usage import record_invocation_usage
from .work import _claim_work, _finish_work, _pause_work, _release_work

logger = logging.getLogger(__name__)


def _queue_group_reply_notifications(
    group_id: str, reply_key: dict, reply: dict, bot: dict, answer: str
) -> None:
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


def _process_group_agent_reply(
    record: dict, request: dict, *, notify: bool = True
) -> str | None:
    group_id = request["groupId"]
    bot_id = request["botId"]
    reply_key = {"pk": _group_pk(group_id), "sk": request["replyKey"]}
    reply = table.get_item(Key=reply_key, ConsistentRead=True).get("Item")
    if not reply:
        return
    bot_owner_id = reply.get("botOwnerId") or request["botOwnerId"]
    if not _account_is_active(bot_owner_id):
        return
    bot = table.get_item(Key=_bot_key(bot_owner_id, bot_id), ConsistentRead=True).get(
        "Item"
    )
    if not bot:
        raise ValueError("Source bot no longer exists")
    if reply.get("pendingWork"):
        _queue_background_poll(reply_key, request, delay_seconds=0)
        return None
    if (
        reply.get("status") in {"COMPLETE", "ERROR"}
        and not reply.get("notificationQueued")
        and reply.get("text")
    ):
        if notify:
            _queue_group_reply_notifications(
                group_id, reply_key, reply, bot, reply["text"]
            )
        return reply["text"]
    if catalog.approval_tool_names(bot_owner_id, bot.get("toolIds", [])):
        if not is_claimable(reply.get("status")):
            return None
        lease_owner = _claim_work(reply_key, record)
        if not lease_owner:
            return None
        failure_answer = (
            "This group reply was stopped because interactive tools require "
            "approval in a direct chat."
        )
        failed_at = _finish_work(
            reply_key, lease_owner, "ERROR", "text", failure_answer
        )
        if not failed_at:
            return None
        if notify:
            _queue_group_reply_notifications(
                group_id, reply_key, reply, bot, failure_answer
            )
        return failure_answer
    if not is_claimable(reply.get("status")):
        return None

    lease_owner = _claim_work(reply_key, record)
    if not lease_owner:
        return None

    receive_count = int(
        record.get("attributes", {}).get("ApproximateReceiveCount", "1")
    )
    if receive_count > 1:
        _delete_group_generated_artifacts(group_id, reply["id"])
    try:
        round_position = int(
            request.get("roundPosition", reply.get("roundPosition", 1))
        )
        round_size = int(request.get("roundSize", reply.get("roundSize", 1)))
        round_role = str(request.get("roundRole", reply.get("roundRole", "solo")))
        coordinator_bot_id = request.get(
            "coordinatorBotId", reply.get("coordinatorBotId")
        )
        result = _invoke(
            bot_owner_id,
            bot_id,
            bot,
            history=_get_group_history(group_id, bot_id),
            session_scope=f"group:{group_id}:bot:{bot_id}",
            artifact_prefix=_group_generated_artifact_prefix(group_id, reply["id"]),
            group_context=_get_group_context(
                group_id,
                bot_id,
                round_position,
                round_size,
                round_role,
                coordinator_bot_id,
            ),
            continuation=reply.get("backgroundResults"),
            on_progress=_progress_updater(reply_key, lease_owner),
        )
        requested_by = request.get("requestedBy")
        billing_user_id = (
            requested_by
            if isinstance(requested_by, str) and requested_by.strip()
            else bot_owner_id
        )
        record_invocation_usage(
            billing_user_id,
            lease_owner,
            result.usage,
            work_type=("group_round" if round_size > 1 else "group"),
            bot_id=bot_id,
            group_id=group_id,
        )
        if result.pending_work:
            if _pause_work(reply_key, lease_owner, result.pending_work):
                _queue_background_poll(reply_key, request)
            return None
        answer = result.text
        artifacts = _collect_group_generated_artifacts(group_id, reply["id"])
    except Exception:
        logger.exception("Agent request failed for group reply %s", reply.get("id"))
        if receive_count < 3:
            _release_work(reply_key, lease_owner)
            raise
        _delete_group_generated_artifacts(group_id, reply["id"])
        answer = "I could not finish that request. Please try again."
        failed_at = _finish_work(reply_key, lease_owner, "ERROR", "text", answer)
        if not failed_at:
            return None
        if notify:
            _queue_group_reply_notifications(group_id, reply_key, reply, bot, answer)
        return answer

    completed_at = _finish_work(
        reply_key, lease_owner, "COMPLETE", "text", answer, artifacts=artifacts
    )
    if not completed_at:
        _delete_group_generated_artifacts(group_id, reply["id"])
        return None
    try:
        table.update_item(
            Key={"pk": _group_pk(group_id), "sk": "META"},
            UpdateExpression="SET lastMessage = :answer, lastMessageAt = :now, updatedAt = :now",
            ExpressionAttributeValues={":answer": answer[:280], ":now": completed_at},
        )
    except Exception:
        logger.exception(
            "Could not update the group preview for reply %s", reply.get("id")
        )
    if notify:
        _queue_group_reply_notifications(group_id, reply_key, reply, bot, answer)
    return answer


def _activate_group_reply(group_id: str, reply_key: str) -> None:
    """Move a queued team contribution into the visible working state."""
    try:
        table.update_item(
            Key={"pk": _group_pk(group_id), "sk": reply_key},
            UpdateExpression="SET #status = :pending",
            ConditionExpression="#status = :waiting",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":pending": "PENDING", ":waiting": "WAITING"},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        # The first reply starts as pending, and retried jobs may already be complete.
        return


def _process_group_agent_round(record: dict, request: dict) -> None:
    replies = request.get("replies")
    index = request.get("nextReplyIndex", 0)
    reply, final_reply = group_round_step(replies, index)
    _activate_group_reply(request["groupId"], reply["replyKey"])
    answer = _process_group_agent_reply(
        record,
        {
            **request,
            **reply,
            "roundPosition": index + 1,
            "roundSize": len(replies),
        },
        notify=final_reply,
    )
    if answer is not None and not final_reply:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({**request, "nextReplyIndex": index + 1}),
        )
