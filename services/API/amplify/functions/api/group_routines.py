"""Owner-managed routines triggered by saved room decisions."""
from __future__ import annotations

import uuid

from boto3.dynamodb.conditions import Attr
from shared.workflows import (
    decision_routine_prompt,
    github_issue_routine_prompt,
    github_subscription_key,
)

from .groups import _require_group_member
from .support import (
    ApiError,
    _group_pk,
    _now,
    _partition_items,
    _validate_string,
    catalog,
    table,
)

MAX_GROUP_ROUTINES = 25
EVENT_TYPE = "group.decision.saved"
GITHUB_EVENT_TYPE = "github.issue.opened"


def _routine_key(group_id: str, routine_id: str) -> dict[str, str]:
    return {"pk": _group_pk(group_id), "sk": f"ROUTINE#{routine_id}"}


def _public_routine(item: dict) -> dict:
    return {key: item[key] for key in (
        "id", "name", "prompt", "trigger", "enabled", "createdAt", "updatedAt"
    ) if key in item}


def _list_group_routines(user_id: str, group_id: str) -> dict:
    _require_group_member(user_id, group_id)
    items = [
        item for item in _partition_items(_group_pk(group_id), "ROUTINE#")
        if item.get("entity") == "GROUP_ROUTINE"
    ]
    return {"routines": [_public_routine(item) for item in sorted(items, key=lambda item: item["createdAt"]) ]}


def _list_group_routine_runs(user_id: str, group_id: str) -> dict:
    _require_group_member(user_id, group_id)
    runs = [
        item for item in _partition_items(_group_pk(group_id), "RUN#")
        if item.get("entity") == "WORKFLOW_RUN" and item.get("source") == "event"
    ]
    return {"runs": [
        {key: item[key] for key in (
            "id", "routineId", "eventType", "occurrenceId", "status",
            "createdAt", "updatedAt", "completedAt", "taskIds",
        ) if key in item}
        for item in sorted(runs, key=lambda item: item["createdAt"], reverse=True)[:50]
    ]}


def _get_routine(user_id: str, group_id: str, routine_id: str) -> dict:
    _require_group_member(user_id, group_id, owner=True)
    routine_id = _validate_string(routine_id, "routineId", 64)
    item = table.get_item(Key=_routine_key(group_id, routine_id), ConsistentRead=True).get("Item")
    if not item or item.get("entity") != "GROUP_ROUTINE":
        raise ApiError(404, "Routine not found")
    return item


def _validated_trigger(user_id: str, value: object) -> dict:
    if not isinstance(value, dict):
        raise ApiError(400, "trigger must be an object")
    event_type = value.get("eventType")
    if event_type == EVENT_TYPE:
        return {"kind": "event", "eventType": EVENT_TYPE}
    if event_type != GITHUB_EVENT_TYPE:
        raise ApiError(400, "This routine trigger is not supported")
    connection_id = _validate_string(value.get("connectionId"), "connectionId", 64)
    repository_id = value.get("repositoryId")
    if type(repository_id) is not int or repository_id <= 0:
        raise ApiError(400, "repositoryId must be a positive number")
    connection = catalog._get_connection(user_id, connection_id)
    if not connection or connection.get("provider") != "github" or connection.get("connectionStatus") != "connected":
        raise ApiError(400, "Connect the selected GitHub account first")
    repository = next(
        (item for item in connection.get("repositories", []) if item.get("id") == repository_id),
        None,
    )
    installation_id = connection.get("providerAccountId")
    connection_updated_at = connection.get("updatedAt")
    if (not repository or not isinstance(installation_id, str)
        or not installation_id.isdecimal() or not isinstance(connection_updated_at, str)):
        raise ApiError(400, "The repository is not in the selected GitHub connection")
    return {
        "kind": "event", "eventType": GITHUB_EVENT_TYPE,
        "connectionId": connection_id, "installationId": installation_id,
        "connectionUpdatedAt": connection_updated_at,
        "repositoryId": repository_id, "repositoryName": repository["name"],
    }


