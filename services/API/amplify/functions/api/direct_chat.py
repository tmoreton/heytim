from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime

from boto3.dynamodb.conditions import Attr
from shared.action_grants import approval_grant_digest, grant_enabled_interactive_tools
from shared.approval_storage import approval_snapshot_key
from shared.client_contract import MESSAGE_MAX_LENGTH
from shared.memory_identity import direct_session_id
from shared.work_state import is_in_flight

from .attachments import _resolve_attachments
from .bot_inbox import inbox_message
from .bots import _get_bot
from .schedules import _get_schedule
from .support import (
    AGENT_RUNTIME_ARN,
    AGENT_RUNTIME_QUALIFIER,
    FILES_BUCKET_NAME,
    QUEUE_URL,
    ApiError,
    _bot_sk,
    _now,
    _partition_items,
    _schedule_key,
    _turn_pk,
    _user_pk,
    _validate_string,
    agentcore,
    catalog,
    s3,
    sqs,
    table,
)
from .workspaces import _resolve_workspace_files

logger = logging.getLogger(__name__)

SEND_LEASE_SECONDS = 60


def _stop_background_work(turn: dict) -> None:
    sessions = set()
    for work in turn.get("pendingWork", []):
        if isinstance(work, dict) and work.get("provider") == "agentcore_runtime":
            try:
                s3.put_object(Bucket=FILES_BUCKET_NAME, Key=f"{work['taskId']}.cancel",
                              Body=b'{"cancelled":true}', ContentType="application/json")
                agentcore.stop_runtime_session(
                    agentRuntimeArn=AGENT_RUNTIME_ARN, qualifier=AGENT_RUNTIME_QUALIFIER,
                    runtimeSessionId=work["sessionId"],
                )
            except agentcore.exceptions.ResourceNotFoundException:
                pass
            except Exception:
                logger.exception("Could not stop background agent; poll will retry")
            continue
        if not isinstance(work, dict) or work.get("provider") != "agentcore_code_interpreter":
            continue
        resource_id = work.get("resourceId")
        session_id = work.get("sessionId")
        task_id = work.get("taskId")
        if not all(isinstance(value, str) and value for value in (resource_id, session_id, task_id)):
            continue
        sessions.add((resource_id, session_id))
        try:
            agentcore.invoke_code_interpreter(
                codeInterpreterIdentifier=resource_id,
                sessionId=session_id,
                name="stopTask",
                arguments={"taskId": task_id},
            )
        except agentcore.exceptions.ResourceNotFoundException:
            pass
        except Exception:
            logger.exception("Could not stop background task %s", task_id)
    for resource_id, session_id in sessions:
        try:
            agentcore.stop_code_interpreter_session(
                codeInterpreterIdentifier=resource_id,
                sessionId=session_id,
            )
        except agentcore.exceptions.ResourceNotFoundException:
            pass
        except Exception:
            logger.exception("Could not stop background code session %s", session_id)


