"""Versioned, fail-closed permission for third-party AI processing.

The DynamoDB record authorizes new jobs. A small S3 fence is checked before
every model request, so revoking permission also stops a running agent's next
provider call. Both stores must agree on the same random epoch.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from .keys import user_state_key
from .time import utc_now_iso

CONSENT_VERSION = 1
MUTATION_LEASE_SECONDS = 30


class ConsentRequired(RuntimeError):
    pass


class ConsentBusy(RuntimeError):
    pass


def actor_id(user_id: str) -> str:
    return hashlib.sha256(f"user:{user_id}".encode()).hexdigest()


def fence_key(user_id: str) -> str:
    return f"users/{actor_id(user_id)}/ai-sharing-consent.json"


def _record(table, user_id: str) -> dict:
    return table.get_item(
        Key=user_state_key(user_id), ConsistentRead=True
    ).get("Item") or {}


def _valid_grant(state: dict) -> bool:
    value = state.get("aiSharingConsent")
    return bool(
        isinstance(value, dict)
        and value.get("version") == CONSENT_VERSION
        and value.get("granted") is True
        and isinstance(value.get("epoch"), str)
        and len(value["epoch"]) == 36
        and isinstance(value.get("grantedAt"), str)
        and not state.get("aiConsentMutationOwner")
        and state.get("accountStatus") not in {"DELETING", "DELETED"}
    )


def _fence(s3, bucket: str, user_id: str) -> dict:
    try:
        response = s3.get_object(Bucket=bucket, Key=fence_key(user_id))
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return {}
        raise
    with response["Body"] as body:
        raw = body.read(513)
    if len(raw) > 512:
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def active_grant(table, s3, bucket: str, user_id: str) -> dict:
    state = _record(table, user_id)
    if not _valid_grant(state):
        raise ConsentRequired("Allow AI processing before using a bot.")
    grant = state["aiSharingConsent"]
    fence = _fence(s3, bucket, user_id)
    if (
        fence.get("version") != CONSENT_VERSION
        or fence.get("granted") is not True
        or fence.get("epoch") != grant["epoch"]
    ):
        raise ConsentRequired("Allow AI processing before using a bot.")
    return {"actorId": actor_id(user_id), "epoch": grant["epoch"]}


def consent_status(table, s3, bucket: str, user_id: str) -> dict:
    try:
        active_grant(table, s3, bucket, user_id)
    except ConsentRequired:
        return {"version": CONSENT_VERSION, "granted": False}
    return {"version": CONSENT_VERSION, "granted": True}


def _write_fence(s3, bucket: str, user_id: str, epoch: str, granted: bool) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=fence_key(user_id),
        Body=json.dumps(
            {"version": CONSENT_VERSION, "epoch": epoch, "granted": granted},
            separators=(",", ":"),
        ).encode(),
        ContentType="application/json",
    )


def set_consent(table, s3, bucket: str, user_id: str, granted: bool) -> dict:
    """Serialize mutations; grant DDB then S3, revoke S3 then DDB.

    Either interrupted ordering denies model dispatch. A later explicit action
    can repair a partial mutation without inventing a user's permission.
    """
    owner = str(uuid.uuid4())
    now = int(time.time())
    try:
        table.update_item(
            Key=user_state_key(user_id),
            UpdateExpression=(
                "SET aiConsentMutationOwner = :owner, "
                "aiConsentMutationExpiresAt = :expires"
            ),
            ConditionExpression=(
                Attr("pk").exists()
                & (Attr("accountStatus").not_exists()
                   | ~Attr("accountStatus").is_in(["DELETING", "DELETED"]))
                & (Attr("aiConsentMutationOwner").not_exists()
                   | Attr("aiConsentMutationExpiresAt").lt(now))
            ),
            ExpressionAttributeValues={":owner": owner, ":expires": now + MUTATION_LEASE_SECONDS},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
        raise ConsentBusy("AI permission is being updated. Please try again.") from exc
    epoch = str(uuid.uuid4())
    try:
        if not granted:
            _write_fence(s3, bucket, user_id, epoch, False)
        table.update_item(
            Key=user_state_key(user_id),
            UpdateExpression="SET aiSharingConsent = :consent",
            ConditionExpression=Attr("aiConsentMutationOwner").eq(owner),
            ExpressionAttributeValues={
                ":consent": {
                    "version": CONSENT_VERSION,
                    "epoch": epoch,
                    "granted": granted,
                    "grantedAt" if granted else "revokedAt": utc_now_iso(),
                },
            },
        )
        if granted:
            _write_fence(s3, bucket, user_id, epoch, True)
    finally:
        try:
            table.update_item(
                Key=user_state_key(user_id),
                UpdateExpression="REMOVE aiConsentMutationOwner, aiConsentMutationExpiresAt",
                ConditionExpression=Attr("aiConsentMutationOwner").eq(owner),
            )
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            pass
    return consent_status(table, s3, bucket, user_id)


def group_subject_ids(table, group_id: str) -> set[str]:
    """Require identifiable current members and every historical human author.

    Room memory is owner-editable; decisions carry their creator. Unknown
    provenance denies the entire room run rather than silently omitting data.
    """
    subjects: set[str] = set()
    bot_owners: dict[str, str] = {}
    unresolved_bot_authors: set[str] = set()
    meta = None
    request = {
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": f"GROUP#{group_id}"},
        "ConsistentRead": True,
    }
    while True:
        page = table.query(**request)
        for item in page.get("Items", []):
            entity = item.get("entity")
            if item.get("sk") == "META":
                meta = item
            elif entity == "GROUP_USER":
                value = item.get("userId")
                if not isinstance(value, str) or not value:
                    raise ConsentRequired("A room member cannot be verified for AI processing.")
                subjects.add(value)
            elif entity == "GROUP_MESSAGE":
                author_type = item.get("authorType")
                if author_type == "user":
                    value = item.get("authorId")
                    if not isinstance(value, str) or not value:
                        raise ConsentRequired("A room message cannot be verified for AI processing.")
                    subjects.add(value)
                elif author_type == "bot":
                    value = item.get("botOwnerId")
                    if isinstance(value, str) and value:
                        subjects.add(value)
                    else:
                        bot_id = item.get("authorId")
                        if not isinstance(bot_id, str) or not bot_id:
                            raise ConsentRequired("A room bot message cannot be verified for AI processing.")
                        unresolved_bot_authors.add(bot_id)
                else:
                    raise ConsentRequired("A room message author cannot be verified for AI processing.")
            elif entity == "GROUP_DECISION":
                value = item.get("createdById")
                if not isinstance(value, str) or not value:
                    raise ConsentRequired("A room decision cannot be verified for AI processing.")
                subjects.add(value)
            elif entity == "GROUP_BOT":
                value = item.get("botOwnerId")
                if not isinstance(value, str) or not value:
                    raise ConsentRequired("A room bot owner cannot be verified for AI processing.")
                subjects.add(value)
                bot_owners[item.get("botId")] = value
        next_key = page.get("LastEvaluatedKey")
        if not next_key:
            break
        request["ExclusiveStartKey"] = next_key
    if not meta or not isinstance(meta.get("ownerId"), str) or not meta["ownerId"]:
        raise ConsentRequired("The room owner cannot be verified for AI processing.")
    subjects.add(meta["ownerId"])
    for bot_id in unresolved_bot_authors:
        if bot_id not in bot_owners:
            raise ConsentRequired("A former room bot owner cannot be verified for AI processing.")
        subjects.add(bot_owners[bot_id])
    return subjects
