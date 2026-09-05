from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Attr
from shared.memory_identity import direct_session_id, memory_actor_id, scoped_session_id

from .groups import _purge_group
from .memories import _delete_user_memory
from .schedules import _delete_remote_schedule
from .support import (
    AGENT_RUNTIME_ARN,
    AGENT_RUNTIME_QUALIFIER,
    FILES_BUCKET_NAME,
    QUEUE_URL,
    USER_POOL_ID,
    _delete_share_record,
    _group_pk,
    _now,
    _owned_share_records,
    _partition_items,
    _push_owner_key,
    _scan_items,
    _user_pk,
    _user_state_key,
    agentcore,
    catalog,
    cognito,
    invite_access_table,
    s3,
    sqs,
    table,
)


def _remove_owned_skills(user_id: str, user_items: list[dict]) -> int:
    owned_skill_ids = {
        item["id"]
        for item in user_items
        if item.get("entity") == "USER_SKILL"
        and item.get("source") == "user"
        and item.get("ownerId") == user_id
        and item.get("relationship") == "owner"
        and isinstance(item.get("id"), str)
    }
    for skill_id in owned_skill_ids:
        listings = _scan_items(
            Attr("entity").eq("USER_SKILL") & Attr("id").eq(skill_id)
        )
        bots = _scan_items(
            Attr("entity").eq("BOT") & Attr("skillIds").contains(skill_id)
        )
        versions = _partition_items(f"SKILL#{skill_id}")
        with table.batch_writer() as batch:
            for bot in bots:
                skill_ids = [
                    value for value in bot.get("skillIds", []) if value != skill_id
                ]
                skill_versions = dict(bot.get("skillVersions", {}))
                skill_versions.pop(skill_id, None)
                batch.put_item(
                    Item={
                        **bot,
                        "skillIds": skill_ids,
                        "skillVersions": skill_versions,
                        "updatedAt": _now(),
                    }
                )
            for listing in listings:
                batch.delete_item(Key={"pk": listing["pk"], "sk": listing["sk"]})
            for version in versions:
                batch.delete_item(Key={"pk": version["pk"], "sk": version["sk"]})
    return len(owned_skill_ids)


def _remove_invite_access_for_user(user_id: str) -> None:
    request: dict[str, Any] = {"FilterExpression": Attr("createdBy").eq(user_id)}
    while True:
        response = invite_access_table.scan(**request)
        with invite_access_table.batch_writer() as batch:
            for item in response.get("Items", []):
                token_hash = item.get("tokenHash")
                if isinstance(token_hash, str):
                    batch.delete_item(Key={"tokenHash": token_hash})
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return
        request["ExclusiveStartKey"] = last_key


def _owned_agent_session_ids(
    user_id: str, user_items: list[dict], group_items: dict[str, list[dict]]
) -> set[str]:
    session_ids = {
        direct_session_id(user_id, item["id"])
        for item in user_items
        if item.get("entity") == "BOT" and isinstance(item.get("id"), str)
    }
    for group_id, items in group_items.items():
        for item in items:
            bot_id = item.get("botId")
            if (
                item.get("entity") == "GROUP_BOT"
                and item.get("botOwnerId") == user_id
                and isinstance(bot_id, str)
            ):
                session_ids.add(scoped_session_id(f"group:{group_id}:bot:{bot_id}"))
    return session_ids


def _stop_runtime_sessions(session_ids: set[str]) -> None:
    if not AGENT_RUNTIME_ARN:
        return
    for session_id in session_ids:
        try:
            agentcore.stop_runtime_session(
                agentRuntimeArn=AGENT_RUNTIME_ARN,
                qualifier=AGENT_RUNTIME_QUALIFIER,
                runtimeSessionId=session_id,
            )
        except agentcore.exceptions.ResourceNotFoundException:
            continue


def _ready_tool_sessions(
    operation: str, identifier_key: str, identifier: str
) -> list[dict]:
    items = []
    request = {identifier_key: identifier, "status": "READY", "maxResults": 100}
    while True:
        response = getattr(agentcore, operation)(**request)
        items.extend(response.get("items", []))
        next_token = response.get("nextToken")
        if not isinstance(next_token, str) or not next_token:
            return items
        request["nextToken"] = next_token


def _stop_tool_sessions(session_ids: set[str]) -> None:
    names = {f"frogbot-{session_id}" for session_id in session_ids}
    if not names:
        return
    for item in _ready_tool_sessions(
        "list_code_interpreter_sessions",
        "codeInterpreterIdentifier",
        "aws.codeinterpreter.v1",
    ):
        if item.get("name") in names and isinstance(item.get("sessionId"), str):
            agentcore.stop_code_interpreter_session(
                codeInterpreterIdentifier="aws.codeinterpreter.v1",
                sessionId=item["sessionId"],
            )
    for item in _ready_tool_sessions(
        "list_browser_sessions", "browserIdentifier", "aws.browser.v1"
    ):
        if item.get("name") in names and isinstance(item.get("sessionId"), str):
            agentcore.stop_browser_session(
                browserIdentifier="aws.browser.v1",
                sessionId=item["sessionId"],
            )


