from __future__ import annotations

import json
import logging
from decimal import Decimal

from botocore.exceptions import BotoCoreError, ClientError
from shared.action_grants import approval_grant_digest
from shared.group_chat import group_round_step
from shared.keys import group_message_sk
from shared.memory_identity import group_memory_actor_id, group_memory_session_id
from shared.time import utc_now_iso
from shared.work_state import is_claimable
from shared.workflows import TERMINAL_STATUSES, is_parallel_group_round, run_key

from .agent import (
    _get_group_context,
    _get_group_history,
    _invoke,
    agent_failure_message,
)
from .approval_job import delete_approval_snapshot, queue_approval_expiry
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
from .progress import progress_updater
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
from .usage_controls import (
    AdmissionDecision,
    UsageControlUnavailable,
    admit_run,
)
from .work import _claim_work, _finish_work, _pause_work

logger = logging.getLogger(__name__)


class _AdmissionDeniedText(str):
    """Internal signal that the complete coordinated round must stop."""


def _finish_group_admission_denial(
    reply_key: dict, lease_owner: str, answer: str
) -> str | None:
    completed_at = utc_now_iso()
    try:
        table.update_item(
            Key=reply_key,
            UpdateExpression=(
                "SET #status = :error, #text = :answer, completedAt = :now, "
                "usageAdmissionDenied = :denied REMOVE leaseOwner, leaseExpiresAt, "
                "pendingWork, backgroundResults, runtimeResult"
            ),
            ConditionExpression="#status = :running AND leaseOwner = :owner",
            ExpressionAttributeNames={"#status": "status", "#text": "text"},
            ExpressionAttributeValues={
                ":error": "ERROR",
                ":running": "RUNNING",
                ":owner": lease_owner,
                ":answer": answer,
                ":now": completed_at,
                ":denied": True,
            },
        )
        return completed_at
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return None


