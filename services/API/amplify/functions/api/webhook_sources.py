"""User-managed webhook sources. Credentials are revealed only on create/rotate."""
from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from contextvars import ContextVar
from functools import wraps

from shared.account_state import (
    UserItemConflictError,
    UserItemGuardFailedError,
    put_user_item_while_account_active,
)
from shared.webhooks import (
    MAX_SOURCES,
    WebhookError,
    eligible_bots,
    get_source,
    owner_key,
    partition,
    public_source,
    retire_secret,
    source_key,
    validate_text_path,
)

from .support import _now, catalog, table

_mutation_owner = ContextVar("webhook_mutation_owner", default="")
logger = logging.getLogger(__name__)


def _mutation_guard(user_id: str) -> dict:
    return {"Key": {"pk": f"USER#{user_id}", "sk": "WEBHOOK_SOURCE_MUTATION"},
            "ConditionExpression": "mutationOwner = :owner AND mutationLeaseExpiresAt > :now",
            "ExpressionAttributeValues": {":owner": _mutation_owner.get(), ":now": int(time.time())}}


def _source_mutation(function):
    @wraps(function)
    def serialized(user_id, *args, **kwargs):
        owner = str(uuid.uuid4())
        key = {"pk": f"USER#{user_id}", "sk": "WEBHOOK_SOURCE_MUTATION"}
        now = int(time.time())
        try:
            table.update_item(Key=key,
                UpdateExpression="SET mutationOwner = :owner, mutationLeaseExpiresAt = :expires, expiresAt = :ttl",
                ConditionExpression="attribute_not_exists(mutationLeaseExpiresAt) OR mutationLeaseExpiresAt <= :now",
                ExpressionAttributeValues={":owner": owner, ":expires": now + 60, ":now": now, ":ttl": now + 120})
        except table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise WebhookError(409, "Another webhook source change is in progress; retry shortly") from exc
        token = _mutation_owner.set(owner)
        try:
            return function(user_id, *args, **kwargs)
        except (UserItemConflictError, UserItemGuardFailedError) as exc:
            raise WebhookError(409, "The webhook source changed; refresh and retry") from exc
        finally:
            _mutation_owner.reset(token)
            try:
                table.delete_item(Key=key, ConditionExpression="mutationOwner = :owner",
                                  ExpressionAttributeValues={":owner": owner})
            except Exception:  # noqa: BLE001 - TTL recovers this best-effort lease release; keep SDK details private.
                logger.warning("Webhook source mutation lease will expire automatically")
    return serialized


def _base_url(event: dict | None = None) -> str:
    configured = os.environ.get("WEBHOOK_API_BASE_URL", "")
    if configured:
        return configured
    # requestContext.domainName is set by API Gateway, not a caller-supplied Host.
    domain = ((event or {}).get("requestContext") or {}).get("domainName", "")
    return f"https://{domain}" if isinstance(domain, str) and domain else ""


def _values(user_id: str, value: dict, previous: dict | None = None) -> dict:
    previous = previous or {}
    if not isinstance(value, dict):
        raise WebhookError(400, "Webhook source must be an object")
    name = value.get("name", previous.get("name", "Webhook"))
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise WebhookError(400, "name must contain 1 to 100 characters")
    kind = value.get("kind", previous.get("kind", "generic"))
    mode = value.get("routingMode", previous.get("routingMode", "local"))
    authentication = value.get("authentication", previous.get("authentication", "either"))
    enabled = value.get("enabled", previous.get("enabled", True))
    allowed = value.get("allowedBotIds", previous.get("allowedBotIds", []))
    fallback = value.get("fallbackBotId", previous.get("fallbackBotId"))
    text_path = validate_text_path(value.get("textPath", previous.get("textPath")))
    if not isinstance(kind, str) or not isinstance(mode, str) or kind not in {"generic", "pebble"} or mode not in {"local", "fixed"}:
        raise WebhookError(400, "Unsupported source kind or routingMode")
    if not isinstance(authentication, str) or authentication not in {"hmac", "bearer", "either"} or not isinstance(enabled, bool):
        raise WebhookError(400, "Unsupported authentication or enabled value")
    if (not isinstance(allowed, list) or len(allowed) > 100
            or any(not isinstance(item, str) or not 1 <= len(item) <= 100 for item in allowed)
            or len(allowed) != len(set(allowed))):
        raise WebhookError(400, "allowedBotIds must be a unique list of bot identifiers")
    # Revocation must remain possible after a previously permitted bot is deleted.
    # Only an existing-source disable with no configuration fields gets this path.
    disable_only = bool(previous) and set(value) == {"enabled"} and enabled is False
    if not disable_only:
        owned = {bot["id"] for bot in eligible_bots(table, user_id, {"allowedBotIds": []})}
        if not set(allowed).issubset(owned):
            raise WebhookError(400, "Every allowed bot must belong to this account")
        if fallback is not None and (not isinstance(fallback, str) or fallback not in owned or (allowed and fallback not in allowed)):
            raise WebhookError(400, "fallbackBotId must be an eligible bot")
    if mode == "fixed" and not fallback:
        raise WebhookError(400, "Fixed routing requires fallbackBotId")
    return {"name": name.strip(), "kind": kind, "routingMode": mode,
            "authentication": authentication, "enabled": enabled,
            "allowedBotIds": allowed, **({"fallbackBotId": fallback} if fallback else {}),
            **({"textPath": text_path} if text_path else {})}