def _routine_values(user_id: str, value: dict, previous: dict | None = None) -> dict:
    name = _validate_string(value.get("name", previous.get("name") if previous else None), "name", 80)
    prompt = _validate_string(value.get("prompt", previous.get("prompt") if previous else None), "prompt", 4_000)
    enabled = value.get("enabled", previous.get("enabled") if previous else False)
    if not isinstance(enabled, bool):
        raise ApiError(400, "enabled must be true or false")
    trigger = _validated_trigger(user_id, value.get("trigger", previous.get("trigger") if previous else {"eventType": EVENT_TYPE}))
    return {"name": name, "prompt": prompt, "enabled": enabled, "trigger": trigger}


def _save_group_routine(user_id: str, group_id: str, value: dict, routine_id: str | None = None) -> dict:
    _require_group_member(user_id, group_id, owner=True)
    from .group_schedules import _group_schedule_team

    _group_schedule_team(user_id, group_id, allow_approval=True)
    previous = _get_routine(user_id, group_id, routine_id) if routine_id else None
    values = _routine_values(user_id, value, previous)
    if values["enabled"] and values["trigger"]["eventType"] == GITHUB_EVENT_TYPE:
        from .github_webhook import _webhook_secret
        _webhook_secret()
    if previous is None and len(_partition_items(_group_pk(group_id), "ROUTINE#")) >= MAX_GROUP_ROUTINES:
        raise ApiError(409, "Room routine limit reached")
    now = _now()
    item = {
        **_routine_key(group_id, routine_id or str(uuid.uuid4())),
        "entity": "GROUP_ROUTINE",
        "routineVersion": 1,
        "id": routine_id or "",
        "groupId": group_id,
        "ownerId": user_id,
        "createdAt": previous["createdAt"] if previous else now,
        "updatedAt": now,
        **values,
    }
    item["id"] = item["sk"].split("#", 1)[1]
    old_trigger = previous.get("trigger", {}) if previous else {}
    new_trigger = item["trigger"]
    if new_trigger["eventType"] == GITHUB_EVENT_TYPE:
        # An orphan pointer is harmless: the worker rechecks the authoritative
        # routine and connection. Put it first so a saved routine is discoverable.
        table.put_item(Item={
            **github_subscription_key(new_trigger, group_id, item["id"]),
            "entity": "GITHUB_ROUTINE_SUBSCRIPTION",
            "groupId": group_id, "routineId": item["id"], "ownerId": user_id,
        })
    table.put_item(
        Item=item,
        ConditionExpression=Attr("pk").exists() if previous else Attr("pk").not_exists(),
    )
    if old_trigger.get("eventType") == GITHUB_EVENT_TYPE:
        old_key = github_subscription_key(old_trigger, group_id, item["id"])
        new_key = (
            github_subscription_key(new_trigger, group_id, item["id"])
            if new_trigger["eventType"] == GITHUB_EVENT_TYPE else None
        )
        if old_key != new_key:
            table.delete_item(Key=old_key)
    return _public_routine(item)


def _delete_group_routine(user_id: str, group_id: str, routine_id: str) -> dict:
    item = _get_routine(user_id, group_id, routine_id)
    table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    trigger = item.get("trigger", {})
    if trigger.get("eventType") == GITHUB_EVENT_TYPE:
        table.delete_item(Key=github_subscription_key(trigger, group_id, item["id"]))
    return {"deleted": True}


def _preview_group_routine(user_id: str, group_id: str, value: dict) -> dict:
    _require_group_member(user_id, group_id, owner=True)
    prompt = _validate_string(value.get("prompt"), "prompt", 4_000)
    trigger = _validated_trigger(user_id, value.get("trigger", {"eventType": EVENT_TYPE}))
    if trigger["eventType"] == GITHUB_EVENT_TYPE:
        sample = value.get("issue")
        if not isinstance(sample, dict):
            raise ApiError(400, "issue must be a sample issue object")
        number = sample.get("number")
        if type(number) is not int or number <= 0:
            raise ApiError(400, "Sample issue number is invalid")
        title = _validate_string(sample.get("title"), "title", 300)
        body = sample.get("body", "")
        if not isinstance(body, str) or len(body) > 4_000:
            raise ApiError(400, "Sample issue body is invalid")
        rendered = github_issue_routine_prompt(prompt, {
            "repositoryName": trigger["repositoryName"],
            "number": number, "title": title, "body": body,
        })
    else:
        decision_text = _validate_string(value.get("decisionText"), "decisionText", 4_000)
        rendered = decision_routine_prompt(prompt, decision_text)
    return {"eventType": trigger["eventType"], "prompt": rendered, "wouldRun": True}
