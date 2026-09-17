from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from botocore.exceptions import BotoCoreError, ClientError

from .support import table
from .usage_controls import (
    USAGE_CONTROL_PK,
    AdmissionDecision,
    UsageControlUnavailable,
    _billing_account_is_active,
    _bounded_integer_environment,
    _consistent_item,
    _counter_value,
    _identifier,
    _transact_write_with_settlement,
)

MAX_PROVIDER_CALL_RESERVATION = 100
YOUTUBE_SEARCH_RESERVATION_CALLS = 3
YOUTUBE_QUOTA_TIME_ZONE = ZoneInfo("America/Los_Angeles")
YOUTUBE_SEARCH_DAILY_LIMIT = _bounded_integer_environment(
    "FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT",
    100,
    YOUTUBE_SEARCH_RESERVATION_CALLS,
    1_000_000,
)


def _uses_youtube_search(resolved_tools: list[dict]) -> bool:
    return any(
        isinstance(tool.get("runtime"), dict)
        and (
            (
                tool["runtime"].get("kind") == "gateway"
                and "youtube_search" in tool["runtime"].get("operations", [])
            )
            or (
                tool["runtime"].get("kind") == "provider_api"
                and tool["runtime"].get("provider") == "youtube"
            )
        )
        for tool in resolved_tools
        if isinstance(tool, dict)
    )


def youtube_quota_day(now: datetime | None = None) -> str:
    """Return the YouTube quota date, which resets at midnight Pacific Time."""
    recorded_at = (now or datetime.now(UTC)).astimezone(UTC)
    return recorded_at.astimezone(YOUTUBE_QUOTA_TIME_ZONE).date().isoformat()


def _youtube_reservation_matches(
    marker: dict[str, Any],
    billing_user_id: str,
    reservation_id: str,
    quota_day: str,
    reserved_calls: int,
) -> bool:
    return (
        marker.get("entity") == "USAGE_PROVIDER_ADMISSION"
        and marker.get("provider") == "youtube_search"
        and marker.get("billingUserId") == billing_user_id
        and marker.get("reservationId") == reservation_id
        and marker.get("quotaDay") == quota_day
        and _counter_value(marker) == reserved_calls
    )


def _youtube_counter_value(item: dict[str, Any] | None) -> int:
    if item is not None and item.get("entity") != "USAGE_PROVIDER_DAY_COUNTER":
        raise UsageControlUnavailable("YouTube usage counter is invalid")
    return _counter_value(item)


def _read_youtube_reservation_after_failure(
    *,
    account_key: dict[str, str],
    marker_key: dict[str, str],
    counter_key: dict[str, str],
    billing_user_id: str,
    reservation_id: str,
    quota_day: str,
    reserved_calls: int,
    daily_limit: int,
) -> AdmissionDecision:
    account = _consistent_item(account_key)
    marker = _consistent_item(marker_key)
    counter = _consistent_item(counter_key)
    if not _billing_account_is_active(account):
        return AdmissionDecision(False, "account_inactive", quota_day=quota_day)
    if marker is not None:
        if not _youtube_reservation_matches(
            marker,
            billing_user_id,
            reservation_id,
            quota_day,
            reserved_calls,
        ):
            raise UsageControlUnavailable(
                "YouTube reservation id was reused inconsistently"
            )
        return AdmissionDecision(
            True, "duplicate", duplicate=True, quota_day=quota_day
        )
    if _youtube_counter_value(counter) + reserved_calls > daily_limit:
        return AdmissionDecision(
            False, "provider_daily_limit", quota_day=quota_day
        )
    raise UsageControlUnavailable("Atomic YouTube capacity reservation was not committed")


