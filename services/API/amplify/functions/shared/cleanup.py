from __future__ import annotations

from typing import Any

from shared.invites import revoke_invite_access
from shared.keys import group_pk, user_pk
from shared.storage import delete_object_versions
from shared.work_state import is_in_flight
from shared.workflows import github_subscription_key


def has_pending_work(items: list[dict], *, bot_id: str | None = None) -> bool:
    return any(
        is_in_flight(item.get("status"))
        and (bot_id is None or item.get("authorId") == bot_id)
        for item in items
    )


def group_member_ids(items: list[dict]) -> list[str]:
    return [
        user_id
        for item in items
        if item.get("entity") == "GROUP_USER"
        and isinstance((user_id := item.get("userId")), str)
    ]


def group_invite_records(items: list[dict]) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for item in items:
        if item.get("entity") != "GROUP_INVITE_POINTER":
            continue
        token = item.get("token")
        token_hash = item.get("tokenHash")
        if isinstance(token, str) and isinstance(token_hash, str):
            records.append((token, token_hash))
    return records


def share_token(item: dict) -> str | None:
    pk = item.get("pk")
    if not isinstance(pk, str) or "#" not in pk:
        return None
    token = pk.split("#", 1)[1]
    return token if token else None


def delete_share_record(
    table: Any, invite_access_table: Any, user_id: str, item: dict
) -> None:
    """Revoke the grant before deleting its denormalized share records."""
    token = share_token(item)
    if not token:
        return
    revoke_invite_access(invite_access_table, token)
    with table.batch_writer() as batch:
        batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
        batch.delete_item(Key={"pk": user_pk(user_id), "sk": f"SHARE#{token}"})
        batch.delete_item(Key={"pk": user_pk(user_id), "sk": f"INVITE#{token}"})
        if item.get("entity") == "GROUP_INVITE" and isinstance(
            item.get("groupId"), str
        ):
            batch.delete_item(
                Key={"pk": group_pk(item["groupId"]), "sk": f"INVITE#{token}"}
            )


def purge_group(
    table: Any,
    invite_access_table: Any,
    s3_client: Any,
    bucket_name: str | None,
    group_id: str,
    items: list[dict],
) -> None:
    """Remove a group after first revoking its authoritative invite grants."""
    members = group_member_ids(items)
    invites = group_invite_records(items)
    if invites:
        with invite_access_table.batch_writer() as batch:
            for _token, token_hash in invites:
                batch.delete_item(Key={"tokenHash": token_hash})
    if bucket_name:
        delete_object_versions(
            s3_client,
            bucket_name,
            f"groups/{group_id}/",
            resource_label="group artifact",
        )
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
            trigger = item.get("trigger", {})
            if item.get("entity") == "GROUP_ROUTINE" and trigger.get("eventType") == "github.issue.opened":
                batch.delete_item(Key=github_subscription_key(trigger, group_id, item["id"]))
        for member_id in members:
            batch.delete_item(Key={"pk": user_pk(member_id), "sk": f"GROUP#{group_id}"})
        for token, _token_hash in invites:
            batch.delete_item(Key={"pk": f"GROUP_INVITE#{token}", "sk": "META"})
        for invite in items:
            if (
                invite.get("entity") == "GROUP_INVITE_POINTER"
                and isinstance(invite.get("createdBy"), str)
                and isinstance(invite.get("token"), str)
            ):
                batch.delete_item(
                    Key={
                        "pk": user_pk(invite["createdBy"]),
                        "sk": f"INVITE#{invite['token']}",
                    }
                )
