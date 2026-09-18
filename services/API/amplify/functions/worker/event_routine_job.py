"""Idempotent first-party room decision event delivery."""
from __future__ import annotations

import json

from boto3.dynamodb.conditions import Key
from shared.group_chat import group_bots, plan_group_reply_round
from shared.keys import group_message_sk
from shared.schedules import scheduled_turn_id
from shared.workflows import (
    decision_routine_prompt,
    github_issue_routine_prompt,
    group_run_record,
    task_metadata,
)

from .group_job import _process_group_agent_round
from .scheduled_group_job import _put_once
from .scheduled_job import _request_string
from .support import (
    QUEUE_URL,
    _account_is_active,
    _bot_key,
    _group_pk,
    catalog,
    sqs,
    table,
)


def _decision(group_id: str, decision_id: str) -> dict | None:
    item = table.get_item(
        Key={"pk": _group_pk(group_id), "sk": f"DECISION#{decision_id}"},
        ConsistentRead=True,
    ).get("Item")
    if not item or item.get("entity") != "GROUP_DECISION":
        return None
    return item


def _event_source_is_safe(group_id: str, decision: dict) -> bool:
    source_id = decision.get("sourceMessageId")
    if not isinstance(source_id, str):
        return False
    source_key = decision.get("sourceMessageKey")
    if isinstance(source_key, str) and source_key.startswith("MESSAGE#"):
        source = table.get_item(
            Key={"pk": _group_pk(group_id), "sk": source_key}, ConsistentRead=True
        ).get("Item")
    else:
        # Decisions saved before source keys were stored need a one-time
        # paginated lookup. A missing source is never trusted.
        source = None
        query = {
            "KeyConditionExpression": Key("pk").eq(_group_pk(group_id)) & Key("sk").begins_with("MESSAGE#"),
            "ConsistentRead": True,
        }
        while source is None:
            result = table.query(**query)
            source = next((item for item in result.get("Items", []) if item.get("id") == source_id), None)
            cursor = result.get("LastEvaluatedKey")
            if source or not cursor:
                break
            query["ExclusiveStartKey"] = cursor
    return bool(source and source.get("source") != "event")


def _process_group_decision_event(request: dict) -> None:
    group_id = _request_string(request, "groupId")
    decision_id = _request_string(request, "decisionId")
    decision = _decision(group_id, decision_id)
    if not decision or not _event_source_is_safe(group_id, decision):
        return
    routines = table.query(
        KeyConditionExpression=Key("pk").eq(_group_pk(group_id)) & Key("sk").begins_with("ROUTINE#"),
        ConsistentRead=True,
    ).get("Items", [])
    for routine in routines:
        if routine.get("entity") != "GROUP_ROUTINE" or routine.get("enabled") is not True:
            continue
        if routine.get("trigger", {}).get("eventType") != "group.decision.saved":
            continue
        if str(routine.get("createdAt", "")) > str(decision.get("createdAt", "")):
            # A newly created routine must not replay old decisions.
            continue
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "type": "EVENT_GROUP_ROUND",
                "groupId": group_id,
                "routineId": routine["id"],
                "decisionId": decision_id,
            }),
        )


