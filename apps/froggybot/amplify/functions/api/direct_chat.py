from __future__ import annotations

import json
import logging
import time
import uuid

from boto3.dynamodb.conditions import Attr
from shared.memory_identity import direct_session_id
from shared.work_state import is_in_flight

from .attachments import _resolve_attachments
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
    approval_tools: list[str] | None = None,
    approval_tool_ids: list[str] | None = None,
    attachments: list[dict] | None = None,
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
        "status": "AWAITING_APPROVAL" if approval_tools else "PENDING",
    }
    if approval_tools:
        item["approvalTools"] = approval_tools
        item["approvalToolIds"] = approval_tool_ids or []
    if attachments:
        item["attachments"] = attachments
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
    if not approval_tools:
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
    bot = _get_bot(user_id, bot_id)
    attachments = _resolve_attachments(user_id, value.get("attachmentIds"))
    raw_text = value.get("text", "")
    if attachments and isinstance(raw_text, str) and not raw_text.strip():
        raw_text = "Please review the attached files."
    text = _validate_string(raw_text, "text", 8_000)
    approval_tools = catalog.unapproved_tools(
        user_id,
        bot.get("toolIds", []),
        bot.get("alwaysAllowedToolIds", []),
    )
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
            approval_tools=[item["name"] for item in approval_tools] or None,
            approval_tool_ids=[item["id"] for item in approval_tools] or None,
            attachments=attachments or None,
        )
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
    always_allowed: list[str] | None = None
    if always:
        interactive_tools = catalog.approval_tools(user_id, bot.get("toolIds", []))
        interactive_ids = {item["id"] for item in interactive_tools}
        requested_ids = turn.get("approvalToolIds")
        if not isinstance(requested_ids, list) or not all(
            isinstance(tool_id, str) for tool_id in requested_ids
        ):
            legacy_names = {
                name for name in turn.get("approvalTools", []) if isinstance(name, str)
            }
            requested_ids = [
                item["id"] for item in interactive_tools if item["name"] in legacy_names
            ]
        raw_allowed_ids = bot.get("alwaysAllowedToolIds", [])
        allowed_ids = (
            set(raw_allowed_ids)
            if isinstance(raw_allowed_ids, list)
            and all(isinstance(tool_id, str) for tool_id in raw_allowed_ids)
            else set()
        )
        allowed_ids.update(set(requested_ids) & interactive_ids)
        always_allowed = [
            tool_id for tool_id in bot.get("toolIds", []) if tool_id in allowed_ids
        ]
    try:
        table.update_item(
            Key={"pk": turn["pk"], "sk": turn["sk"]},
            UpdateExpression=(
                "SET #status = :pending, approvedAt = :now "
                "REMOVE approvalTools, approvalToolIds"
            ),
            ConditionExpression="#status = :awaiting",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":awaiting": "AWAITING_APPROVAL",
                ":pending": "PENDING",
                ":now": approved_at,
            },
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ApiError(409, "This approval request is no longer active") from exc
    if always_allowed is not None:
        try:
            table.update_item(
                Key={"pk": _user_pk(user_id), "sk": _bot_sk(bot_id)},
                UpdateExpression="SET alwaysAllowedToolIds = :tools, updatedAt = :now",
                ConditionExpression=Attr("pk").exists(),
                ExpressionAttributeValues={
                    ":tools": always_allowed,
                    ":now": approved_at,
                },
            )
        except Exception:
            table.update_item(
                Key={"pk": turn["pk"], "sk": turn["sk"]},
                UpdateExpression=(
                    "SET #status = :awaiting, approvalTools = :approvalTools, "
                    "approvalToolIds = :approvalToolIds REMOVE approvedAt"
                ),
                ConditionExpression="#status = :pending",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":pending": "PENDING",
                    ":awaiting": "AWAITING_APPROVAL",
                    ":approvalTools": turn.get("approvalTools", []),
                    ":approvalToolIds": turn.get("approvalToolIds", []),
                },
            )
            raise
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
