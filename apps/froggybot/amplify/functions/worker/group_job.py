from __future__ import annotations

import json
import logging

from shared.group_chat import group_round_step
from shared.memory_identity import group_memory_actor_id, group_memory_session_id
from shared.time import utc_now_iso
from shared.work_state import is_claimable

from .agent import (
    _get_group_context,
    _get_group_history,
    _invoke,
    _progress_updater,
    agent_failure_message,
)
from .artifacts import (
    _collect_group_generated_artifacts,
    _delete_group_generated_artifacts,
    _group_generated_artifact_prefix,
)
from .background_work import _queue_background_poll
from .health_events import record_terminal_error
from .job_lifecycle import (
    FailureDisposition,
    begin_attempt,
    finish_failed_attempt,
)
from .notifications import _update_schedule_result
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
from .work import _claim_work, _finish_work, _pause_work

logger = logging.getLogger(__name__)


def _queue_group_reply_notifications(
    group_id: str, reply_key: dict, reply: dict, bot: dict, answer: str
) -> None:
    request = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
        "ExpressionAttributeValues": {
            ":pk": _group_pk(group_id),
            ":prefix": "USER#",
        },
    }
    members = []
    while True:
        response = table.query(**request)
        members.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        request["ExclusiveStartKey"] = last_key
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
                    **({"scheduleId": reply["scheduleId"], "scheduleName": reply.get("scheduleName", "Group report")} if reply.get("source") == "schedule" else {}),
                    "notificationId": (
                        f"group:{group_id}:{reply['id']}:{user_id}"
                    ),
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
        and reply.get("text")
    ):
        if notify and not reply.get("notificationQueued"):
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

    def cleanup_artifacts() -> None:
        _delete_group_generated_artifacts(group_id, reply["id"])

    attempt = begin_attempt(record, lambda: None)
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
            history=_get_group_history(
                group_id, bot_id, request.get("messageId")
            ),
            session_scope=f"group:{group_id}:bot:{bot_id}",
            event_id=reply["id"],
            artifact_prefix=_group_generated_artifact_prefix(group_id, reply["id"]),
            attachment_prefix=f"groups/{group_id}/uploads/",
            group_context=_get_group_context(
                group_id,
                bot_id,
                round_position,
                round_size,
                round_role,
                coordinator_bot_id,
            ),
            memory=(
                {
                    "actorId": group_memory_actor_id(group_id),
                    "sessionId": group_memory_session_id(group_id),
                    "eventId": reply["id"],
                    "scope": "group",
                    "userText": request["userText"],
                }
                if isinstance(request.get("userText"), str)
                and request["userText"].strip()
                else None
            ),
            continuation=reply.get("backgroundResults"),
            on_progress=_progress_updater(reply_key, lease_owner),
            runtime_result=reply.get("runtimeResult"),
            work_key=reply_key, lease_owner=lease_owner, resume_request=request,
        )
        requested_by = request.get("requestedBy")
        billing_user_id = (
            requested_by
            if isinstance(requested_by, str) and requested_by.strip()
            else bot_owner_id
        )
        record_invocation_usage(
            billing_user_id,
            result.usage_event_id or lease_owner,
            result.usage,
            work_type=("group_round" if round_size > 1 else "group"),
            bot_id=bot_id,
            group_id=group_id,
        )
        if result.pending_work:
            if _pause_work(reply_key, lease_owner, result.pending_work):
                _queue_background_poll(reply_key, request)
            return None
        if result.terminal_error:
            record_terminal_error(result.terminal_error)
            cleanup_artifacts()
            failed_at = _finish_work(
                reply_key,
                lease_owner,
                "ERROR",
                "text",
                result.terminal_error,
            )
            if not failed_at:
                return None
            if notify:
                _queue_group_reply_notifications(
                    group_id, reply_key, reply, bot, result.terminal_error
                )
            return result.terminal_error
        answer = result.text
        artifacts = _collect_group_generated_artifacts(group_id, reply["id"])
    except Exception as error:
        record_terminal_error(error)
        logger.exception("Agent request failed for group reply %s", reply.get("id"))
        answer = agent_failure_message(error)
        failure = finish_failed_attempt(
            attempt,
            reply_key,
            lease_owner,
            "text",
            answer,
            cleanup_artifacts,
        )
        if failure.disposition is FailureDisposition.RETRY:
            raise
        if failure.disposition is FailureDisposition.LOST_LEASE:
            return None
        if notify:
            _queue_group_reply_notifications(group_id, reply_key, reply, bot, answer)
        return answer

    completed_at = _finish_work(
        reply_key, lease_owner, "COMPLETE", "text", answer, artifacts=artifacts
    )
    if not completed_at:
        cleanup_artifacts()
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
    logger.info("Group round %s step %d/%d for reply %s", request.get("messageId"), index + 1, len(replies), reply.get("replyKey"))
    if request.get("scheduleId"):
        user_id = request.get("requestedBy")
        group_id = request["groupId"]
        meta = table.get_item(Key={"pk": _group_pk(group_id), "sk": "META"}, ConsistentRead=True).get("Item")
        member = table.get_item(Key={"pk": _group_pk(group_id), "sk": f"USER#{user_id}"}, ConsistentRead=True).get("Item")
        bot_member = table.get_item(Key={"pk": _group_pk(group_id), "sk": f"BOT#{reply['botId']}"}, ConsistentRead=True).get("Item")
        if not meta or not member or not bot_member or meta.get("ownerId") != user_id or not _account_is_active(user_id):
            return
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
        logger.info("Group round %s queued step %d/%d", request.get("messageId"), index + 2, len(replies))
    if answer is not None and final_reply and request.get("scheduleId"):
        states = [table.get_item(Key={"pk": _group_pk(request["groupId"]), "sk": entry["replyKey"]}, ConsistentRead=True).get("Item", {}) for entry in replies]
        status = "error" if any(item.get("status") == "ERROR" for item in states) else "complete"
        _update_schedule_result({"source": "schedule", "scheduleId": request["scheduleId"], "userId": request["requestedBy"]}, status, utc_now_iso())
