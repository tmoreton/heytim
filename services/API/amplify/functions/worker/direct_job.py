from __future__ import annotations

import logging
from datetime import UTC, datetime

from shared.action_grants import approval_grant_digest
from shared.job_envelope import send_job
from shared.time import utc_now_iso
from shared.work_state import is_claimable

from .agent import _invoke, agent_failure_message
from .approval_job import delete_approval_snapshot, queue_approval_expiry
from .artifacts import _collect_generated_artifacts, _delete_generated_artifacts
from .background_work import _queue_background_poll
from .bot_mutations import apply_bot_mutations
from .device_calls import create_device_call, unavailable_device_result
from .health_events import record_terminal_error
from .job_lifecycle import (
    FailureDisposition,
    begin_attempt,
    finish_failed_attempt,
)
from .notifications import (
    _queue_email_delivery,
    _queue_reply_notification,
    _update_schedule_result,
)
from .progress import progress_updater
from .support import (
    QUEUE_URL,
    _account_is_active,
    _bot_key,
    _turn_pk,
    catalog,
    sqs,
    table,
)
from .usage import record_invocation_usage
from .usage_controls import (
    AdmissionDecision,
    UsageControlUnavailable,
    admit_run,
)
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

    try:
        billing_user_id = turn.get("userId")
        if billing_user_id != user_id:
            raise UsageControlUnavailable("Turn billing identity is invalid")
        admission = admit_run(
            billing_user_id,
            f"direct:{turn['id']}",
        )
    except (UsageControlUnavailable, ValueError):
        logger.exception(
            "Usage controls could not authorize direct turn %s", turn.get("id")
        )
        admission = AdmissionDecision(False, "storage_unavailable")
    if not admission.allowed:
        cleanup_artifacts()
        completed_at = _finish_work(
            turn_key,
            lease_owner,
            "ERROR",
            "assistantText",
            admission.user_message,
        )
        if not completed_at:
            return
        _update_schedule_result(turn, "error", completed_at)
        _queue_reply_notification(
            user_id, bot_id, turn_key, turn, bot, admission.user_message
        )
        return

    attempt = begin_attempt(record, lambda: None)
    configuration_changed = False
    try:
        decision = turn.get("approvalDecision")
        if decision and not turn.get("runtimeResult"):
            proposal = turn.get("approvalRequest")
            if (
                not isinstance(proposal, dict)
                or any(decision.get(key) != proposal.get(key) for key in ("id", "digest", "toolUseId"))
                or not catalog.approval_tool_names(user_id, bot.get("toolIds", []))
                or turn.get("approvalGrantDigest") != approval_grant_digest(catalog, user_id, bot)
                or datetime.fromisoformat(proposal["expiresAt"].replace("Z", "+00:00")) <= datetime.now(UTC)
                or turn.get("approvalConsumedAt")
            ):
                raise ValueError("Approval expired, changed, or its outcome is uncertain")
            table.update_item(
                Key=turn_key,
                UpdateExpression="SET approvalConsumedAt = :now",
                ConditionExpression=(
                    "#status = :running AND leaseOwner = :owner AND "
                    "approvalDecision = :decision AND attribute_not_exists(approvalConsumedAt)"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":running": "RUNNING", ":owner": lease_owner,
                    ":decision": decision, ":now": utc_now_iso(),
                },
            )
        device_result = turn.get("deviceResult")
        if device_result and not turn.get("runtimeResult"):
            device_request = turn.get("deviceRequest")
            device_received_at = turn.get("deviceResultReceivedAt")
            if (
                not isinstance(device_result, dict)
                or not isinstance(device_request, dict)
                or not isinstance(device_received_at, str)
                or any(
                    device_result.get(key) != device_request.get(key)
                    for key in ("id", "digest", "toolUseId")
                )
                or device_result.get("status") not in {"success", "error"}
                or datetime.fromisoformat(
                    device_received_at.replace("Z", "+00:00")
                )
                > datetime.fromisoformat(
                    device_request["expiresAt"].replace("Z", "+00:00")
                )
                or turn.get("deviceResultConsumedAt")
            ):
                raise ValueError("Device result expired, changed, or was already consumed")
            table.update_item(
                Key=turn_key,
                UpdateExpression="SET deviceResultConsumedAt = :now",
                ConditionExpression=(
                    "#status = :running AND leaseOwner = :owner AND "
                    "deviceResult = :result AND attribute_not_exists(deviceResultConsumedAt)"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":running": "RUNNING",
                    ":owner": lease_owner,
                    ":result": device_result,
                    ":now": utc_now_iso(),
                },
            )
        result = _invoke(
            user_id,
            bot_id,
            bot,
            billing_user_id=billing_user_id,
            event_id=turn["id"],
            continuation=turn.get("backgroundResults"),
            on_progress=progress_updater(turn_key, lease_owner),
            runtime_result=turn.get("runtimeResult"),
            work_key=turn_key, lease_owner=lease_owner, resume_request=request,
            allow_bot_management=turn.get("source") != "schedule",
            workspace_files=turn.get("attachments", []),
            action_approval=(
                {key: decision[key] for key in ("id", "digest", "toolUseId")}
                if decision and not turn.get("runtimeResult") else None
            ),
            device_result=(
                device_result
                if device_result and not turn.get("runtimeResult")
                else None
            ),
            allow_device_tools=turn.get("source") not in {"schedule", "email"},
        )
        record_invocation_usage(
            user_id,
            result.usage_event_id or lease_owner,
            result.usage,
            work_type=("schedule" if turn.get("source") == "schedule" else "direct"),
            bot_id=bot_id,
        )
        if result.bot_mutations and (
            result.pending_work
            or result.pending_approval
            or result.pending_device_call
            or result.terminal_error
        ):
            raise ValueError(
                "A bot, skill, or memory change cannot be combined with unfinished or failed work"
            )
        if result.pending_work:
            if _pause_work(turn_key, lease_owner, result.pending_work):
                _queue_background_poll(turn_key, request)
            return
        if result.pending_device_call:
            proposal = result.pending_device_call
            device_request = create_device_call(
                user_id, bot, turn, turn_key, proposal
            )
            if device_request is None:
                retry_result = unavailable_device_result(proposal)
                table.update_item(
                    Key=turn_key,
                    UpdateExpression=(
                        "SET #status = :pending, deviceRequest = :proposal, "
                        "deviceResult = :result, deviceResultReceivedAt = :now, "
                        "activity = :activity, "
                        "activityUpdatedAt = :now "
                        "REMOVE leaseOwner, leaseExpiresAt, runtimeResult, "
                        "deviceResultConsumedAt, approvalRequest, approvalDecision, "
                        "approvalConsumedAt, approvalTools, approvalToolIds"
                    ),
                    ConditionExpression="#status = :running AND leaseOwner = :owner",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":pending": "PENDING",
                        ":running": "RUNNING",
                        ":owner": lease_owner,
                        ":proposal": proposal,
                        ":result": retry_result,
                        ":activity": ["Authorized device is unavailable"],
                        ":now": utc_now_iso(),
                    },
                )
                send_job(sqs, QUEUE_URL, request)
                return
            table.update_item(
                Key=turn_key,
                UpdateExpression=(
                    "SET #status = :awaiting, deviceRequest = :request, "
                    "activity = :activity, activityUpdatedAt = :now "
                    "REMOVE leaseOwner, leaseExpiresAt, runtimeResult, deviceResult, "
                    "deviceResultReceivedAt, deviceResultConsumedAt, approvalRequest, approvalDecision, "
                    "approvalConsumedAt, approvalTools, approvalToolIds"
                ),
                ConditionExpression="#status = :running AND leaseOwner = :owner",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":awaiting": "AWAITING_DEVICE",
                    ":running": "RUNNING",
                    ":owner": lease_owner,
                    ":request": device_request,
                    ":activity": ["Waiting for authorized Apple device"],
                    ":now": utc_now_iso(),
                },
            )
            return
        if result.pending_approval:
            proposal = result.pending_approval
            if not all(isinstance(proposal.get(key), str) and proposal[key]
                       for key in ("id", "digest", "toolUseId", "toolName", "expiresAt")):
                raise ValueError("Approval proposal is invalid")
            queue_approval_expiry(turn_key, proposal, "direct")
            table.update_item(
                Key=turn_key,
                UpdateExpression=(
                    "SET #status = :awaiting, approvalRequest = :proposal, approvalGrantDigest = :grant, "
                    "approvalTools = :tools, "
                    "activity = :activity, activityUpdatedAt = :now "
                    "REMOVE leaseOwner, leaseExpiresAt, approvalDecision, approvalConsumedAt, runtimeResult"
                ),
                ConditionExpression="#status = :running AND leaseOwner = :owner",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":awaiting": "AWAITING_APPROVAL", ":running": "RUNNING",
                    ":owner": lease_owner, ":proposal": proposal,
                    ":grant": approval_grant_digest(catalog, user_id, bot),
                    ":tools": catalog.approval_tool_names(user_id, bot.get("toolIds", [])),
                    ":activity": ["Approval needed for " + proposal["toolName"]],
                    ":now": utc_now_iso(),
                },
            )
            _update_schedule_result(turn, "awaiting_approval", turn["createdAt"])
            _queue_email_delivery(
                user_id, bot_id, turn, bot, event="approval"
            )
            return
        if result.terminal_error:
            record_terminal_error(result.terminal_error)
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
            if decision or device_result:
                try:
                    delete_approval_snapshot("direct", user_id, turn["id"], bot_id)
                except Exception:
                    logger.exception("Could not remove completed approval snapshot")
            _update_schedule_result(turn, "error", completed_at)
            _queue_reply_notification(
                user_id, bot_id, turn_key, turn, bot, result.terminal_error
            )
            return
        answer = result.text
        if result.bot_mutations:
            apply_bot_mutations(user_id, bot, turn, result.bot_mutations)
            configuration_changed = any(
                mutation.get("action") != "create_memory"
                for mutation in result.bot_mutations
                if isinstance(mutation, dict)
            )
        artifacts = _collect_generated_artifacts(user_id, bot_id, turn["id"])
    except Exception as error:
        record_terminal_error(error)
        logger.exception("Agent request failed for turn %s", turn.get("id"))
        failure_answer = agent_failure_message(error)
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
        configuration_changed=configuration_changed,
    )
    if not completed_at:
        cleanup_artifacts()
        return
    if decision or device_result:
        try:
            delete_approval_snapshot("direct", user_id, turn["id"], bot_id)
        except Exception:
            logger.exception("Could not remove completed approval snapshot")
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