def _process_event_group_round(record: dict, request: dict) -> None:
    group_id = _request_string(request, "groupId")
    routine_id = _request_string(request, "routineId")
    github_issue = request.get("githubIssue")
    github_event = isinstance(github_issue, dict)
    occurrence_id = _request_string(request, "deliveryId" if github_event else "decisionId", 128)
    group_key = _group_pk(group_id)
    routine = table.get_item(
        Key={"pk": group_key, "sk": f"ROUTINE#{routine_id}"}, ConsistentRead=True
    ).get("Item")
    meta = table.get_item(Key={"pk": group_key, "sk": "META"}, ConsistentRead=True).get("Item")
    if not routine or not meta or routine.get("enabled") is not True:
        return
    owner_id = routine.get("ownerId")
    if (
        not isinstance(owner_id, str)
        or meta.get("ownerId") != owner_id
        or not _account_is_active(owner_id)
    ):
        return
    trigger = routine.get("trigger", {})
    if github_event:
        if trigger.get("eventType") != "github.issue.opened":
            return
        connection = catalog._get_connection(owner_id, trigger.get("connectionId", ""))
        if (
            not connection or connection.get("provider") != "github"
            or connection.get("connectionStatus") != "connected"
            or connection.get("providerAccountId") != github_issue.get("installationId")
            or connection.get("updatedAt") != trigger.get("connectionUpdatedAt")
            or trigger.get("installationId") != github_issue.get("installationId")
            or trigger.get("repositoryId") != github_issue.get("repositoryId")
            or trigger.get("repositoryName") != github_issue.get("repositoryName")
            or not any(repo.get("id") == github_issue.get("repositoryId") for repo in connection.get("repositories", []))
        ):
            return
        created_at = github_issue.get("createdAt")
        if not isinstance(created_at, str):
            return
        event_type = "github.issue.opened"
        prompt = github_issue_routine_prompt(routine["prompt"], github_issue)
    else:
        decision = _decision(group_id, occurrence_id)
        if not decision or trigger.get("eventType") != "group.decision.saved" or not _event_source_is_safe(group_id, decision):
            return
        created_at = decision["createdAt"]
        event_type = "group.decision.saved"
        prompt = decision_routine_prompt(routine["prompt"], decision["text"])
    if str(routine.get("createdAt", "")) > created_at:
        return
    member = table.get_item(
        Key={"pk": group_key, "sk": f"USER#{owner_id}"}, ConsistentRead=True
    ).get("Item")
    if not member:
        return
    message_id = scheduled_turn_id(routine_id, occurrence_id)
    message_key = {"pk": group_key, "sk": group_message_sk(created_at, message_id)}
    message = table.get_item(Key=message_key, ConsistentRead=True).get("Item")
    if not message:
        members = table.query(
            KeyConditionExpression=Key("pk").eq(group_key) & Key("sk").begins_with("BOT#"),
            ConsistentRead=True,
        ).get("Items", [])
        team = plan_group_reply_round(group_bots(members), True)
        if not team:
            return
        for member_bot in team:
            bot_owner = member_bot["botOwnerId"]
            bot = table.get_item(
                Key=_bot_key(bot_owner, member_bot["botId"]), ConsistentRead=True
            ).get("Item")
            if not bot or not _account_is_active(bot_owner) or (
                bot_owner != owner_id and catalog.approval_tool_names(bot_owner, bot.get("toolIds", []))
            ):
                raise ValueError("Event routine bot is unavailable or not owned by the approver")
        message = _put_once({
            **message_key,
            "entity": "GROUP_MESSAGE", "id": message_id,
            "authorType": "user", "authorId": owner_id,
            "authorName": member.get("name", "Group owner"),
            "billingUserId": owner_id, "text": prompt,
            "createdAt": created_at, "status": "COMPLETE",
            "source": "event", "routineId": routine_id,
            "eventType": event_type, "eventId": occurrence_id,
            "scheduledTeam": team,
        })
    team = message["scheduledTeam"]
    replies = []
    for position, member_bot in enumerate(team, 1):
        reply_id = scheduled_turn_id(message_id, str(position))
        reply = _put_once({
            "pk": group_key, "sk": group_message_sk(created_at, reply_id, position),
            "entity": "GROUP_MESSAGE", "id": reply_id, "authorType": "bot",
            "authorId": member_bot["botId"], "authorName": member_bot["name"],
            "authorColor": member_bot.get("color"),
            "botOwnerId": member_bot["botOwnerId"], "billingUserId": owner_id,
            "roundId": message_id, "roundPosition": position,
            "roundSize": len(team), "roundRole": member_bot["roundRole"],
            "coordinatorBotId": team[0]["botId"], "createdAt": created_at,
            **task_metadata(message_id, reply_id, member_bot["roundRole"]),
            "status": "PENDING" if position == 1 else "WAITING", "text": "",
            "source": "event", "routineId": routine_id, "eventId": occurrence_id,
            "userId": owner_id,
        })
        replies.append({
            "botId": reply["authorId"], "botOwnerId": reply["botOwnerId"],
            "replyKey": reply["sk"], "roundRole": reply["roundRole"],
            "coordinatorBotId": reply["coordinatorBotId"],
        })
    _put_once({
        **group_run_record(
            group_key, message_id, owner_id, "event", created_at,
            [scheduled_turn_id(message_id, str(position)) for position in range(1, len(team) + 1)],
            [entry["replyKey"] for entry in replies],
        ),
        "routineId": routine_id, "eventType": event_type,
        "occurrenceId": occurrence_id,
        "routineUpdatedAt": routine["updatedAt"],
    })
    _process_group_agent_round(record, {
        "type": "GROUP_AGENT_ROUND", "source": "event", "requestedBy": owner_id,
        "groupId": group_id, "messageId": message_id,
        "userText": message["text"], "replyTarget": "all", "replies": replies,
        "routineId": routine_id, "eventId": occurrence_id,
    })