def reserve_youtube_search_calls(
    billing_user_id: str,
    reservation_id: str,
    *,
    reserved_calls: int = YOUTUBE_SEARCH_RESERVATION_CALLS,
    daily_limit: int = YOUTUBE_SEARCH_DAILY_LIMIT,
    now: datetime | None = None,
) -> AdmissionDecision:
    """Reserve a runtime session's maximum YouTube search calls atomically.

    YouTube's Search Queries bucket is shared by the company API key. The
    runtime receives this reservation's Pacific-time date and refuses to use it
    after that date changes.
    """
    safe_user_id = _identifier(billing_user_id, "billing_user_id", 128)
    safe_reservation_id = _identifier(reservation_id, "reservation_id", 256)
    if (
        isinstance(reserved_calls, bool)
        or not isinstance(reserved_calls, int)
        or not 1 <= reserved_calls <= MAX_PROVIDER_CALL_RESERVATION
    ):
        raise ValueError(
            "reserved_calls must be between 1 and "
            f"{MAX_PROVIDER_CALL_RESERVATION}"
        )
    if (
        isinstance(daily_limit, bool)
        or not isinstance(daily_limit, int)
        or not YOUTUBE_SEARCH_RESERVATION_CALLS <= daily_limit <= 1_000_000
    ):
        raise ValueError(
            "daily_limit must be between "
            f"{YOUTUBE_SEARCH_RESERVATION_CALLS} and 1000000"
        )

    recorded_at = (now or datetime.now(UTC)).astimezone(UTC)
    quota_day = youtube_quota_day(recorded_at)
    marker_hash = hashlib.sha256(safe_reservation_id.encode()).hexdigest()[:32]
    marker_key = {
        "pk": f"USER#{safe_user_id}",
        "sk": (
            "USAGE_PROVIDER_ADMISSION#YOUTUBE_SEARCH#"
            f"{quota_day}#{marker_hash}"
        ),
    }
    account_key = {"pk": f"USER#{safe_user_id}", "sk": "STATE"}
    counter_key = {
        "pk": USAGE_CONTROL_PK,
        "sk": f"USAGE_LIMIT#PROVIDER#YOUTUBE_SEARCH#DAY#{quota_day}",
    }

    if not _billing_account_is_active(_consistent_item(account_key)):
        return AdmissionDecision(False, "account_inactive", quota_day=quota_day)
    marker = _consistent_item(marker_key)
    if marker is not None:
        if not _youtube_reservation_matches(
            marker,
            safe_user_id,
            safe_reservation_id,
            quota_day,
            reserved_calls,
        ):
            raise UsageControlUnavailable(
                "YouTube reservation id was reused inconsistently"
            )
        return AdmissionDecision(
            True, "duplicate", duplicate=True, quota_day=quota_day
        )
    if reserved_calls > daily_limit:
        return AdmissionDecision(
            False, "provider_daily_limit", quota_day=quota_day
        )

    timestamp = recorded_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    expires_at = int((recorded_at + timedelta(days=8)).timestamp())
    marker_item = {
        **marker_key,
        "entity": "USAGE_PROVIDER_ADMISSION",
        "provider": "youtube_search",
        "billingUserId": safe_user_id,
        "reservationId": safe_reservation_id,
        "quotaDay": quota_day,
        "runUnits": reserved_calls,
        "createdAt": timestamp,
        "expiresAt": expires_at,
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
            "Put": {
                "TableName": table.name,
                "Item": marker_item,
                "ConditionExpression": "attribute_not_exists(pk)",
            }
        },
        {
            "Update": {
                "TableName": table.name,
                "Key": counter_key,
                "UpdateExpression": (
                    "SET #entity = if_not_exists(#entity, :entity), "
                    "expiresAt = if_not_exists(expiresAt, :expiry) "
                    "ADD runUnits :units"
                ),
                "ConditionExpression": (
                    "(attribute_not_exists(runUnits) OR "
                    "(attribute_type(runUnits, :numberType) AND runUnits >= :zero "
                    "AND runUnits <= :maximumBefore)) AND "
                    "(attribute_not_exists(#entity) OR #entity = :entity)"
                ),
                "ExpressionAttributeNames": {"#entity": "entity"},
                "ExpressionAttributeValues": {
                    ":entity": "USAGE_PROVIDER_DAY_COUNTER",
                    ":expiry": expires_at,
                    ":units": reserved_calls,
                    ":zero": 0,
                    ":numberType": "N",
                    ":maximumBefore": daily_limit - reserved_calls,
                },
            }
        },
    ]
    client = table.meta.client
    client_request_token = hashlib.sha256(
        f"youtube_search\0{safe_user_id}\0{quota_day}\0{safe_reservation_id}".encode()
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
            raise UsageControlUnavailable(
                "Atomic YouTube capacity reservation failed"
            ) from exc
        return _read_youtube_reservation_after_failure(
            account_key=account_key,
            marker_key=marker_key,
            counter_key=counter_key,
            billing_user_id=safe_user_id,
            reservation_id=safe_reservation_id,
            quota_day=quota_day,
            reserved_calls=reserved_calls,
            daily_limit=daily_limit,
        )
    except (BotoCoreError, ClientError):
        try:
            return _read_youtube_reservation_after_failure(
                account_key=account_key,
                marker_key=marker_key,
                counter_key=counter_key,
                billing_user_id=safe_user_id,
                reservation_id=safe_reservation_id,
                quota_day=quota_day,
                reserved_calls=reserved_calls,
                daily_limit=daily_limit,
            )
        except UsageControlUnavailable as reconciliation_error:
            raise UsageControlUnavailable(
                "Usage control storage is unavailable"
            ) from reconciliation_error
    except Exception as exc:
        raise UsageControlUnavailable("Usage control storage is unavailable") from exc
    return AdmissionDecision(True, "reserved", quota_day=quota_day)


__all__ = [
    "YOUTUBE_SEARCH_RESERVATION_CALLS",
    "reserve_youtube_search_calls",
    "youtube_quota_day",
]
