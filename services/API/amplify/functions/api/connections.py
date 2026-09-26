from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError
from shared.catalog import CatalogError
from shared.connection_providers import (
    SUPPORTED_CONNECTION_PROVIDER_IDS,
    connection_provider,
)
from shared.plaid_ledger import item_mapping_key, public_sync_status, sync_key

from .external_oauth import (
    _begin_hubspot_authorization,
    _begin_jira_authorization,
    _begin_microsoft_authorization,
    _begin_microsoft_teams_authorization,
    _begin_notion_authorization,
    _begin_slack_authorization,
    _begin_zoom_authorization,
)
from .finance_connections import (
    _begin_plaid_authorization,
    _begin_quickbooks_authorization,
)
from .github_oauth import _begin_github_authorization
from .google_oauth import (
    _begin_gmail_authorization,
    _begin_google_workspace_authorization,
    _begin_youtube_authorization,
)
from .support import QUEUE_URL, ApiError, catalog, sqs, table
from .x_oauth import _begin_x_authorization

AuthorizationHandler = Callable[[str, dict], dict]
logger = logging.getLogger(__name__)
_AUTHORIZATION_HANDLERS: dict[str, AuthorizationHandler] = {
    "github": _begin_github_authorization,
    "gmail": _begin_gmail_authorization,
    "youtube": _begin_youtube_authorization,
    "google_workspace": _begin_google_workspace_authorization,
    "slack": _begin_slack_authorization,
    "microsoft": _begin_microsoft_authorization,
    "microsoft_teams": _begin_microsoft_teams_authorization,
    "notion": _begin_notion_authorization,
    "hubspot": _begin_hubspot_authorization,
    "jira": _begin_jira_authorization,
    "zoom": _begin_zoom_authorization,
    "quickbooks": _begin_quickbooks_authorization,
    "plaid": _begin_plaid_authorization,
    "x": _begin_x_authorization,
}
if frozenset(_AUTHORIZATION_HANDLERS) | {"home_assistant", "mcp_server"} != SUPPORTED_CONNECTION_PROVIDER_IDS:
    raise RuntimeError("Every visible connection provider must have an authorization adapter")


def _connections(user_id: str) -> dict:
    connections = catalog.list_connections(user_id)
    for connection in connections:
        if connection.get("provider") == "plaid":
            state = table.get_item(
                Key=sync_key(user_id, connection["id"]), ConsistentRead=True
            ).get("Item")
            connection["plaidSync"] = public_sync_status(state)
    return {"connections": connections}


def _plaid_sync_status(user_id: str, connection_id: str) -> dict:
    _owned_plaid_connection(user_id, connection_id)
    state = table.get_item(Key=sync_key(user_id, connection_id), ConsistentRead=True).get("Item")
    return public_sync_status(state)


def _owned_plaid_connection(user_id: str, connection_id: str) -> dict:
    try:
        connection = catalog._get_connection(user_id, connection_id)
    except CatalogError as exc:
        raise ApiError(404, "Plaid connection not found") from exc
    if not connection or connection.get("provider") != "plaid":
        raise ApiError(404, "Plaid connection not found")
    return connection


def _request_plaid_sync(user_id: str, connection_id: str) -> dict:
    connection = _owned_plaid_connection(user_id, connection_id)
    runtime = connection.get("runtime") or {}
    item_id = connection.get("providerAccountId")
    environment = runtime.get("environment")
    try:
        mapping_key = item_mapping_key(environment, item_id)
    except ValueError as exc:
        raise ApiError(409, "Plaid connection needs to be reconnected") from exc
    table.put_item(Item={
        **mapping_key, "entity": "PLAID_ITEM_MAPPING", "userId": user_id,
        "connectionId": connection_id,
    })
    key = sync_key(user_id, connection_id)
    current = table.get_item(Key=key, ConsistentRead=True).get("Item")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not current:
        try:
            table.put_item(
                Item={**key, "entity": "PLAID_SYNC", "connectionId": connection_id,
                      "userId": user_id, "cursor": "", "revision": 0,
                      "status": "queued", "transactionCount": 0, "requestedAt": now},
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            # A concurrent request can have created the row; the queued message is safe.
            current = table.get_item(Key=key, ConsistentRead=True).get("Item")
            if not current:
                raise
    else:
        table.update_item(
            Key=key,
            UpdateExpression="SET requestedAt = :now, #status = :queued",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":now": now, ":queued": "queued"},
        )
    try:
        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "type": "PLAID_SYNC", "userId": user_id,
                "connectionId": connection_id,
            }),
        )
    except (BotoCoreError, ClientError) as exc:
        table.update_item(
            Key=key,
            UpdateExpression="SET #status = :failed, errorCode = :code",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":failed": "error", ":code": "QUEUE_UNAVAILABLE"},
        )
        raise ApiError(503, "Plaid sync could not be queued. Please try again.") from exc
    return {"status": "queued", "requestedAt": now}


def _connect_home_assistant(user_id: str, value: dict) -> dict:
    # Compatibility endpoint for older clients. Count requests before retiring it;
    # new clients use generic MCP servers and existing grant IDs remain stable.
    logger.info("Legacy Home Assistant connection route used")
    try:
        return catalog.save_home_assistant_connection(
            user_id, value.get("instanceUrl"), value.get("accessToken")
        )
    except CatalogError as exc:
        raise ApiError(400, str(exc)) from exc


def _connect_mcp_server(user_id: str, value: dict) -> dict:
    try:
        return catalog.save_mcp_server_connection(
            user_id, value.get("name"), value.get("url"), value.get("accessToken")
        )
    except CatalogError as exc:
        raise ApiError(400, str(exc)) from exc


def _rename_mcp_server(user_id: str, connection_id: str, value: dict) -> dict:
    try:
        return catalog.rename_mcp_server_connection(
            user_id, connection_id, value.get("name")
        )
    except CatalogError as exc:
        status = 404 if str(exc) == "MCP server not found" else 400
        raise ApiError(status, str(exc)) from exc


def _begin_connection_authorization(
    user_id: str, provider_id: str, value: dict
) -> dict:
    provider = connection_provider(provider_id)
    if not provider:
        raise ApiError(
            404,
            "Connection provider not found",
            code="connection_provider_not_found",
        )
    handler = _AUTHORIZATION_HANDLERS.get(provider["id"])
    if handler:
        return handler(user_id, value)
    raise ApiError(
        501,
        "This connection provider is not available",
        code="connection_provider_unavailable",
    )


def _delete_connection(user_id: str, connection_id: str) -> dict:
    try:
        connection = catalog._get_connection(user_id, connection_id)
        result = catalog.delete_connection(user_id, connection_id)
        if connection and connection.get("provider") == "plaid":
            runtime = connection.get("runtime") or {}
            try:
                table.delete_item(Key=item_mapping_key(
                    runtime.get("environment"), connection.get("providerAccountId")
                ))
            except ValueError:
                logger.warning("Plaid Item mapping was invalid during disconnect")
            key = sync_key(user_id, connection_id)
            current = table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
            table.put_item(Item={
                **key, "entity": "PLAID_SYNC", "connectionId": connection_id,
                "userId": user_id, "status": "deleted",
                "revision": int(current.get("revision", 0)) + 1,
            })
            sqs.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=json.dumps({
                    "type": "PLAID_LEDGER_DELETE", "userId": user_id,
                    "connectionId": connection_id,
                }),
            )
        return result
    except CatalogError as exc:
        status = 409 if "before deleting" in str(exc) else 404
        raise ApiError(status, str(exc)) from exc