def _claim_send_lease(user_id: str, bot_id: str) -> str:
    owner = str(uuid.uuid4())
    current = int(time.time())
    try:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
            UpdateExpression=(
                "SET sendLeaseOwner = :owner, sendLeaseExpiresAt = :expires"
            ),
            ConditionExpression=(
                "attribute_exists(pk) AND (attribute_not_exists(sendLeaseExpiresAt) "
                "OR sendLeaseExpiresAt < :now)"
            ),
            ExpressionAttributeValues={
                ":owner": owner,
                ":now": current,
                ":expires": current + SEND_LEASE_SECONDS,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(409, "Another message is being sent. Try again in a moment") from exc
    return owner


def _release_send_lease(user_id: str, bot_id: str, owner: str) -> None:
    try:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
            UpdateExpression="REMOVE sendLeaseOwner, sendLeaseExpiresAt",
            ConditionExpression="sendLeaseOwner = :owner",
            ExpressionAttributeValues={":owner": owner},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass
    except Exception:
        logger.exception("Could not release the send lease for bot %s", bot_id)


def _start_bot_turn(
    user_id: str,
    bot_id: str,
    text: str,
    schedule_item: dict | None = None,
    attachments: list[dict] | None = None,
    email_context: dict | None = None,
) -> dict:
    turn_id = str(uuid.uuid4())
    current = _now()
    item = {
        "pk": _turn_pk(user_id, bot_id),
        "sk": f"TURN#{current}#{turn_id}",
        "entity": "TURN",
        "id": turn_id,
        "botId": bot_id,
        "userId": user_id,
        "userText": text,
        "createdAt": current,
        "status": "PENDING",
    }
    if attachments:
        item["attachments"] = attachments
    if email_context:
        item.update(
            {
                "source": "email",
                "emailSender": email_context.get("from", ""),
                "emailRecipient": email_context.get("recipient", ""),
                "emailSubject": email_context.get("subject", ""),
                "emailSesMessageId": email_context.get("sesMessageId", ""),
                "emailMessageIdHeader": email_context.get("messageIdHeader", ""),
                "emailInReplyTo": email_context.get("inReplyTo", ""),
                "emailReferences": email_context.get("references", ""),
            }
        )
    if schedule_item:
        item.update(
            {
                "source": "schedule",
                "scheduleId": schedule_item["id"],
                "scheduleName": schedule_item["name"],
            }
        )
    table.put_item(Item=item)
    if schedule_item:
        try:
            table.update_item(
                Key=_schedule_key(user_id, schedule_item["id"]),
                UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
                ConditionExpression=Attr("pk").exists(),
                ExpressionAttributeValues={":now": current, ":status": "pending"},
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
            raise ApiError(404, "Scheduled task not found") from exc
    try:
        table.update_item(
            Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
            UpdateExpression="SET lastMessage = :message, lastMessageAt = :now, updatedAt = :now",
            ConditionExpression=Attr("pk").exists(),
            ExpressionAttributeValues={":message": text, ":now": current},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
        if schedule_item:
            try:
                table.update_item(
                    Key=_schedule_key(user_id, schedule_item["id"]),
                    UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
                    ConditionExpression=Attr("pk").exists(),
                    ExpressionAttributeValues={":now": current, ":status": "error"},
                )
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                pass
        raise ApiError(404, "Bot not found") from exc
    _queue_bot_turn(item, schedule_item)
    return {"turnId": turn_id, "status": item["status"].lower()}


def _queue_bot_turn(item: dict, schedule_item: dict | None = None) -> None:
    try:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(
                {
                    "type": "AGENT_REPLY",
                    "userId": item["userId"],
                    "botId": item["botId"],
                    "turnKey": item["sk"],
                }
            ),
        )
    except Exception:
        failed_at = _now()
        table.update_item(
            Key={"pk": item["pk"], "sk": item["sk"]},
            UpdateExpression="SET #status = :status, assistantText = :text, completedAt = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "ERROR",
                ":text": "I could not start that request. Please try again.",
                ":now": failed_at,
            },
        )
        if schedule_item:
            try:
                table.update_item(
                    Key=_schedule_key(item["userId"], schedule_item["id"]),
                    UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
                    ConditionExpression=Attr("pk").exists(),
                    ExpressionAttributeValues={":now": failed_at, ":status": "error"},
                )
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                pass
        raise


def _interrupt_bot_turn(
    user_id: str,
    bot_id: str,
    turn: dict,
    message: str,
    *,
    strict: bool,
) -> bool:
    if not is_in_flight(turn.get("status")):
        if strict:
            raise ApiError(409, "This response can no longer be stopped")
        return False
    cancelled_at = _now()
    try:
        table.update_item(
            Key={"pk": turn["pk"], "sk": turn["sk"]},
            UpdateExpression=(
                "SET #status = :cancelled, assistantText = :message, completedAt = :now "
                "REMOVE leaseOwner, leaseExpiresAt, backgroundResults, runtimeResult"
            ),
            ConditionExpression=(
                "#status = :pending OR #status = :running OR #status = :waiting OR "
                "#status = :needsInput OR #status = :awaiting"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "PENDING",
                ":running": "RUNNING",
                ":waiting": "WAITING",
                ":needsInput": "NEEDS_INPUT",
                ":awaiting": "AWAITING_APPROVAL",
                ":cancelled": "CANCELLED",
                ":message": message,
                ":now": cancelled_at,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        if strict:
            raise ApiError(409, "This response can no longer be stopped") from exc
        return False
    if turn.get("source") == "schedule":
        _update_cancelled_schedule(user_id, turn, cancelled_at)
    _stop_background_work(turn)
    if isinstance(turn.get("approvalRequest"), dict):
        s3.delete_object(Bucket=FILES_BUCKET_NAME,
                         Key=approval_snapshot_key("direct", user_id, turn["id"], bot_id))
    if turn.get("status") == "RUNNING" and AGENT_RUNTIME_ARN:
        try:
            agentcore.stop_runtime_session(
                agentRuntimeArn=AGENT_RUNTIME_ARN,
                qualifier=AGENT_RUNTIME_QUALIFIER,
                runtimeSessionId=direct_session_id(user_id, bot_id),
            )
        except agentcore.exceptions.ResourceNotFoundException:
            pass
        except Exception:
            logger.exception("Could not stop the interrupted turn %s", turn.get("id"))
    return True


def _steer_active_turns(user_id: str, bot_id: str, turns: list[dict]) -> list[str]:
    steered = []
    for turn in reversed(turns):
        if _interrupt_bot_turn(
            user_id, bot_id, turn, "Steered by you.", strict=False
        ) and isinstance(turn.get("id"), str):
            steered.append(turn["id"])
    return steered


def _send_message(user_id: str, bot_id: str, value: dict) -> dict:
    _get_bot(user_id, bot_id)
    email_context = (
        inbox_message(user_id, bot_id, value.get("inboxMessageId"))
        if value.get("inboxMessageId") is not None
        else None
    )
    raw_text = value.get("text", "")
    if not isinstance(raw_text, str) or raw_text.strip():
        _validate_string(raw_text, "text", MESSAGE_MAX_LENGTH)
    attachments = _resolve_attachments(user_id, value.get("attachmentIds"))
    attachments.extend(
        _resolve_workspace_files(user_id, "bot", bot_id, value.get("workspaceFileIds"))
    )
    if len(attachments) > 5:
        raise ApiError(400, "Attach up to 5 files per message")
    if attachments and isinstance(raw_text, str) and not raw_text.strip():
        raw_text = "Please review the attached files."
    text = _validate_string(raw_text, "text", MESSAGE_MAX_LENGTH)
    lease_owner = _claim_send_lease(user_id, bot_id)
    try:
        from shared.browser_session_store import BrowserSessionError
        from shared.browser_sessions import ensure_browser_send_allowed

        try:
            ensure_browser_send_allowed(table, user_id, bot_id)
        except BrowserSessionError as exc:
            raise ApiError(exc.status_code, exc.message, code=exc.code) from None
        steered_turn_ids = _steer_active_turns(
            user_id, bot_id, _partition_items(_turn_pk(user_id, bot_id))
        )
        result = _start_bot_turn(
            user_id,
            bot_id,
            text,
            attachments=attachments or None,
            email_context=email_context,
        )
        if email_context:
            try:
                table.update_item(
                    Key={"pk": email_context["pk"], "sk": email_context["sk"]},
                    UpdateExpression=(
                        "SET disposition = :manual, linkedTurnId = :turnId"
                    ),
                    ConditionExpression="attribute_exists(pk)",
                    ExpressionAttributeValues={
                        ":manual": "manual",
                        ":turnId": result["turnId"],
                    },
                )
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                pass
        if steered_turn_ids:
            result["steeredTurnIds"] = steered_turn_ids
        return result
    finally:
        _release_send_lease(user_id, bot_id, lease_owner)


def _get_turn(user_id: str, bot_id: str, turn_id: str) -> dict:
    turn_id = _validate_string(turn_id, "turnId", 64)
    turn = next(
        (
            item
            for item in _partition_items(_turn_pk(user_id, bot_id))
            if item.get("id") == turn_id
        ),
        None,
    )
    if not turn:
        raise ApiError(404, "Message not found")
    return turn


def _approve_bot_turn(
    user_id: str, bot_id: str, turn_id: str, always: bool = False
) -> dict:
    bot = _get_bot(user_id, bot_id)
    turn = _get_turn(user_id, bot_id, turn_id)
    approved_at = _now()
    proposal = turn.get("approvalRequest")
    if isinstance(proposal, dict):
        try:
            expires = datetime.fromisoformat(proposal["expiresAt"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(409, "This approval request is invalid") from exc
        if expires.tzinfo is None or expires <= datetime.now(UTC):
            raise ApiError(409, "This approval request expired")
        if not catalog.approval_tool_names(user_id, bot.get("toolIds", [])):
            raise ApiError(409, "The bot no longer has interactive tools")
        if turn.get("approvalGrantDigest") != approval_grant_digest(catalog, user_id, bot):
            raise ApiError(409, "The bot's tool grants changed after this proposal")
        decision = {key: proposal[key] for key in ("id", "digest", "toolUseId")}
        decision["executionKey"] = str(uuid.uuid4())
    else:
        # Legacy approval requests created before exact-action interception can
        # be restarted safely. They never grant a tool call.
        if always:
            raise ApiError(400, "Only a proposed tool call can be allowed permanently")
        decision = None
    if always:
        try:
            grant_enabled_interactive_tools(table, catalog, user_id, bot)
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise ApiError(409, "The bot changed before the tool grant could be saved") from exc
    try:
        table.update_item(
            Key={"pk": turn["pk"], "sk": turn["sk"]},
            UpdateExpression=(
                "SET #status = :pending, approvedAt = :now"
                + (", approvalDecision = :decision" if decision else "")
                + " REMOVE approvalTools, approvalToolIds, runtimeResult"
            ),
            ConditionExpression="#status = :awaiting" + (
                " AND approvalRequest = :proposal" if decision else
                " AND attribute_not_exists(approvalRequest)"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":awaiting": "AWAITING_APPROVAL",
                ":pending": "PENDING",
                ":now": approved_at,
                **({":decision": decision, ":proposal": proposal} if decision else {}),
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(409, "This approval request is no longer active") from exc
    queued_turn = {**turn, "status": "PENDING"}
    queued_turn.pop("approvalTools", None)
    queued_turn.pop("approvalToolIds", None)
    _queue_bot_turn(queued_turn)
    return {
        "turnId": turn["id"],
        "status": "pending",
        "alwaysAllowed": always,
    }


def _cancel_bot_turn(user_id: str, bot_id: str, turn_id: str) -> dict:
    _get_bot(user_id, bot_id)
    turn = _get_turn(user_id, bot_id, turn_id)
    if turn.get("status") == "CANCELLED":
        return {"cancelled": True}
    if turn.get("status") in {"COMPLETE", "ERROR"}:
        raise ApiError(409, "This response has already finished")
    _interrupt_bot_turn(user_id, bot_id, turn, "Stopped by you.", strict=True)
    return {"cancelled": True}


def _update_cancelled_schedule(user_id: str, turn: dict, cancelled_at: str) -> None:
    schedule_id = turn.get("scheduleId")
    if not isinstance(schedule_id, str):
        return
    try:
        table.update_item(
            Key=_schedule_key(user_id, schedule_id),
            UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
            ConditionExpression=Attr("pk").exists(),
            ExpressionAttributeValues={":now": cancelled_at, ":status": "error"},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def _run_schedule_now(user_id: str, bot_id: str, schedule_id: str) -> dict:
    schedule_item = _get_schedule(user_id, bot_id, schedule_id)
    _get_bot(user_id, bot_id)
    return _start_bot_turn(user_id, bot_id, schedule_item["prompt"], schedule_item)