def _finalize_remaining_group_denials(
    group_id: str, replies: list[dict], start_index: int, answer: str
) -> None:
    completed_at = utc_now_iso()
    for entry in replies[start_index:]:
        key = {"pk": _group_pk(group_id), "sk": entry["replyKey"]}
        try:
            table.update_item(
                Key=key,
                UpdateExpression=(
                    "SET #status = :error, #text = :answer, completedAt = :now, "
                    "usageAdmissionDenied = :denied REMOVE leaseOwner, "
                    "leaseExpiresAt, pendingWork, backgroundResults, runtimeResult"
                ),
                ConditionExpression="#status = :waiting OR #status = :pending",
                ExpressionAttributeNames={"#status": "status", "#text": "text"},
                ExpressionAttributeValues={
                    ":error": "ERROR",
                    ":waiting": "WAITING",
                    ":pending": "PENDING",
                    ":answer": answer,
                    ":now": completed_at,
                    ":denied": True,
                },
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            item = table.get_item(Key=key, ConsistentRead=True).get("Item")
            if not item or item.get("status") not in {"COMPLETE", "ERROR"}:
                raise


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
    bot_owner_id = reply.get("botOwnerId")
    if not isinstance(bot_owner_id, str) or not bot_owner_id.strip():
        raise ValueError("Group reply has no persisted bot owner")
    if not _account_is_active(bot_owner_id):
        return
    bot = table.get_item(Key=_bot_key(bot_owner_id, bot_id), ConsistentRead=True).get(
        "Item"
    )
    if not bot:
        raise ValueError("Source bot no longer exists")
    billing_user_id = reply.get("billingUserId")
    billing_denial: AdmissionDecision | None = None
    if not isinstance(billing_user_id, str) or not billing_user_id.strip():
        billing_denial = AdmissionDecision(False, "storage_unavailable")
    else:
        try:
            if not _account_is_active(billing_user_id):
                billing_denial = AdmissionDecision(False, "account_inactive")
        except (BotoCoreError, ClientError):
            logger.exception(
                "Billing account state could not be verified for group reply %s",
                reply.get("id"),
            )
            billing_denial = AdmissionDecision(False, "storage_unavailable")
    if billing_denial is not None:
        if not is_claimable(reply.get("status")):
            return None
        lease_owner = _claim_work(reply_key, record)
        if not lease_owner:
            return None
        _delete_group_generated_artifacts(group_id, reply["id"])
        failed_at = _finish_group_admission_denial(
            reply_key, lease_owner, billing_denial.user_message
        )
        if not failed_at:
            return None
        _queue_group_reply_notifications(
            group_id, reply_key, reply, bot, billing_denial.user_message
        )
        return _AdmissionDeniedText(billing_denial.user_message)
    if reply.get("pendingWork"):
        _queue_background_poll(reply_key, request, delay_seconds=0)
        return None
    if (
        reply.get("status") in {"COMPLETE", "ERROR"}
        and reply.get("text")
    ):
        admission_denied = reply.get("usageAdmissionDenied") is True
        if (notify or admission_denied) and not reply.get("notificationQueued"):
            _queue_group_reply_notifications(
                group_id, reply_key, reply, bot, reply["text"]
            )
        return (
            _AdmissionDeniedText(reply["text"])
            if admission_denied
            else reply["text"]
        )
    if (bot_owner_id != billing_user_id
            and catalog.approval_tool_names(bot_owner_id, bot.get("toolIds", []))):
        if not is_claimable(reply.get("status")):
            return None
        lease_owner = _claim_work(reply_key, record)
        if not lease_owner:
            return None
        failure_answer = (
            "This group reply was stopped because only the requester's own bot "
            "can request an interactive action."
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

    try:
        round_id = reply.get("roundId", reply.get("id"))
        round_size = reply.get("roundSize", 1)
        if (
            isinstance(round_size, Decimal)
            and round_size == round_size.to_integral_value()
        ):
            round_size = int(round_size)
        if not isinstance(round_id, str) or not round_id.strip():
            raise UsageControlUnavailable("Group reply round identity is invalid")
        if (
            isinstance(round_size, bool)
            or not isinstance(round_size, int)
            or round_size < 1
        ):
            raise UsageControlUnavailable("Group reply round size is invalid")
        admission = admit_run(
            billing_user_id,
            f"group:{group_id}:{round_id}",
            run_units=round_size,
        )
    except (UsageControlUnavailable, ValueError):
        logger.exception(
            "Usage controls could not authorize group reply %s", reply.get("id")
        )
        admission = AdmissionDecision(False, "storage_unavailable")
    if not admission.allowed:
        cleanup_artifacts()
        failed_at = _finish_group_admission_denial(
            reply_key, lease_owner, admission.user_message
        )
        if not failed_at:
            return None
        _queue_group_reply_notifications(
            group_id, reply_key, reply, bot, admission.user_message
        )
        return _AdmissionDeniedText(admission.user_message)

    attempt = begin_attempt(record, lambda: None)
    try:
        decision = reply.get("approvalDecision")
        if decision and not reply.get("runtimeResult"):
            from datetime import UTC, datetime
            proposal = reply.get("approvalRequest")
            if (
                bot_owner_id != billing_user_id
                or not isinstance(proposal, dict)
                or any(decision.get(key) != proposal.get(key) for key in ("id", "digest", "toolUseId"))
                or not catalog.approval_tool_names(bot_owner_id, bot.get("toolIds", []))
                or reply.get("approvalGrantDigest") != approval_grant_digest(catalog, bot_owner_id, bot)
                or datetime.fromisoformat(proposal["expiresAt"].replace("Z", "+00:00")) <= datetime.now(UTC)
                or reply.get("approvalConsumedAt")
                or _run_is_cancelled(group_id, reply.get("runId"))
            ):
                raise ValueError("Approval expired, changed, or its outcome is uncertain")
            table.update_item(
                Key=reply_key,
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
        round_position = int(
            request.get("roundPosition", reply.get("roundPosition", 1))
        )
        round_size = int(request.get("roundSize", reply.get("roundSize", 1)))
        round_role = str(request.get("roundRole", reply.get("roundRole", "solo")))
        coordinator_bot_id = request.get(
            "coordinatorBotId", reply.get("coordinatorBotId")
        )
        source_message = {}
        if isinstance(reply.get("createdAt"), str) and isinstance(request.get("messageId"), str):
            source_message = table.get_item(
                Key={
                    "pk": _group_pk(group_id),
                    "sk": group_message_sk(reply["createdAt"], request["messageId"]),
                },
                ConsistentRead=True,
            ).get("Item", {})
        result = _invoke(
            bot_owner_id,
            bot_id,
            bot,
            billing_user_id=billing_user_id,
            history=_get_group_history(
                group_id, bot_id, request.get("messageId"),
                parallel_role=(
                    round_role if request.get("parallelRound") is True else None
                ),
                current_message_sk=(
                    group_message_sk(reply["createdAt"], request["messageId"])
                    if request.get("parallelRound") is True else None
                ),
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
            on_progress=progress_updater(reply_key, lease_owner),
            runtime_result=reply.get("runtimeResult"),
            work_key=reply_key, lease_owner=lease_owner, resume_request=request,
            workspace_files=source_message.get("attachments", []),
            action_approval=(
                {key: decision[key] for key in ("id", "digest", "toolUseId")}
                if decision and not reply.get("runtimeResult") else None
            ),
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
        if result.pending_approval:
            proposal = result.pending_approval
            if not all(isinstance(proposal.get(key), str) and proposal[key]
                       for key in ("id", "digest", "toolUseId", "toolName", "expiresAt")):
                raise ValueError("Approval proposal is invalid")
            queue_approval_expiry(reply_key, proposal, "group")
            table.update_item(
                Key=reply_key,
                UpdateExpression=(
                    "SET #status = :awaiting, approvalRequest = :proposal, approvalGrantDigest = :grant, "
                    "resumeRequest = :request, activity = :activity, activityUpdatedAt = :now "
                    "REMOVE leaseOwner, leaseExpiresAt, approvalDecision, approvalConsumedAt, runtimeResult"
                ),
                ConditionExpression="#status = :running AND leaseOwner = :owner",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":awaiting": "AWAITING_APPROVAL", ":running": "RUNNING",
                    ":owner": lease_owner, ":proposal": proposal,
                    ":grant": approval_grant_digest(catalog, bot_owner_id, bot),
                    ":request": request, ":activity": ["Approval needed for " + proposal["toolName"]],
                    ":now": utc_now_iso(),
                },
            )
            _set_group_run_status(group_id, reply.get("runId"), "AWAITING_APPROVAL")
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
            if decision:
                try:
                    delete_approval_snapshot("group", group_id, reply["id"])
                except Exception:
                    logger.exception("Could not remove completed approval snapshot")
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
    if decision:
        try:
            delete_approval_snapshot("group", group_id, reply["id"])
        except Exception:
            logger.exception("Could not remove completed approval snapshot")
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


def _set_group_run_status(group_id: str, run_id: str, status: str) -> None:
    if not isinstance(run_id, str) or not run_id:
        return
    values = {":status": status, ":now": utc_now_iso(), ":cancelled": "CANCELLED", ":entity": "WORKFLOW_RUN"}
    expression = "SET #status = :status, updatedAt = :now"
    if status in TERMINAL_STATUSES:
        expression += ", completedAt = :now"
    try:
        table.update_item(
            Key=run_key(_group_pk(group_id), run_id),
            UpdateExpression=expression,
            ConditionExpression="#status <> :cancelled AND #entity = :entity",
            ExpressionAttributeNames={"#status": "status", "#entity": "entity"},
            ExpressionAttributeValues=values,
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        # Older in-flight rounds have no workflow record.
        return


def _run_is_cancelled(group_id: str, run_id: object) -> bool:
    if not isinstance(run_id, str) or not run_id:
        return False
    run = table.get_item(
        Key=run_key(_group_pk(group_id), run_id), ConsistentRead=True
    ).get("Item")
    return bool(run and run.get("status") == "CANCELLED")


def _cancel_queued_reply(group_id: str, reply_key: str) -> None:
    try:
        table.update_item(
            Key={"pk": _group_pk(group_id), "sk": reply_key},
            UpdateExpression="SET #status = :cancelled, completedAt = :now",
            ConditionExpression="#status = :pending OR #status = :waiting",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":cancelled": "CANCELLED", ":now": utc_now_iso(),
                ":pending": "PENDING", ":waiting": "WAITING",
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return


def _process_group_agent_round(record: dict, request: dict) -> None:
    replies = request.get("replies")
    index = request.get("nextReplyIndex", 0)
    reply, final_reply = group_round_step(replies, index)
    if _run_is_cancelled(request["groupId"], request.get("messageId")):
        _cancel_queued_reply(request["groupId"], reply["replyKey"])
        return
    logger.info("Group round %s step %d/%d for reply %s", request.get("messageId"), index + 1, len(replies), reply.get("replyKey"))
    if request.get("scheduleId") or request.get("source") == "event":
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
    if isinstance(answer, _AdmissionDeniedText):
        _set_group_run_status(request["groupId"], request.get("messageId"), "ERROR")
        _finalize_remaining_group_denials(
            request["groupId"], replies, index + 1, str(answer)
        )
        if request.get("scheduleId"):
            _update_schedule_result(
                {
                    "source": "schedule",
                    "scheduleId": request["scheduleId"],
                    "userId": request["requestedBy"],
                },
                "error",
                utc_now_iso(),
            )
        return
    if answer is not None and index == 0 and not final_reply:
        _set_group_run_status(request["groupId"], request.get("messageId"), "RUNNING")
    if answer is not None and _run_is_cancelled(request["groupId"], request.get("messageId")):
        return
    if answer is not None and is_parallel_group_round(replies) and len(replies) <= 5 and index == 0:
        for child_index in range(1, len(replies) - 1):
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps({
                    **request,
                    "type": "GROUP_AGENT_CONTRIBUTOR",
                    "nextReplyIndex": child_index,
                    "parallelRound": True,
                }),
            )
        logger.info(
            "Group round %s queued %d parallel contributors",
            request.get("messageId"), len(replies) - 2,
        )
        return
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
    if answer is not None and final_reply:
        states = [
            table.get_item(
                Key={"pk": _group_pk(request["groupId"]), "sk": entry["replyKey"]},
                ConsistentRead=True,
            ).get("Item", {})
            for entry in replies
        ]
        status = "ERROR" if any(item.get("status") == "ERROR" for item in states) else "COMPLETE"
        _set_group_run_status(request["groupId"], request.get("messageId"), status)


def _process_group_agent_contributor(record: dict, request: dict) -> None:
    replies = request.get("replies")
    index = request.get("nextReplyIndex")
    reply, _ = group_round_step(replies, index)
    if (
        not is_parallel_group_round(replies)
        or not 0 < index < len(replies) - 1
        or reply.get("roundRole") != "contributor"
    ):
        raise ValueError("Parallel group contribution is invalid")
    if _run_is_cancelled(request["groupId"], request.get("messageId")):
        _cancel_queued_reply(request["groupId"], reply["replyKey"])
        return
    if request.get("scheduleId") or request.get("source") == "event":
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
        {**request, **reply, "roundPosition": index + 1, "roundSize": len(replies)},
        notify=False,
    )
    if answer is None:
        return
    if _run_is_cancelled(request["groupId"], request.get("messageId")):
        return
    _queue_parallel_synthesis_if_ready(request)


def _queue_parallel_synthesis_if_ready(request: dict) -> None:
    replies = request["replies"]
    group_id = request["groupId"]
    if _run_is_cancelled(group_id, request.get("messageId")):
        return
    states = [
        table.get_item(
            Key={"pk": _group_pk(group_id), "sk": entry["replyKey"]},
            ConsistentRead=True,
        ).get("Item", {})
        for entry in replies[1:-1]
    ]
    if not all(item.get("status") in TERMINAL_STATUSES for item in states):
        return
    synthesis_index = len(replies) - 1
    synthesis = replies[synthesis_index]
    synthesis_key = {"pk": _group_pk(group_id), "sk": synthesis["replyKey"]}
    current = table.get_item(Key=synthesis_key, ConsistentRead=True).get("Item", {})
    if current.get("status") in TERMINAL_STATUSES:
        return
    # Duplicate SQS messages are safe: the synthesis reply has one durable lease.
    sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps({
            **request,
            "type": "GROUP_AGENT_ROUND",
            "nextReplyIndex": synthesis_index,
            "parallelRound": True,
        }),
    )
