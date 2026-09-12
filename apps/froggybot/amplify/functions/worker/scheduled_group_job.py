from __future__ import annotations

from datetime import datetime

from boto3.dynamodb.conditions import Attr, Key
from shared.group_chat import group_bots, plan_group_reply_round
from shared.keys import group_message_sk
from shared.schedules import occurrence_time, scheduled_turn_id

from .group_job import _process_group_agent_round
from .scheduled_job import _request_string
from .support import (
    _account_is_active,
    _bot_key,
    _group_pk,
    _schedule_key,
    catalog,
    table,
)


def _put_once(item: dict) -> dict:
    try:
        table.put_item(Item=item, ConditionExpression=Attr("pk").not_exists())
        return item
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        return table.get_item(Key={"pk": item["pk"], "sk": item["sk"]}, ConsistentRead=True)["Item"]


def _process_scheduled_group_round(record: dict, request: dict) -> None:
    user_id = _request_string(request, "userId")
    group_id = _request_string(request, "groupId")
    schedule_id = _request_string(request, "scheduleId")
    execution_id = _request_string(request, "executionId")
    # Stable scheduled time is required: falling back to now creates duplicate retries.
    scheduled_time = _request_string(request, "scheduledTime")
    parsed = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Scheduled time must include a timezone")
    created_at = occurrence_time(scheduled_time)
    message_id = scheduled_turn_id(schedule_id, execution_id)
    group_key = _group_pk(group_id)
    if not _account_is_active(user_id):
        return
    meta = table.get_item(Key={"pk": group_key, "sk": "META"}, ConsistentRead=True).get("Item")
    membership = table.get_item(Key={"pk": group_key, "sk": f"USER#{user_id}"}, ConsistentRead=True).get("Item")
    task = table.get_item(Key=_schedule_key(user_id, schedule_id), ConsistentRead=True).get("Item")
    if not meta or not membership or meta.get("ownerId") != user_id or not task or task.get("groupId") != group_id:
        return
    message_key = {"pk": group_key, "sk": group_message_sk(created_at, message_id)}
    message = table.get_item(Key=message_key, ConsistentRead=True).get("Item")
    if not message:
        if not task.get("enabled", True) and request.get("manual") is not True:
            return
        members = table.query(KeyConditionExpression=Key("pk").eq(group_key) & Key("sk").begins_with("BOT#"), ConsistentRead=True).get("Items", [])
        team = plan_group_reply_round(group_bots(members), True)
        if not team:
            raise ValueError("Scheduled group has no bots")
        for member in team:
            owner = member["botOwnerId"]
            bot = table.get_item(Key=_bot_key(owner, member["botId"]), ConsistentRead=True).get("Item")
            if not bot or not _account_is_active(owner) or catalog.approval_tool_names(owner, bot.get("toolIds", [])):
                raise ValueError("Scheduled group bot is unavailable or requires interactive approval")
        message = _put_once({
            **message_key, "entity": "GROUP_MESSAGE", "id": message_id,
            "authorType": "user", "authorId": user_id, "authorName": membership.get("name", "Group owner"),
            "billingUserId": user_id,
            "text": task["prompt"], "createdAt": created_at, "status": "COMPLETE",
            "source": "schedule", "scheduleId": schedule_id, "scheduleName": task["name"],
            "scheduledTeam": team,
        })
    team = message["scheduledTeam"]
    replies = []
    for position, member in enumerate(team, 1):
        reply_id = scheduled_turn_id(message_id, str(position))
        reply = _put_once({
            "pk": group_key, "sk": group_message_sk(created_at, reply_id, position),
            "entity": "GROUP_MESSAGE", "id": reply_id, "authorType": "bot",
            "authorId": member["botId"], "authorName": member["name"], "authorColor": member.get("color"),
            "botOwnerId": member["botOwnerId"], "billingUserId": user_id, "roundId": message_id,
            "roundPosition": position, "roundSize": len(team), "roundRole": member["roundRole"],
            "coordinatorBotId": team[0]["botId"], "createdAt": created_at,
            "status": "PENDING" if position == 1 else "WAITING", "text": "",
            "source": "schedule", "scheduleId": schedule_id, "scheduleName": message["scheduleName"], "userId": user_id,
        })
        replies.append({"botId": reply["authorId"], "botOwnerId": reply["botOwnerId"], "replyKey": reply["sk"], "roundRole": reply["roundRole"], "coordinatorBotId": reply["coordinatorBotId"]})
    if request.get("nextReplyIndex", 0) == 0:
        table.update_item(Key=_schedule_key(user_id, schedule_id),
            UpdateExpression="SET lastRunAt = :now, lastStatus = :status",
            ConditionExpression=Attr("pk").exists(),
            ExpressionAttributeValues={":now": created_at, ":status": "pending"})
    _process_group_agent_round(record, {
        "type": "GROUP_AGENT_ROUND", "requestedBy": user_id, "groupId": group_id,
        "messageId": message_id, "userText": message["text"], "replyTarget": "all", "replies": replies,
        "scheduleId": schedule_id, "scheduleName": message["scheduleName"],
    })
