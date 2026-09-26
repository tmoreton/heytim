"""Incremental Plaid transaction ingestion with an atomic cursor checkpoint."""
from __future__ import annotations

import gzip
import io
import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError
from shared.plaid_ledger import (
    MAX_TRANSACTIONS,
    ledger_prefix,
    merge_transactions,
    sync_key,
)
from shared.storage import delete_object_versions

from .support import FILES_BUCKET_NAME, catalog, s3, table

logger = logging.getLogger(__name__)
PLAID_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}
MAX_PAGES = 500
MAX_SNAPSHOT_BYTES = 32_000_000
MAX_LEDGER_BYTES = 64_000_000
SNAPSHOT_RETENTION_SECONDS = 2 * 24 * 60 * 60


class PlaidSyncError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _plaid_request(config: dict, token: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        PLAID_URLS[config["environment"]] + path,
        data=json.dumps({
            "client_id": config["clientId"],
            "secret": config["secret"],
            "access_token": token,
            **payload,
        }, separators=(",", ":")).encode(),
        headers={"accept": "application/json", "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:  # nosec B310
            value = json.loads(response.read(8_000_001))
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read(100_001))
            code = error.get("error_code") if isinstance(error, dict) else None
        except (ValueError, UnicodeDecodeError):
            code = None
        finally:
            exc.close()
        raise PlaidSyncError(code if isinstance(code, str) else "PLAID_HTTP_ERROR") from exc
    except (urllib.error.URLError, ValueError, UnicodeDecodeError) as exc:
        raise PlaidSyncError("PLAID_UNAVAILABLE") from exc
    if not isinstance(value, dict):
        raise PlaidSyncError("PLAID_INVALID_RESPONSE")
    return value


def _credential(connection: dict) -> tuple[dict, str]:
    runtime = connection.get("runtime") or {}
    environment = runtime.get("environment")
    if environment not in PLAID_URLS:
        raise PlaidSyncError("PLAID_CONFIGURATION_ERROR")
    try:
        app = catalog._secret_document(runtime.get("appSecretArn", ""))
        grant = catalog._secret_document(connection.get("secretArn", ""))
    except (BotoCoreError, ClientError) as exc:
        raise PlaidSyncError("PLAID_CREDENTIAL_UNAVAILABLE") from exc
    if not isinstance(app, dict) or not isinstance(grant, dict):
        raise PlaidSyncError("PLAID_CONFIGURATION_ERROR")
    if (
        not isinstance(app.get("clientId"), str)
        or not isinstance(app.get("secret"), str)
        or app.get("environment") != environment
        or not isinstance(grant.get("accessToken"), str)
        or grant.get("itemId") != connection.get("providerAccountId")
    ):
        raise PlaidSyncError("PLAID_CONFIGURATION_ERROR")
    return {**app, "environment": environment}, grant["accessToken"]


def _window(config: dict, token: str, starting_cursor: str) -> tuple[list, list, list, str]:
    """Return a complete change window; restart if Plaid invalidates pagination."""
    for attempt in range(3):
        cursor = starting_cursor
        added: list = []
        modified: list = []
        removed: list = []
        for _ in range(MAX_PAGES):
            try:
                page = _plaid_request(
                    config, token, "/transactions/sync",
                    {"cursor": cursor, "count": 500,
                     "options": {"include_personal_finance_category": True}},
                )
            except PlaidSyncError as exc:
                if exc.code == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION":
                    logger.info("Plaid sync pagination changed; restarting window")
                    break
                raise
            next_cursor = page.get("next_cursor")
            if not isinstance(next_cursor, str) or len(next_cursor) > 2048:
                raise PlaidSyncError("PLAID_INVALID_RESPONSE")
            for key, target in (("added", added), ("modified", modified), ("removed", removed)):
                values = page.get(key)
                if not isinstance(values, list):
                    raise PlaidSyncError("PLAID_INVALID_RESPONSE")
                target.extend(values)
            if len(added) + len(modified) + len(removed) > 2 * MAX_TRANSACTIONS:
                raise PlaidSyncError("PLAID_TOO_MANY_CHANGES")
            if page.get("has_more") is False:
                return added, modified, removed, next_cursor
            if page.get("has_more") is not True or next_cursor == cursor:
                raise PlaidSyncError("PLAID_INVALID_RESPONSE")
            cursor = next_cursor
        else:
            raise PlaidSyncError("PLAID_TOO_MANY_PAGES")
    raise PlaidSyncError("PLAID_PAGINATION_CHANGED")


def _load_snapshot(user_id: str, connection_id: str, state: dict) -> list[dict]:
    key = state.get("objectKey")
    if not key:
        return []
    if not isinstance(key, str) or not key.startswith(ledger_prefix(user_id, connection_id)):
        raise PlaidSyncError("PLAID_LEDGER_INVALID")
    response = s3.get_object(Bucket=FILES_BUCKET_NAME, Key=key)
    body = response["Body"]
    try:
        compressed = body.read(MAX_SNAPSHOT_BYTES + 1)
    finally:
        body.close()
    if len(compressed) > MAX_SNAPSHOT_BYTES:
        raise PlaidSyncError("PLAID_LEDGER_TOO_LARGE")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
            raw = archive.read(MAX_LEDGER_BYTES + 1)
        if len(raw) > MAX_LEDGER_BYTES:
            raise PlaidSyncError("PLAID_LEDGER_TOO_LARGE")
        data = json.loads(raw)
    except (OSError, EOFError, ValueError) as exc:
        raise PlaidSyncError("PLAID_LEDGER_INVALID") from exc
    if not isinstance(data, list):
        raise PlaidSyncError("PLAID_LEDGER_INVALID")
    return data


def _mark_error(key: dict, code: str) -> None:
    status = "needs_reconnect" if code in {
        "ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN", "ITEM_NOT_FOUND",
    } else "waiting_for_plaid" if code == "PRODUCT_NOT_READY" else "error"
    try:
        table.update_item(
            Key=key,
            UpdateExpression="SET #status = :status, errorCode = :code, lastCheckedAt = :now",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status, ":code": code, ":now": _utc_now(),
                ":deleted": "deleted",
            },
            ConditionExpression="attribute_exists(pk) AND #status <> :deleted",
        )
    except ClientError:
        logger.warning("Could not record Plaid sync failure")


