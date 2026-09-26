from __future__ import annotations

import uuid

from boto3.dynamodb.conditions import Attr
from shared.action_grants import effective_allowed_interactive_tool_ids
from shared.group_chat import group_bots, plan_group_reply_round
from shared.job_envelope import send_job
from shared.schedules import scheduler_name

from .attachments import _public_file
from .bots import _get_bot
from .groups import _require_group_member
from .schedules import (
    _create_remote_schedule,
    _delete_remote_schedule,
    _schedule_items,
    _schedule_values,
    _update_remote_schedule,
)
from .support import (
    QUEUE_URL,
    SCHEDULE_LIMIT,
    ApiError,
    _body,
    _group_pk,
    _now,
    _partition_items,
    _public_schedule,
    _response,
    _schedule_key,
    catalog,
    sqs,
    table,
)


def group_schedule_route(user_id: str, _display_name: str, method: str, path: str, params: dict, event: dict) -> dict:
    group_id, schedule_id = params.get("groupId", ""), params.get("scheduleId", "")
    if method == "GET":
        if path.endswith("/runs"):
            return _response(200, {"runs": _list_group_schedule_runs(user_id, group_id)})
        return _response(200, {"schedules": _list_group_schedules(user_id, group_id)})
    if method == "POST" and path.endswith("/run"):
        return _response(202, _run_group_schedule(user_id, group_id, schedule_id))
    if method == "DELETE":
        return _response(200, _delete_group_schedule(user_id, group_id, schedule_id))
    return _response(201 if method == "POST" else 200, _save_group_schedule(user_id, group_id, _body(event), schedule_id or None))


def _group_schedule_team(user_id: str, group_id: str, *, allow_approval: bool = False) -> list[dict]:
    _, items = _require_group_member(user_id, group_id, owner=True)
    try:
        team = plan_group_reply_round(group_bots(items), True)
    except ValueError as exc:
        raise ApiError(409, "Add Chief before scheduling the group team") from exc
    if not team:
        raise ApiError(409, "Add bots before scheduling this group")
    for member in team:
        bot = _get_bot(member["botOwnerId"], member["botId"])
        interactive = catalog.approval_tool_names(
            member["botOwnerId"], bot.get("toolIds", []))
        unapproved = catalog.unapproved_tools(
            member["botOwnerId"], bot.get("toolIds", []),
            effective_allowed_interactive_tool_ids(bot))
        if (interactive and member["botOwnerId"] != user_id) or (
            unapproved and not allow_approval
        ):
            raise ApiError(409, "Allow this bot's tools in a direct chat before scheduling it")
    return team


def _get_group_schedule(user_id: str, group_id: str, schedule_id: str) -> dict:
    _require_group_member(user_id, group_id, owner=True)
    item = table.get_item(Key=_schedule_key(user_id, schedule_id), ConsistentRead=True).get("Item")
    if not item or item.get("groupId") != group_id:
        raise ApiError(404, "Scheduled task not found")
    return item


def _list_group_schedules(user_id: str, group_id: str) -> list[dict]:
    _require_group_member(user_id, group_id, owner=True)
    return [_public_schedule(item) for item in _schedule_items(user_id) if item.get("groupId") == group_id]


def _save_group_schedule(user_id: str, group_id: str, value: dict, schedule_id: str | None = None) -> dict:
    team = _group_schedule_team(user_id, group_id)
    previous = _get_group_schedule(user_id, group_id, schedule_id) if schedule_id else None
    if not previous and len(_schedule_items(user_id)) >= SCHEDULE_LIMIT:
        raise ApiError(400, f"You can create up to {SCHEDULE_LIMIT} scheduled tasks")
    schedule_id = schedule_id or str(uuid.uuid4())
    current = _now()
    schedule_values = _schedule_values(value, previous)
    if schedule_values["deliveryMode"] != "app":
        raise ApiError(400, "Email delivery is available for bot schedules")
    item = {
        **(previous or {}), **_schedule_key(user_id, schedule_id),
        "entity": "SCHEDULE", "id": schedule_id, "userId": user_id,
        "groupId": group_id, "botId": team[0]["botId"],
        "schedulerName": scheduler_name(user_id, schedule_id),
        "createdAt": previous["createdAt"] if previous else current,
        "updatedAt": current, **schedule_values,
    }
    if item["frequency"] != "weekly":
        item.pop("dayOfWeek", None)
    if item["frequency"] != "monthly":
        item.pop("dayOfMonth", None)
    table.put_item(Item=item, ConditionExpression=Attr("pk").exists() if previous else Attr("pk").not_exists())
    try:
        (_update_remote_schedule if previous else _create_remote_schedule)(item)
    except Exception:
        if previous:
            table.put_item(Item=previous)
        else:
            table.delete_item(Key=_schedule_key(user_id, schedule_id))
        raise
    return _public_schedule(item)


def _delete_group_schedule(user_id: str, group_id: str, schedule_id: str) -> dict:
    item = _get_group_schedule(user_id, group_id, schedule_id)
    _delete_remote_schedule(item)
    table.delete_item(Key=_schedule_key(user_id, schedule_id))
    return {"deleted": True}


def _run_group_schedule(user_id: str, group_id: str, schedule_id: str) -> dict:
    _group_schedule_team(user_id, group_id)
    _get_group_schedule(user_id, group_id, schedule_id)
    execution_id = str(uuid.uuid4())
    send_job(sqs, QUEUE_URL, {
        "type": "SCHEDULED_GROUP_ROUND", "userId": user_id, "groupId": group_id,
        "scheduleId": schedule_id, "executionId": execution_id,
        "scheduledTime": _now(), "manual": True,
    })
    return {"executionId": execution_id}


def _list_group_schedule_runs(user_id: str, group_id: str) -> list[dict]:
    _require_group_member(user_id, group_id, owner=True)
    items = _partition_items(_group_pk(group_id), "MESSAGE#")
    prompts = {item["id"]: item for item in items if item.get("source") == "schedule" and item.get("authorType") == "user"}
    runs = []
    for item in items:
        parent = prompts.get(item.get("roundId"))
        if not parent or item.get("roundRole") not in {"synthesizer", "solo"}:
            continue
        replies = [reply for reply in items if reply.get("roundId") == parent["id"]]
        failed = any(reply.get("status") == "ERROR" for reply in replies)
        runs.append({
            "id": item["id"], "botId": item["authorId"], "groupId": group_id,
            "scheduleId": parent["scheduleId"], "scheduleName": parent["scheduleName"],
            "prompt": parent["text"], "createdAt": parent["createdAt"],
            "status": "error" if failed else ("complete" if item.get("status") == "COMPLETE" else "pending"),
            "output": item.get("text", ""), "activity": item.get("activity", []),
            "attachments": [_public_file(file) for file in item.get("artifacts", [])],
        })
    return sorted(runs, key=lambda item: item["createdAt"], reverse=True)[:50]
