from __future__ import annotations

import logging

from shared.work_state import is_claimable

from .agent import _invoke, _progress_updater
from .artifacts import _collect_generated_artifacts, _delete_generated_artifacts
from .background_work import _queue_background_poll
from .notifications import _queue_reply_notification, _update_schedule_result
from .support import _account_is_active, _bot_key, _turn_pk, catalog, table
from .usage import record_invocation_usage
from .work import _claim_work, _finish_work, _pause_work, _release_work

logger = logging.getLogger(__name__)


def _process_agent_reply(record: dict, request: dict) -> None:
    user_id = request["userId"]
    bot_id = request["botId"]
    turn_key = {"pk": _turn_pk(user_id, bot_id), "sk": request["turnKey"]}
    turn = table.get_item(Key=turn_key, ConsistentRead=True).get("Item")
    if not turn:
        return
    if not _account_is_active(user_id):
        return
    bot = table.get_item(Key=_bot_key(user_id, bot_id), ConsistentRead=True).get("Item")
    if not bot:
        raise ValueError("Bot no longer exists")
    if turn.get("pendingWork"):
        _queue_background_poll(turn_key, request, delay_seconds=0)
        return
    if (
        turn.get("status") in {"COMPLETE", "ERROR"}
        and not turn.get("notificationQueued")
        and turn.get("assistantText")
    ):
        _update_schedule_result(
            turn,
            turn["status"].lower(),
            turn.get("completedAt", turn["createdAt"]),
        )
        _queue_reply_notification(
            user_id, bot_id, turn_key, turn, bot, turn["assistantText"]
        )
        return
    interactive_tool_names = catalog.approval_tool_names(
        user_id, bot.get("toolIds", [])
    )
    unapproved_tools = catalog.unapproved_tools(
        user_id,
        bot.get("toolIds", []),
        bot.get("alwaysAllowedToolIds", []),
    )
    approval_tools = [item["name"] for item in unapproved_tools]
    approval_tool_ids = [item["id"] for item in unapproved_tools]
    if turn.get("source") == "schedule" and interactive_tool_names:
        if not is_claimable(turn.get("status")):
            return
        lease_owner = _claim_work(turn_key, record)
        if not lease_owner:
            return
        failure_answer = (
            "This scheduled task was stopped because interactive tools require "
            "approval in a direct chat."
        )
        failed_at = _finish_work(
            turn_key, lease_owner, "ERROR", "assistantText", failure_answer
        )
        if not failed_at:
            return
        _update_schedule_result(turn, "error", failed_at)
        _queue_reply_notification(user_id, bot_id, turn_key, turn, bot, failure_answer)
        return
    if approval_tools and not turn.get("approvedAt"):
        try:
            table.update_item(
                Key=turn_key,
                UpdateExpression=(
                    "SET #status = :awaiting, approvalTools = :approvalTools, "
                    "approvalToolIds = :approvalToolIds"
                ),
                ConditionExpression="#status = :pending",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":pending": "PENDING",
                    ":awaiting": "AWAITING_APPROVAL",
                    ":approvalTools": approval_tools,
                    ":approvalToolIds": approval_tool_ids,
                },
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            pass
        return
    if not is_claimable(turn.get("status")):
        if turn.get("status") in {"COMPLETE", "ERROR"}:
            _update_schedule_result(
                turn,
                turn["status"].lower(),
                turn.get("completedAt", turn["createdAt"]),
            )
        return

    lease_owner = _claim_work(turn_key, record)
    if not lease_owner:
        return

    receive_count = int(
        record.get("attributes", {}).get("ApproximateReceiveCount", "1")
    )
    if receive_count > 1:
        _delete_generated_artifacts(user_id, turn["id"])
    try:
        result = _invoke(
            user_id,
            bot_id,
            bot,
            event_id=turn["id"],
            continuation=turn.get("backgroundResults"),
            on_progress=_progress_updater(turn_key, lease_owner),
        )
        record_invocation_usage(
            user_id,
            lease_owner,
            result.usage,
            work_type=("schedule" if turn.get("source") == "schedule" else "direct"),
            bot_id=bot_id,
        )
        if result.pending_work:
            if _pause_work(turn_key, lease_owner, result.pending_work):
                _queue_background_poll(turn_key, request)
            return
        answer = result.text
        artifacts = _collect_generated_artifacts(user_id, turn["id"])
    except Exception:
        logger.exception("Agent request failed for turn %s", turn.get("id"))
        if receive_count < 3:
            _release_work(turn_key, lease_owner)
            raise
        _delete_generated_artifacts(user_id, turn["id"])
        failure_answer = "I could not finish that request. Please try again."
        failed_at = _finish_work(
            turn_key, lease_owner, "ERROR", "assistantText", failure_answer
        )
        if not failed_at:
            return
        _update_schedule_result(turn, "error", failed_at)
        _queue_reply_notification(user_id, bot_id, turn_key, turn, bot, failure_answer)
        return

    completed_at = _finish_work(
        turn_key,
        lease_owner,
        "COMPLETE",
        "assistantText",
        answer,
        artifacts=artifacts,
    )
    if not completed_at:
        _delete_generated_artifacts(user_id, turn["id"])
        return
    try:
        table.update_item(
            Key=_bot_key(user_id, bot_id),
            UpdateExpression="SET lastMessage = :answer, lastMessageAt = :now, updatedAt = :now",
            ExpressionAttributeValues={":answer": answer[:280], ":now": completed_at},
        )
    except Exception:
        logger.exception("Could not update the bot preview for turn %s", turn.get("id"))
    _update_schedule_result(turn, "complete", completed_at)
    _queue_reply_notification(user_id, bot_id, turn_key, turn, bot, answer)
