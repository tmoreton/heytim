from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Attr
from shared.memory_identity import memory_actor_id
from shared.storage import (
    delete_object_version_identifiers,
    object_version_identifiers,
)

from .attachments import _public_file
from .support import (
    FILES_BUCKET_NAME,
    _file_key,
    _partition_items,
    _turn_pk,
    _user_pk,
    s3,
    table,
)


def _bot_prefix(user_id: str, bot_id: str) -> str:
    return f"users/{memory_actor_id(user_id)}/bots/{bot_id}/"


def _legacy_artifact_prefix(user_id: str) -> str:
    return f"users/{memory_actor_id(user_id)}/artifacts/"


def _belongs_to_bot(user_id: str, bot_id: str, object_key: Any) -> bool:
    if not isinstance(object_key, str):
        return False
    return object_key.startswith(
        (_bot_prefix(user_id, bot_id), _legacy_artifact_prefix(user_id))
    )


def _turn_documents(user_id: str, bot_id: str, turns: list[dict]) -> list[dict]:
    documents = []
    for turn in turns:
        artifacts = turn.get("artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if (
                isinstance(artifact, dict)
                and artifact.get("source") == "generated"
                and isinstance(artifact.get("id"), str)
                and _belongs_to_bot(user_id, bot_id, artifact.get("objectKey"))
            ):
                documents.append(artifact)
    return documents


def _associate_turn_documents(
    user_id: str, bot_id: str, turns: list[dict], files: list[dict]
) -> list[dict]:
    by_id = {
        item["id"]: item
        for item in files
        if item.get("entity") == "FILE"
        and item.get("source") == "generated"
        and item.get("status") == "READY"
        and isinstance(item.get("id"), str)
    }
    for artifact in _turn_documents(user_id, bot_id, turns):
        file_id = artifact["id"]
        stored = by_id.get(file_id)
        if stored and stored.get("botId") not in {None, bot_id}:
            continue
        if stored and stored.get("botId") is None:
            try:
                table.update_item(
                    Key=_file_key(user_id, file_id),
                    UpdateExpression="SET botId = :bot",
                    ConditionExpression=Attr("botId").not_exists(),
                    ExpressionAttributeValues={":bot": bot_id},
                )
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                continue
            stored = {**stored, "botId": bot_id}
        elif not stored:
            stored = {
                **artifact,
                **_file_key(user_id, file_id),
                "entity": "FILE",
                "status": "READY",
                "source": "generated",
                "botId": bot_id,
            }
            try:
                table.put_item(
                    Item=stored,
                    ConditionExpression=Attr("pk").not_exists(),
                )
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                continue
        by_id[file_id] = stored
    return list(by_id.values())


def _owned_documents(
    user_id: str, bot_id: str, turns: list[dict] | None = None
) -> list[dict]:
    files = _partition_items(_user_pk(user_id), "FILE#")
    turns = (
        turns
        if turns is not None
        else _partition_items(_turn_pk(user_id, bot_id), "TURN#")
    )
    files = _associate_turn_documents(user_id, bot_id, turns, files)
    return [
        item
        for item in files
        if item.get("botId") == bot_id
        and item.get("entity") == "FILE"
        and item.get("source") == "generated"
        and item.get("status") == "READY"
        and _belongs_to_bot(user_id, bot_id, item.get("objectKey"))
    ]


def _list_bot_documents(user_id: str, bot_id: str) -> list[dict]:
    documents = _owned_documents(user_id, bot_id)
    documents.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
    return [_public_file(item) for item in documents]


def _preserve_bot_documents(user_id: str, bot_id: str, turns: list[dict]) -> int:
    return len(_owned_documents(user_id, bot_id, turns))


def _version_identifiers(prefix: str, exact_keys: set[str] | None = None) -> list[dict]:
    return object_version_identifiers(
        s3,
        FILES_BUCKET_NAME,
        prefix,
        exact_keys=exact_keys,
    )


def _delete_versions(versions: list[dict]) -> int:
    return delete_object_version_identifiers(
        s3,
        FILES_BUCKET_NAME,
        versions,
        resource_label="bot document",
    )


def _delete_bot_documents(user_id: str, bot_id: str, turns: list[dict]) -> dict:
    documents = _owned_documents(user_id, bot_id, turns)
    legacy_keys = {
        item["objectKey"]
        for item in documents
        if isinstance(item.get("objectKey"), str)
        and not item["objectKey"].startswith(_bot_prefix(user_id, bot_id))
    }
    versions = _version_identifiers(_bot_prefix(user_id, bot_id))
    if legacy_keys:
        versions.extend(
            _version_identifiers(_legacy_artifact_prefix(user_id), legacy_keys)
        )
    deleted_versions = _delete_versions(versions)
    with table.batch_writer() as batch:
        for item in documents:
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    return {
        "deletedDocuments": len(documents),
        "deletedDocumentVersions": deleted_versions,
    }
