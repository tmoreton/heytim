from __future__ import annotations

from boto3.dynamodb.conditions import Attr
from shared.schedules import occurrence_time, scheduled_turn_id

from .direct_job import _process_agent_reply
from .notifications import _update_schedule_result
from .support import _bot_key, _schedule_key, _turn_pk, table


def _request_string(request: dict, key: str, maximum: int = 128) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"Scheduled job has an invalid {key}")
    return value


def _process_scheduled_agent_reply(record: dict, request: dict) -> None:
    user_id = _request_string(request, "userId")
    bot_id = _request_string(request, "botId")
    schedule_id = _request_string(request, "scheduleId")
    execution_id = _request_string(request, "executionId")
    created_at = occurrence_time(request.get("scheduledTime"))
    turn_id = scheduled_turn_id(schedule_id, execution_id)
    turn_key = {
        "pk": _turn_pk(user_id, bot_id),
        "sk": f"TURN#{created_at}#{turn_id}",
    }
    existing_turn = table.get_item(Key=turn_key, ConsistentRead=True).get("Item")
    if existing_turn:
        _process_agent_reply(
            record,
            {"userId": user_id, "botId": bot_id, "turnKey": turn_key["sk"]},
        )
        return

    schedule_item = table.get_item(
        Key=_schedule_key(user_id, schedule_id), ConsistentRead=True
    ).get("Item")
    if (
        not schedule_item
        or schedule_item.get("botId") != bot_id
        or not schedule_item.get("enabled", True)
    ):
        return

    turn = {
        **turn_key,
        "entity": "TURN",
        "id": turn_id,
        "botId": bot_id,
        "userId": user_id,
        "userText": schedule_item["prompt"],
        "createdAt": created_at,
        "status": "PENDING",
        "source": "schedule",
        "scheduleId": schedule_id,
        "scheduleName": schedule_item["name"],
        "schedulerExecutionId": execution_id,
    }
    created = False
    try:
        table.put_item(Item=turn, ConditionExpression=Attr("pk").not_exists())
        created = True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass

    if created:
        try:
            table.update_item(
                Key=_schedule_key(user_id, schedule_id),
                UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
                ConditionExpression=Attr("pk").exists(),
                ExpressionAttributeValues={
                    ":now": created_at,
                    ":status": "pending",
                },
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            table.delete_item(Key=turn_key)
            return
        try:
            table.update_item(
                Key=_bot_key(user_id, bot_id),
                UpdateExpression="SET lastMessage = :message, lastMessageAt = :now, updatedAt = :now",
                ConditionExpression=Attr("pk").exists(),
                ExpressionAttributeValues={
                    ":message": schedule_item["prompt"][:280],
                    ":now": created_at,
                },
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            table.delete_item(Key=turn_key)
            _update_schedule_result(turn, "error", created_at)
            return

    _process_agent_reply(
        record,
        {"userId": user_id, "botId": bot_id, "turnKey": turn_key["sk"]},
    )
