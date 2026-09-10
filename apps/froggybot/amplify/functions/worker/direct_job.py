from __future__ import annotations

import logging

from shared.work_state import is_claimable

from .agent import _invoke, _progress_updater
from .artifacts import _collect_generated_artifacts, _delete_generated_artifacts
from .background_work import _queue_background_poll
from .bot_mutations import apply_bot_mutations
from .job_lifecycle import (
    FailureDisposition,
    begin_attempt,
    finish_failed_attempt,
)
from .notifications import _queue_reply_notification, _update_schedule_result
from .support import _account_is_active, _bot_key, _turn_pk, catalog, table
from .usage import record_invocation_usage
from .work import _claim_work, _finish_work, _pause_work

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
    unapproved_tools = catalog.unapproved_tools(
        user_id,
        bot.get("toolIds", []),
        bot.get("alwaysAllowedToolIds", []),
    )
    approval_tools = [item["name"] for item in unapproved_tools]
    approval_tool_ids = [item["id"] for item in unapproved_tools]
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
        _update_schedule_result(turn, "awaiting_approval", turn["createdAt"])
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

    def cleanup_artifacts() -> None:
        _delete_generated_artifacts(user_id, bot_id, turn["id"])

    attempt = begin_attempt(record, lambda: None)
    try:
        result = _invoke(
            user_id,
            bot_id,
            bot,
            event_id=turn["id"],
            continuation=turn.get("backgroundResults"),
            on_progress=_progress_updater(turn_key, lease_owner),
            runtime_result=turn.get("runtimeResult"),
            work_key=turn_key, lease_owner=lease_owner, resume_request=request,
            allow_bot_management=turn.get("source") != "schedule",
        )
        record_invocation_usage(
            user_id,
            result.usage_event_id or lease_owner,
            result.usage,
            work_type=("schedule" if turn.get("source") == "schedule" else "direct"),
            bot_id=bot_id,
        )
        if result.bot_mutations and (result.pending_work or result.terminal_error):
            raise ValueError(
                "A bot change cannot be combined with unfinished or failed work"
            )
        if result.pending_work:
            if _pause_work(turn_key, lease_owner, result.pending_work):
                _queue_background_poll(turn_key, request)
            return
        if result.terminal_error:
            cleanup_artifacts()
            completed_at = _finish_work(
                turn_key,
                lease_owner,
                "ERROR",
                "assistantText",
                result.terminal_error,
            )
            if not completed_at:
                return
            _update_schedule_result(turn, "error", completed_at)
            _queue_reply_notification(
                user_id, bot_id, turn_key, turn, bot, result.terminal_error
            )
            return
        answer = result.text
        if result.bot_mutations:
            apply_bot_mutations(user_id, bot, turn, result.bot_mutations)
        artifacts = _collect_generated_artifacts(user_id, bot_id, turn["id"])
    except Exception:
        logger.exception("Agent request failed for turn %s", turn.get("id"))
        failure_answer = "I could not finish that request. Please try again."
        failure = finish_failed_attempt(
            attempt,
            turn_key,
            lease_owner,
            "assistantText",
            failure_answer,
            cleanup_artifacts,
        )
        if failure.disposition is FailureDisposition.RETRY:
            raise
        if failure.disposition is FailureDisposition.LOST_LEASE:
            return
        _update_schedule_result(turn, "error", failure.completed_at)
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
        cleanup_artifacts()
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