def list_sources(user_id: str, event: dict) -> dict:
    return {"sources": [public_source(item, _base_url(event))
                        for item in partition(table, user_id, "WEBHOOK_SOURCE#")]}


@_source_mutation
def save_source(user_id: str, value: dict, event: dict, source_id: str | None = None) -> dict:
    old = get_source(table, user_id, source_id) if source_id else None
    if not old and len(partition(table, user_id, "WEBHOOK_SOURCE#")) >= MAX_SOURCES:
        raise WebhookError(409, "This account has reached its webhook source limit")
    fields = _values(user_id, value, old)
    source_id = source_id or str(uuid.uuid4())
    now = _now()
    item = {**(old or {}), **source_key(user_id, source_id), **fields,
            "entity": "WEBHOOK_SOURCE", "id": source_id, "userId": user_id,
            "createdAt": (old or {}).get("createdAt", now), "updatedAt": now,
            "mutationRevision": int((old or {}).get("mutationRevision", 0)) + 1}
    if "fallbackBotId" not in fields:
        item.pop("fallbackBotId", None)
    if "textPath" not in fields:
        item.pop("textPath", None)
    credential = signing_secret = None
    if not old:
        credential, signing_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        import json
        item["secretArn"] = catalog._create_secret(
            user_id, f"webhook-{source_id}-{uuid.uuid4().hex[:8]}",
            json.dumps({"credential": credential, "signingSecret": signing_secret}))
        item["credentialVersion"] = 1
    try:
        put_user_item_while_account_active(table, user_id, item, require_absent=not bool(old),
            expected_secret_arn=old.get("secretArn") if old else None,
            expected_item_fields={"mutationRevision": old["mutationRevision"]} if old else None,
            required_item_condition=_mutation_guard(user_id),
            additional_put_items=[{**owner_key(source_id), "entity": "WEBHOOK_SOURCE_OWNER", "userId": user_id}] if not old else None)
    except Exception:
        if not old:
            retire_secret(catalog, item["secretArn"])
            table.delete_item(Key=source_key(user_id, source_id))
        raise
    result = {"source": public_source(item, _base_url(event))}
    if credential:
        result.update(credential=credential, signingSecret=signing_secret)
    return result


@_source_mutation
def rotate_source(user_id: str, source_id: str, event: dict) -> dict:
    import json
    old = get_source(table, user_id, source_id)
    credential, signing_secret = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    arn = catalog._create_secret(user_id, f"webhook-{source_id}-{uuid.uuid4().hex[:8]}",
                                 json.dumps({"credential": credential, "signingSecret": signing_secret}))
    retired = list(old.get("retiredSecretArns", [])) + [old["secretArn"]]
    item = {**old, "secretArn": arn, "retiredSecretArns": retired,
            "credentialVersion": int(old.get("credentialVersion", 1)) + 1, "updatedAt": _now(),
            "mutationRevision": old["mutationRevision"] + 1}
    try:
        put_user_item_while_account_active(table, user_id, item, expected_secret_arn=old["secretArn"],
            expected_item_fields={"mutationRevision": old["mutationRevision"]}, required_item_condition=_mutation_guard(user_id))
    except Exception:
        retire_secret(catalog, arn)
        raise
    # The old credential is already fenced by the source version before deleting it.
    for old_arn in retired:
        try:
            retire_secret(catalog, old_arn)
        except Exception:  # noqa: BLE001 - account cleanup retries revocation; never log secret-bearing SDK details.
            logger.warning("Retired webhook credential deletion will be retried at account cleanup")
    return {"source": public_source(item, _base_url(event)),
            "credential": credential, "signingSecret": signing_secret}


@_source_mutation
def delete_source(user_id: str, source_id: str) -> dict:
    source = get_source(table, user_id, source_id)
    tombstone = {**source, "enabled": False, "updatedAt": _now(), "mutationRevision": source["mutationRevision"] + 1}
    put_user_item_while_account_active(table, user_id, tombstone,
        expected_item_fields={"mutationRevision": source["mutationRevision"]}, required_item_condition=_mutation_guard(user_id))
    table.delete_item(Key=owner_key(source_id))
    for arn in [source["secretArn"], *source.get("retiredSecretArns", [])]:
        retire_secret(catalog, arn)
    table.delete_item(Key=source_key(user_id, source_id))
    return {"deleted": True}
