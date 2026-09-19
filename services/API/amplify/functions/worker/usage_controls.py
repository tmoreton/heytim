from __future__ import annotations

import hashlib
import os
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from shared.billing import entitlement_for_user

from .support import table

ADMISSION_RETENTION_DAYS = 400
RATE_COUNTER_RETENTION_SECONDS = 86_400
MAX_RUN_UNITS = 100
TRANSACTION_SETTLEMENT_DELAYS_SECONDS = (0.5, 1.0, 2.0, 2.0)
USAGE_CONTROL_PK = "SYSTEM#USAGE_CONTROL"
USAGE_CIRCUIT_KEY = {"pk": USAGE_CONTROL_PK, "sk": "CIRCUIT#PROVIDER"}


def _bounded_integer_environment(
    name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class UsageLimits:
    monthly_run_units: int
    user_window_run_units: int
    global_window_run_units: int
    window_seconds: int


USAGE_LIMITS = UsageLimits(
    monthly_run_units=_bounded_integer_environment(
        "HEYTIM_MONTHLY_RUN_UNIT_LIMIT", 1_000, 1, 1_000_000
    ),
    user_window_run_units=_bounded_integer_environment(
        "HEYTIM_USER_WINDOW_RUN_UNIT_LIMIT", 30, 1, 10_000
    ),
    global_window_run_units=_bounded_integer_environment(
        "HEYTIM_GLOBAL_WINDOW_RUN_UNIT_LIMIT", 300, 1, 100_000
    ),
    window_seconds=_bounded_integer_environment(
        "HEYTIM_USAGE_WINDOW_SECONDS", 60, 10, 3_600
    ),
)

@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    reason: str
    duplicate: bool = False
    quota_day: str | None = None

    @property
    def user_message(self) -> str:
        if self.reason == "account_inactive":
            return (
                "This request was stopped because the account that started it is "
                "no longer active."
            )
        if self.reason in {"monthly_limit", "user_rate_limit"}:
            return (
                "This request could not run because your account has reached its "
                "current usage limit. Please try again after the limit resets."
            )
        if self.reason == "provider_daily_limit":
            return (
                "YouTube research has reached HeyTim's shared daily capacity. "
                "Please try again after the provider limit resets."
            )
        return (
            "HeyTim is temporarily unavailable because this run could not be "
            "safely authorized. Please try again later."
        )


class UsageControlUnavailable(RuntimeError):
    """Raised when durable admission cannot be verified safely."""


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
    # Missing error metadata is conservatively treated as an ambiguous transport
    # result. Known authorization and validation failures do not spend the bounded
    # settlement window retrying a request that cannot succeed.
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


def _transact_write_with_settlement(
    client: Any,
    transaction: list[dict[str, Any]],
    client_request_token: str,
) -> None:
    """Retry one idempotent transaction through DynamoDB's settlement window."""
    delays = (0.0, *TRANSACTION_SETTLEMENT_DELAYS_SECONDS)
    last_error: BotoCoreError | ClientError | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            client.transact_write_items(
                # The DynamoDB resource client's marshaller mutates nested input
                # values in place. Retry a fresh native-value copy so a second
                # attempt is byte-equivalent instead of double-serialized.
                TransactItems=deepcopy(transaction),
                ClientRequestToken=client_request_token,
            )
            return
        except client.exceptions.TransactionCanceledException:
            # Cancellation is a settled outcome; the caller classifies its durable
            # conditions and matching marker below.
            raise
        except (BotoCoreError, ClientError) as exc:
            last_error = exc
            if not _transaction_error_is_retryable(exc):
                raise
    if last_error is None:  # pragma: no cover - delays always includes one attempt
        raise UsageControlUnavailable("Atomic transaction was not attempted")
    raise last_error


def _identifier(value: Any, name: str, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_length
    ):
        raise ValueError(f"{name} is invalid")
    return value


def _counter_value(item: dict[str, Any] | None) -> int:
    value = (item or {}).get("runUnits", 0)
    if isinstance(value, Decimal) and value == value.to_integral_value():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UsageControlUnavailable("Usage counter contains an invalid value")
    return value


def _consistent_item(key: dict[str, str]) -> dict[str, Any] | None:
    try:
        return table.get_item(Key=key, ConsistentRead=True).get("Item")
    except (BotoCoreError, ClientError) as exc:
        raise UsageControlUnavailable("Usage control storage is unavailable") from exc
    except Exception as exc:
        # Unknown storage failures must also fail closed, but typed SDK failures
        # remain separate above so callers and tests cannot mistake denials for I/O.
        raise UsageControlUnavailable("Usage control storage is unavailable") from exc


def _circuit_is_open() -> bool:
    circuit = _consistent_item(USAGE_CIRCUIT_KEY)
    return _circuit_item_is_open(circuit)


def _circuit_item_is_open(circuit: dict[str, Any] | None) -> bool:
    if circuit is None:
        return False
    if circuit.get("entity") != "USAGE_CIRCUIT":
        raise UsageControlUnavailable("Usage circuit contains an invalid value")
    state = circuit.get("open")
    if not isinstance(state, bool):
        raise UsageControlUnavailable("Usage circuit contains an invalid value")
    return state


def _billing_account_is_active(state: dict[str, Any] | None) -> bool:
    if state is None or "accountStatus" not in state:
        return True
    status = state.get("accountStatus")
    if not isinstance(status, str):
        raise UsageControlUnavailable("Billing account state is invalid")
    return status not in {"DELETING", "DELETED"}


def _marker_matches(
    marker: dict[str, Any], billing_user_id: str, run_id: str, run_units: int
) -> bool:
    return (
        marker.get("entity") == "USAGE_ADMISSION"
        and marker.get("billingUserId") == billing_user_id
        and marker.get("runId") == run_id
        and _counter_value(marker) == run_units
    )


def _read_decision_after_failure(
    *,
    account_key: dict[str, str],
    marker_key: dict[str, str],
    billing_user_id: str,
    run_id: str,
    run_units: int,
    month_key: dict[str, str],
    user_window_key: dict[str, str],
    global_window_key: dict[str, str],
    limits: UsageLimits,
    allow_duplicate_during_circuit: bool,
) -> AdmissionDecision:
    # Every read is strongly consistent. Read the complete decision state before
    # classifying an ambiguous transaction result; a matching durable marker is
    # proof that this exact admission committed even if its response was lost.
    account = _consistent_item(account_key)
    marker = _consistent_item(marker_key)
    circuit = _consistent_item(USAGE_CIRCUIT_KEY)
    month_counter = _consistent_item(month_key)
    user_window_counter = _consistent_item(user_window_key)
    global_window_counter = _consistent_item(global_window_key)

    if not _billing_account_is_active(account):
        return AdmissionDecision(False, "account_inactive")
    if marker is not None:
        if not _marker_matches(marker, billing_user_id, run_id, run_units):
            raise UsageControlUnavailable("Admission id was reused inconsistently")
        if _circuit_item_is_open(circuit) and not allow_duplicate_during_circuit:
            return AdmissionDecision(False, "circuit_open")
        return AdmissionDecision(True, "duplicate", duplicate=True)
    if _circuit_item_is_open(circuit):
        return AdmissionDecision(False, "circuit_open")

    if _counter_value(month_counter) + run_units > limits.monthly_run_units:
        return AdmissionDecision(False, "monthly_limit")
    if (
        _counter_value(user_window_counter) + run_units
        > limits.user_window_run_units
    ):
        return AdmissionDecision(False, "user_rate_limit")
    if (
        _counter_value(global_window_counter) + run_units
        > limits.global_window_run_units
    ):
        return AdmissionDecision(False, "global_rate_limit")
    raise UsageControlUnavailable("Atomic usage admission was not committed")


def admit_run(
    billing_user_id: str,
    run_id: str,
    *,
    run_units: int = 1,
    now: datetime | None = None,
    limits: UsageLimits | None = None,
    allow_duplicate_during_circuit: bool = False,
) -> AdmissionDecision:
    """Atomically reserve a logical run before any product-funded provider call.

    The durable marker makes retries and background continuations idempotent. A
    coordinated group round uses one run id and reserves its complete reply count.
    """
    safe_user_id = _identifier(billing_user_id, "billing_user_id", 128)
    safe_run_id = _identifier(run_id, "run_id", 256)
    if (
        isinstance(run_units, bool)
        or not isinstance(run_units, int)
        or not 1 <= run_units <= MAX_RUN_UNITS
    ):
        raise ValueError(f"run_units must be between 1 and {MAX_RUN_UNITS}")

    recorded_at = (now or datetime.now(UTC)).astimezone(UTC)
    usage_period = f"month:{recorded_at.strftime('%Y-%m')}"
    counter_sort_key = f"USAGE_LIMIT#MONTH#{recorded_at.strftime('%Y-%m')}"
    effective_limits = limits
    if effective_limits is None:
        try:
            entitlement = entitlement_for_user(table, safe_user_id, now=recorded_at)
        except Exception as exc:
            raise UsageControlUnavailable("Billing entitlement is unavailable") from exc
        effective_limits = UsageLimits(
            monthly_run_units=min(
                entitlement.credit_limit, USAGE_LIMITS.monthly_run_units
            ),
            user_window_run_units=USAGE_LIMITS.user_window_run_units,
            global_window_run_units=USAGE_LIMITS.global_window_run_units,
            window_seconds=USAGE_LIMITS.window_seconds,
        )
        usage_period = entitlement.period_key
        counter_sort_key = entitlement.counter_sort_key
    epoch = int(recorded_at.timestamp())
    window_start = epoch - (epoch % effective_limits.window_seconds)
    month = recorded_at.strftime("%Y-%m")
    marker_key = {
        "pk": f"USER#{safe_user_id}",
        "sk": f"USAGE_ADMISSION#{safe_run_id}",
    }
    account_key = {"pk": f"USER#{safe_user_id}", "sk": "STATE"}
    month_key = {
        "pk": f"USER#{safe_user_id}",
        "sk": counter_sort_key,
    }
    user_window_key = {
        "pk": f"USER#{safe_user_id}",
        "sk": f"USAGE_LIMIT#WINDOW#{window_start}",
    }
    global_window_key = {
        "pk": USAGE_CONTROL_PK,
        "sk": f"WINDOW#{window_start}",
    }

    if not _billing_account_is_active(_consistent_item(account_key)):
        return AdmissionDecision(False, "account_inactive")
    marker = _consistent_item(marker_key)
    if marker is not None:
        if not _marker_matches(marker, safe_user_id, safe_run_id, run_units):
            raise UsageControlUnavailable("Admission id was reused inconsistently")
        if _circuit_is_open() and not allow_duplicate_during_circuit:
            return AdmissionDecision(False, "circuit_open")
        return AdmissionDecision(True, "duplicate", duplicate=True)
    # The operator-controlled circuit is deliberately read strongly consistently.
    # A transaction condition below closes the race with a concurrent circuit flip.
    if _circuit_is_open():
        return AdmissionDecision(False, "circuit_open")

    if run_units > effective_limits.monthly_run_units:
        return AdmissionDecision(False, "monthly_limit")
    if run_units > effective_limits.user_window_run_units:
        return AdmissionDecision(False, "user_rate_limit")
    if run_units > effective_limits.global_window_run_units:
        return AdmissionDecision(False, "global_rate_limit")

    timestamp = recorded_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    admission_expiry = int(
        (recorded_at + timedelta(days=ADMISSION_RETENTION_DAYS)).timestamp()
    )
    rate_expiry = epoch + max(
        RATE_COUNTER_RETENTION_SECONDS, effective_limits.window_seconds * 2
    )
    marker_item = {
        **marker_key,
        "entity": "USAGE_ADMISSION",
        "billingUserId": safe_user_id,
        "runId": safe_run_id,
        "runUnits": run_units,
        "usageMonth": month,
        "usagePeriod": usage_period,
        "windowStart": window_start,
        "createdAt": timestamp,
        "expiresAt": admission_expiry,
    }

    def counter_update(
        key: dict[str, str], *, entity: str, limit: int, expiry: int
    ) -> dict[str, Any]:
        return {
            "TableName": table.name,
            "Key": key,
            "UpdateExpression": (
                "SET #entity = if_not_exists(#entity, :entity), "
                "expiresAt = if_not_exists(expiresAt, :expiry) ADD runUnits :units"
            ),
            "ConditionExpression": (
                "(attribute_not_exists(runUnits) OR "
                "(attribute_type(runUnits, :numberType) AND runUnits >= :zero "
                "AND runUnits <= :maximumBefore)) AND "
                "(attribute_not_exists(#entity) OR #entity = :entity)"
            ),
            "ExpressionAttributeNames": {"#entity": "entity"},
            "ExpressionAttributeValues": {
                ":entity": entity,
                ":expiry": expiry,
                ":units": run_units,
                ":zero": 0,
                ":numberType": "N",
                ":maximumBefore": limit - run_units,
            },
        }

    transaction = [
        {
            "ConditionCheck": {
                "TableName": table.name,
                "Key": account_key,
                "ConditionExpression": (
                    "attribute_not_exists(accountStatus) OR "
                    "(attribute_type(accountStatus, :stringType) AND "
                    "accountStatus <> :deleting AND accountStatus <> :deleted)"
                ),
                "ExpressionAttributeValues": {
                    ":stringType": "S",
                    ":deleting": "DELETING",
                    ":deleted": "DELETED",
                },
            }
        },
        {
            "ConditionCheck": {
                "TableName": table.name,
                "Key": USAGE_CIRCUIT_KEY,
                "ConditionExpression": (
                    "attribute_not_exists(pk) OR (#entity = :entity AND "
                    "attribute_type(#open, :boolType) AND #open = :false)"
                ),
                "ExpressionAttributeNames": {"#entity": "entity", "#open": "open"},
                "ExpressionAttributeValues": {
                    ":entity": "USAGE_CIRCUIT",
                    ":boolType": "BOOL",
                    ":false": False,
                },
            }
        },
        {
            "Put": {
                "TableName": table.name,
                "Item": marker_item,
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
        {
            "Update": counter_update(
                month_key,
                entity="USAGE_MONTH_COUNTER",
                limit=effective_limits.monthly_run_units,
                expiry=admission_expiry,
            )
        },
        {
            "Update": counter_update(
                user_window_key,
                entity="USAGE_USER_WINDOW_COUNTER",
                limit=effective_limits.user_window_run_units,
                expiry=rate_expiry,
            )
        },
        {
            "Update": counter_update(
                global_window_key,
                entity="USAGE_GLOBAL_WINDOW_COUNTER",
                limit=effective_limits.global_window_run_units,
                expiry=rate_expiry,
            )
        },
    ]
    client = table.meta.client
    client_request_token = hashlib.sha256(
        f"{safe_user_id}\0{safe_run_id}".encode()
    ).hexdigest()[:36]
    try:
        _transact_write_with_settlement(client, transaction, client_request_token)
    except client.exceptions.TransactionCanceledException as exc:
        cancellation_reasons = exc.response.get("CancellationReasons", [])
        if any(
            isinstance(reason, dict)
            and reason.get("Code") not in {None, "None", "ConditionalCheckFailed"}
            for reason in cancellation_reasons
        ):
            raise UsageControlUnavailable("Atomic usage admission failed") from exc
        return _read_decision_after_failure(
            account_key=account_key,
            marker_key=marker_key,
            billing_user_id=safe_user_id,
            run_id=safe_run_id,
            run_units=run_units,
            month_key=month_key,
            user_window_key=user_window_key,
            global_window_key=global_window_key,
            limits=effective_limits,
            allow_duplicate_during_circuit=allow_duplicate_during_circuit,
        )
    except (BotoCoreError, ClientError):
        try:
            return _read_decision_after_failure(
                account_key=account_key,
                marker_key=marker_key,
                billing_user_id=safe_user_id,
                run_id=safe_run_id,
                run_units=run_units,
                month_key=month_key,
                user_window_key=user_window_key,
                global_window_key=global_window_key,
                limits=effective_limits,
                allow_duplicate_during_circuit=allow_duplicate_during_circuit,
            )
        except UsageControlUnavailable as reconciliation_error:
            raise UsageControlUnavailable(
                "Usage control storage is unavailable"
            ) from reconciliation_error
    except Exception as exc:
        raise UsageControlUnavailable("Usage control storage is unavailable") from exc
    return AdmissionDecision(True, "admitted")


__all__ = [
    "USAGE_CIRCUIT_KEY",
    "AdmissionDecision",
    "UsageControlUnavailable",
    "UsageLimits",
    "admit_run",
]
