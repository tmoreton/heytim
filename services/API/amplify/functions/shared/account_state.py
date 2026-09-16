from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

INACTIVE_ACCOUNT_STATUSES = {"DELETING", "DELETED"}
TRANSACTION_SETTLEMENT_DELAYS_SECONDS = (0.5, 1.0, 2.0, 2.0)


class AccountInactiveError(RuntimeError):
    pass


class UserItemConflictError(RuntimeError):
    pass


def _client_error_code(error: ClientError) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return None
    details = response.get("Error")
    code = details.get("Code") if isinstance(details, dict) else None
    return code if isinstance(code, str) and code else None


def _transaction_error_is_retryable(error: BotoCoreError | ClientError) -> bool:
    if isinstance(error, BotoCoreError):
        return True
    code = _client_error_code(error)
    return code is None or code in {
        "InternalServerError",
        "ProvisionedThroughputExceededException",
        "RequestLimitExceeded",
        "RequestTimeout",
        "RequestTimeoutException",
        "ServiceUnavailable",
        "Throttling",
        "ThrottlingException",
        "TransactionInProgressException",
    }


def _transaction_token(
    user_id: str,
    item: dict,
    *,
    require_absent: bool,
    expected_secret_arn: str | None,
) -> str:
    payload = json.dumps(
        {
            "userId": user_id,
            "item": item,
            "requireAbsent": require_absent,
            "expectedSecretArn": expected_secret_arn,
        },
        default=repr,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _item_was_persisted(table: Any, item: dict) -> bool:
    current = table.get_item(
        Key={"pk": item["pk"], "sk": item["sk"]},
        ConsistentRead=True,
    ).get("Item")
    return current == item


def _raise_transaction_cancellation(
    table: Any,
    user_id: str,
    *,
    has_item_condition: bool,
    error: Exception,
) -> None:
    response = getattr(error, "response", {})
    reasons = response.get("CancellationReasons", [])
    account_check_failed = bool(
        reasons
        and isinstance(reasons[0], dict)
        and reasons[0].get("Code") == "ConditionalCheckFailed"
    )
    if account_check_failed or not account_accepts_writes(table, user_id):
        raise AccountInactiveError from error
    item_check_failed = bool(
        has_item_condition
        and len(reasons) > 1
        and isinstance(reasons[1], dict)
        and reasons[1].get("Code") == "ConditionalCheckFailed"
    )
    if item_check_failed:
        raise UserItemConflictError from error
    raise error


def account_accepts_writes(table: Any, user_id: str) -> bool:
    state = table.get_item(
        Key={"pk": f"USER#{user_id}", "sk": "STATE"},
        ConsistentRead=True,
    ).get("Item")
    if not state or "accountStatus" not in state:
        return True
    status = state.get("accountStatus")
    return isinstance(status, str) and status not in INACTIVE_ACCOUNT_STATUSES


def put_user_item_while_account_active(
    table: Any,
    user_id: str,
    item: dict,
    *,
    require_absent: bool = False,
    expected_secret_arn: str | None = None,
) -> None:
    if require_absent and expected_secret_arn is not None:
        raise ValueError("A conditional user write cannot have two expectations")
    put = {
        "TableName": table.name,
        "Item": item,
    }
    has_item_condition = require_absent or expected_secret_arn is not None
    if require_absent:
        put["ConditionExpression"] = "attribute_not_exists(pk)"
    elif expected_secret_arn is not None:
        put.update(
            {
                "ConditionExpression": "#secret = :expectedSecret",
                "ExpressionAttributeNames": {"#secret": "secretArn"},
                "ExpressionAttributeValues": {
                    ":expectedSecret": expected_secret_arn
                },
            }
        )
    transact_items = [
        {
            "ConditionCheck": {
                "TableName": table.name,
                "Key": {"pk": f"USER#{user_id}", "sk": "STATE"},
                "ConditionExpression": (
                    "attribute_not_exists(#status) OR "
                    "(attribute_type(#status, :stringType) AND "
                    "#status <> :deleting AND #status <> :deleted)"
                ),
                "ExpressionAttributeNames": {"#status": "accountStatus"},
                "ExpressionAttributeValues": {
                    ":stringType": "S",
                    ":deleting": "DELETING",
                    ":deleted": "DELETED",
                },
            }
        },
        {"Put": put},
    ]
    token = _transaction_token(
        user_id,
        item,
        require_absent=require_absent,
        expected_secret_arn=expected_secret_arn,
    )
    client = table.meta.client
    delays = (0.0, *TRANSACTION_SETTLEMENT_DELAYS_SECONDS)
    last_error: BotoCoreError | ClientError | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            client.transact_write_items(
                ClientRequestToken=token,
                # The resource client's marshaller mutates nested values in place.
                # Every retry must start from the same native document request.
                TransactItems=deepcopy(transact_items),
            )
            return
        except client.exceptions.TransactionCanceledException as exc:
            _raise_transaction_cancellation(
                table,
                user_id,
                has_item_condition=has_item_condition,
                error=exc,
            )
        except (BotoCoreError, ClientError) as exc:
            last_error = exc
            try:
                if _item_was_persisted(table, item):
                    return
            except (BotoCoreError, ClientError):
                pass
            if not _transaction_error_is_retryable(exc):
                raise
    if last_error is None:  # pragma: no cover - delays always includes one attempt
        raise RuntimeError("Atomic user item transaction was not attempted")
    raise last_error