def _delete_user_files(user_id: str) -> int:
    if not FILES_BUCKET_NAME:
        return 0
    prefix = f"users/{memory_actor_id(user_id)}/"
    deleted = 0
    key_marker = None
    version_marker = None
    while True:
        request: dict[str, Any] = {
            "Bucket": FILES_BUCKET_NAME,
            "Prefix": prefix,
            "MaxKeys": 1000,
        }
        if key_marker:
            request["KeyMarker"] = key_marker
        if version_marker:
            request["VersionIdMarker"] = version_marker
        response = s3.list_object_versions(**request)
        versions = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for item in [
                *response.get("Versions", []),
                *response.get("DeleteMarkers", []),
            ]
            if isinstance(item.get("Key"), str)
            and isinstance(item.get("VersionId"), str)
        ]
        if versions:
            result = s3.delete_objects(
                Bucket=FILES_BUCKET_NAME,
                Delete={"Objects": versions, "Quiet": True},
            )
            errors = result.get("Errors", [])
            if errors:
                raise RuntimeError(
                    f"S3 did not delete {len(errors)} user file versions"
                )
            deleted += len(versions)
        if response.get("IsTruncated") is not True:
            return deleted
        key_marker = response.get("NextKeyMarker")
        version_marker = response.get("NextVersionIdMarker")
        if not isinstance(key_marker, str) or not key_marker:
            raise RuntimeError(
                "S3 file deletion pagination did not return a key marker"
            )


def _begin_account_deletion(user_id: str, username: str) -> dict:
    started_at = _now()
    table.update_item(
        Key=_user_state_key(user_id),
        UpdateExpression=(
            "SET entity = :entity, accountStatus = :status, "
            "deletionStartedAt = if_not_exists(deletionStartedAt, :now)"
        ),
        ExpressionAttributeValues={
            ":entity": "USER_STATE",
            ":status": "DELETING",
            ":now": started_at,
        },
    )
    try:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(
                {
                    "type": "DELETE_ACCOUNT",
                    "userId": user_id,
                    "username": username,
                }
            ),
        )
    except Exception:
        table.update_item(
            Key=_user_state_key(user_id),
            UpdateExpression="REMOVE accountStatus, deletionStartedAt",
        )
        raise
    return {"deletionStarted": True}


def _delete_account(user_id: str, username: str) -> dict:
    started_at = _now()
    table.update_item(
        Key=_user_state_key(user_id),
        UpdateExpression=(
            "SET entity = :entity, accountStatus = :status, "
            "deletionStartedAt = if_not_exists(deletionStartedAt, :now)"
        ),
        ExpressionAttributeValues={
            ":entity": "USER_STATE",
            ":status": "DELETING",
            ":now": started_at,
        },
    )

    user_items = _partition_items(_user_pk(user_id))
    group_ids = {
        item["groupId"]
        for item in user_items
        if item.get("entity") == "USER_GROUP" and isinstance(item.get("groupId"), str)
    }
    group_items_by_id = {
        group_id: _partition_items(_group_pk(group_id)) for group_id in group_ids
    }
    session_ids = _owned_agent_session_ids(user_id, user_items, group_items_by_id)
    _stop_runtime_sessions(session_ids)
    _stop_tool_sessions(session_ids)
    schedules = [item for item in user_items if item.get("entity") == "SCHEDULE"]
    for schedule_item in schedules:
        _delete_remote_schedule(schedule_item)

    for group_id in group_ids:
        group_items = group_items_by_id[group_id]
        meta = next(
            (item for item in group_items if item.get("entity") == "GROUP"), None
        )
        if meta and meta.get("ownerId") == user_id:
            _purge_group(group_id, group_items)
            continue
        with table.batch_writer() as batch:
            for group_item in group_items:
                authored_message = (
                    group_item.get("entity") == "GROUP_MESSAGE"
                    and group_item.get("authorType") == "user"
                    and group_item.get("authorId") == user_id
                )
                owned_bot_data = group_item.get("botOwnerId") == user_id
                if authored_message or owned_bot_data:
                    batch.delete_item(
                        Key={"pk": group_item["pk"], "sk": group_item["sk"]}
                    )
            batch.delete_item(Key={"pk": _group_pk(group_id), "sk": f"USER#{user_id}"})
            batch.delete_item(Key={"pk": _user_pk(user_id), "sk": f"GROUP#{group_id}"})

    for share in _owned_share_records(user_id):
        _delete_share_record(user_id, share)
    _remove_invite_access_for_user(user_id)
    deleted_skills = _remove_owned_skills(user_id, user_items)
    deleted_connections = catalog.delete_connection_secrets(user_items)
    deleted_memory = _delete_user_memory(user_id)
    deleted_files = _delete_user_files(user_id)

    push_items = [item for item in user_items if item.get("entity") == "PUSH_TOKEN"]
    chat_items = _scan_items(Attr("pk").begins_with(f"CHAT#{user_id}#"))
    with table.batch_writer() as batch:
        for push_item in push_items:
            token_id = push_item.get("tokenId")
            if isinstance(token_id, str):
                batch.delete_item(Key=_push_owner_key(token_id))
        for chat_item in chat_items:
            batch.delete_item(Key={"pk": chat_item["pk"], "sk": chat_item["sk"]})
        for item in user_items:
            if item.get("sk") != "STATE":
                batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})

    try:
        cognito.admin_user_global_sign_out(UserPoolId=USER_POOL_ID, Username=username)
        cognito.admin_delete_user(UserPoolId=USER_POOL_ID, Username=username)
    except cognito.exceptions.UserNotFoundException:
        pass

    deleted_at = _now()
    table.put_item(
        Item={
            **_user_state_key(user_id),
            "entity": "USER_STATE",
            "accountStatus": "DELETED",
            "deletedAt": deleted_at,
            # API Gateway JWTs remain valid briefly after Cognito deletion. This
            # non-personal tombstone prevents a still-valid token recreating data.
            "expiresAt": int(datetime.now(UTC).timestamp()) + 2 * 24 * 60 * 60,
        }
    )
    return {
        "deleted": True,
        "deletedSkills": deleted_skills,
        "deletedConnections": deleted_connections,
        "deletedMemory": deleted_memory,
        "deletedFileVersions": deleted_files,
    }