def _prune_snapshots(user_id: str, connection_id: str, current_key: str) -> None:
    """Keep recent snapshots for in-flight readers; S3 lifecycle clears versions."""
    cutoff = datetime.now(timezone.utc).timestamp() - SNAPSHOT_RETENTION_SECONDS
    prefix = ledger_prefix(user_id, connection_id) + "snapshots/"
    paginator = s3.get_paginator("list_objects_v2")
    expired = []
    for page in paginator.paginate(Bucket=FILES_BUCKET_NAME, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key")
            modified = item.get("LastModified")
            if key != current_key and isinstance(key, str) and key.startswith(prefix) \
                    and isinstance(modified, datetime) and modified.timestamp() < cutoff:
                expired.append({"Key": key})
                if len(expired) == 1000:
                    s3.delete_objects(Bucket=FILES_BUCKET_NAME,
                                      Delete={"Objects": expired, "Quiet": True})
                    expired = []
    if expired:
        s3.delete_objects(Bucket=FILES_BUCKET_NAME,
                          Delete={"Objects": expired, "Quiet": True})


def delete_plaid_ledger(request: dict) -> None:
    user_id = request.get("userId")
    connection_id = request.get("connectionId")
    if not isinstance(user_id, str) or not user_id or not isinstance(connection_id, str):
        raise ValueError("Plaid ledger identity is invalid")
    if catalog._get_connection(user_id, connection_id):
        return
    delete_object_versions(
        s3, FILES_BUCKET_NAME, ledger_prefix(user_id, connection_id),
        resource_label="Plaid ledger",
    )


def process_plaid_sync(request: dict) -> None:
    user_id = request.get("userId")
    connection_id = request.get("connectionId")
    if not isinstance(user_id, str) or not user_id or not isinstance(connection_id, str):
        raise ValueError("Plaid sync identity is invalid")
    key = sync_key(user_id, connection_id)
    connection = catalog._get_connection(user_id, connection_id)
    if not connection or connection.get("provider") != "plaid":
        return  # A queued event can outlive a disconnect.
    state = table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
    if state.get("status") == "deleted":
        return
    starting_cursor = state.get("cursor", "")
    if not isinstance(starting_cursor, str):
        raise PlaidSyncError("PLAID_LEDGER_INVALID")
    try:
        if state:
            table.update_item(
                Key=key,
                UpdateExpression="SET #status = :syncing",
                ConditionExpression="revision = :revision AND #status <> :deleted",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":syncing": "syncing", ":revision": int(state["revision"]),
                    ":deleted": "deleted",
                },
            )
        config, token = _credential(connection)
        webhook_configured = state.get("webhookConfigured") is True
        webhook_url = os.environ.get("PLAID_WEBHOOK_URL", "")
        if webhook_url and not webhook_configured:
            _plaid_request(
                config, token, "/item/webhook/update", {"webhook": webhook_url}
            )
            webhook_configured = True
        added, modified, removed, next_cursor = _window(config, token, starting_cursor)
        now = _utc_now()
        revision = int(state.get("revision", 0)) + 1
        item = {
            **key, "entity": "PLAID_SYNC", "connectionId": connection_id,
            "userId": user_id, "cursor": next_cursor, "revision": revision,
            "status": "ready", "transactionCount": int(state.get("transactionCount", 0)),
            "lastCheckedAt": now, "lastSyncedAt": now,
            "historicalComplete": bool(state.get("historicalComplete", False))
                or request.get("historicalComplete") is True,
            "webhookConfigured": webhook_configured,
        }
        wrote_snapshot = bool(added or modified or removed or not state.get("objectKey"))
        if wrote_snapshot:
            merged = merge_transactions(
                _load_snapshot(user_id, connection_id, state), added, modified, removed
            )
            raw = json.dumps(merged, separators=(",", ":")).encode()
            if len(raw) > MAX_LEDGER_BYTES:
                raise PlaidSyncError("PLAID_LEDGER_TOO_LARGE")
            payload = gzip.compress(raw)
            if len(payload) > MAX_SNAPSHOT_BYTES:
                raise PlaidSyncError("PLAID_LEDGER_TOO_LARGE")
            object_key = ledger_prefix(user_id, connection_id) + f"snapshots/{uuid.uuid4().hex}.json.gz"
            s3.put_object(
                Bucket=FILES_BUCKET_NAME, Key=object_key, Body=payload,
                ContentType="application/json", ContentEncoding="gzip",
            )
            item["objectKey"] = object_key
            item["transactionCount"] = len(merged)
        else:
            item["objectKey"] = state["objectKey"]
        if not catalog._get_connection(user_id, connection_id):
            if item["objectKey"] != state.get("objectKey"):
                s3.delete_object(Bucket=FILES_BUCKET_NAME, Key=item["objectKey"])
            return
        condition = (
            "revision = :prior AND #status <> :deleted"
            if state else "attribute_not_exists(pk)"
        )
        expression = {":prior": int(state["revision"])} if state else None
        if expression is not None:
            expression[":deleted"] = "deleted"
        table.put_item(
            Item=item, ConditionExpression=condition,
            **({"ExpressionAttributeNames": {"#status": "status"}} if state else {}),
            **({"ExpressionAttributeValues": expression} if expression else {}),
        )
        if wrote_snapshot:
            try:
                _prune_snapshots(user_id, connection_id, item["objectKey"])
            except Exception:
                logger.exception("Could not prune old Plaid snapshots")
    except PlaidSyncError as exc:
        _mark_error(key, exc.code)
        if exc.code in {"ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN", "ITEM_NOT_FOUND", "PRODUCT_NOT_READY"}:
            return
        raise
    except (BotoCoreError, ClientError) as exc:
        if isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise
        _mark_error(key, "PLAID_STORAGE_UNAVAILABLE")
        raise
