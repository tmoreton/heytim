from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


def _bounded_integer(name: str, default: int, minimum: int, maximum: int) -> int:
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


def billing_available() -> bool:
    return os.environ.get("HEYTIM_STRIPE_AVAILABLE", "false").lower() == "true"


def free_monthly_credits() -> int:
    return _bounded_integer("HEYTIM_FREE_MONTHLY_CREDITS", 30, 1, 1_000_000)


def plus_monthly_credits() -> int:
    return _bounded_integer("HEYTIM_PLUS_MONTHLY_CREDITS", 300, 1, 1_000_000)


def preview_monthly_credits() -> int:
    return _bounded_integer("HEYTIM_MONTHLY_RUN_UNIT_LIMIT", 1_000, 1, 1_000_000)


def _integer(value: Any) -> int | None:
    if isinstance(value, Decimal) and value == value.to_integral_value():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _iso_timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _next_month(moment: datetime) -> datetime:
    year = moment.year + (1 if moment.month == 12 else 0)
    month = 1 if moment.month == 12 else moment.month + 1
    return datetime(year, month, 1, tzinfo=UTC)


@dataclass(frozen=True)
class BillingEntitlement:
    plan: str
    status: str
    credit_limit: int
    counter_sort_key: str
    period_key: str
    resets_at: str
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    cancel_at_period_end: bool = False


def entitlement_for_user(
    table: Any,
    user_id: str,
    *,
    now: datetime | None = None,
) -> BillingEntitlement:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    month = current.strftime("%Y-%m")
    item = table.get_item(
        Key={"pk": f"USER#{user_id}", "sk": "BILLING"},
        ConsistentRead=True,
    ).get("Item")
    item = item if isinstance(item, dict) else {}

    status = item.get("subscriptionStatus")
    period_start = _integer(item.get("currentPeriodStart"))
    period_end = _integer(item.get("currentPeriodEnd"))
    expected_price = os.environ.get("STRIPE_PLUS_PRICE_ID", "")
    price_matches = not expected_price or item.get("stripePriceId") == expected_price
    active_plus = (
        billing_available()
        and status in ACTIVE_SUBSCRIPTION_STATUSES
        and price_matches
        and period_start is not None
        and period_end is not None
        and period_start <= int(current.timestamp()) < period_end
    )
    if active_plus:
        customer_id = item.get("stripeCustomerId")
        subscription_id = item.get("stripeSubscriptionId")
        return BillingEntitlement(
            plan="plus",
            status=str(status),
            credit_limit=plus_monthly_credits(),
            counter_sort_key=f"USAGE_LIMIT#SUBSCRIPTION#{period_start}",
            period_key=f"subscription:{period_start}",
            resets_at=_iso_timestamp(datetime.fromtimestamp(period_end, UTC)),
            stripe_customer_id=customer_id if isinstance(customer_id, str) else None,
            stripe_subscription_id=(
                subscription_id if isinstance(subscription_id, str) else None
            ),
            cancel_at_period_end=item.get("cancelAtPeriodEnd") is True,
        )

    if not billing_available():
        return BillingEntitlement(
            plan="preview",
            status="preview",
            credit_limit=preview_monthly_credits(),
            counter_sort_key=f"USAGE_LIMIT#MONTH#{month}",
            period_key=f"month:{month}",
            resets_at=_iso_timestamp(_next_month(current)),
        )

    customer_id = item.get("stripeCustomerId")
    subscription_id = item.get("stripeSubscriptionId")
    return BillingEntitlement(
        plan="free",
        status=str(status) if isinstance(status, str) else "free",
        credit_limit=free_monthly_credits(),
        counter_sort_key=f"USAGE_LIMIT#MONTH#{month}",
        period_key=f"month:{month}",
        resets_at=_iso_timestamp(_next_month(current)),
        stripe_customer_id=customer_id if isinstance(customer_id, str) else None,
        stripe_subscription_id=(
            subscription_id if isinstance(subscription_id, str) else None
        ),
        cancel_at_period_end=item.get("cancelAtPeriodEnd") is True,
    )


__all__ = [
    "ACTIVE_SUBSCRIPTION_STATUSES",
    "BillingEntitlement",
    "billing_available",
    "entitlement_for_user",
    "free_monthly_credits",
    "plus_monthly_credits",
]
