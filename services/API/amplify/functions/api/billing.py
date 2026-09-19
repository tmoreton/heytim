from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from botocore.config import Config
from shared.billing import billing_available, entitlement_for_user

from .support import (
    PUBLIC_WEB_BASE_URL,
    ApiError,
    _body,
    _now,
    _response,
    _verified_email,
    table,
)

STRIPE_API_BASE = "https://api.stripe.com"
STRIPE_EVENT_RETENTION_DAYS = 400
STRIPE_SIGNATURE_TOLERANCE_SECONDS = 300
_secret_cache: dict[str, str] | None = None


def _price_cents() -> int:
    try:
        value = int(os.environ.get("HEYTIM_PLUS_PRICE_CENTS", "2000"))
    except ValueError as exc:
        raise RuntimeError("HEYTIM_PLUS_PRICE_CENTS must be an integer") from exc
    if not 1 <= value <= 10_000_000:
        raise RuntimeError("HEYTIM_PLUS_PRICE_CENTS is invalid")
    return value


def _stripe_live_mode() -> bool:
    return os.environ.get("STRIPE_LIVE_MODE", "false").lower() == "true"


def _stripe_automatic_tax() -> bool:
    return os.environ.get("STRIPE_AUTOMATIC_TAX", "false").lower() == "true"


def _stripe_configuration() -> dict[str, str]:
    global _secret_cache
    if not billing_available():
        raise ApiError(503, "Subscriptions are not available yet")
    if _secret_cache is not None:
        return _secret_cache
    secret_id = os.environ.get("STRIPE_SECRET_ID", "")
    if not secret_id:
        raise ApiError(503, "Subscriptions are not configured")
    client = boto3.client(
        "secretsmanager",
        config=Config(
            retries={"total_max_attempts": 4, "mode": "adaptive"},
            connect_timeout=3,
            read_timeout=10,
        ),
    )
    try:
        raw = client.get_secret_value(SecretId=secret_id).get("SecretString", "")
        value = json.loads(raw)
    except Exception as exc:
        raise ApiError(503, "Subscriptions are temporarily unavailable") from exc
    if not isinstance(value, dict):
        raise ApiError(503, "Subscriptions are not configured")
    secret_key = value.get("secretKey") or value.get("STRIPE_SECRET_KEY")
    webhook_secret = value.get("webhookSecret") or value.get(
        "STRIPE_WEBHOOK_SECRET"
    )
    if not isinstance(secret_key, str) or not secret_key.startswith("sk_"):
        raise ApiError(503, "Subscriptions are not configured")
    if not isinstance(webhook_secret, str) or not webhook_secret.startswith("whsec_"):
        raise ApiError(503, "Subscriptions are not configured")
    _secret_cache = {"secretKey": secret_key, "webhookSecret": webhook_secret}
    return _secret_cache


def _stripe_request(
    method: str,
    path: str,
    *,
    form: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    config = _stripe_configuration()
    data = urllib.parse.urlencode(form or {}, doseq=True).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {config['secretKey']}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Version": os.environ.get("STRIPE_API_VERSION", "2026-08-26.dahlia"),
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(
        f"{STRIPE_API_BASE}{path}",
        data=data if method != "GET" else None,
        headers=headers,
        method=method,
    )
    try:
        # The origin is the constant Stripe HTTPS API; callers supply only a path.
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
            result = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            message = error.get("message") if isinstance(error, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = None
        raise ApiError(
            502,
            message if isinstance(message, str) else "Stripe rejected the request",
        ) from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ApiError(502, "Stripe is temporarily unavailable") from exc
    if not isinstance(result, dict):
        raise ApiError(502, "Stripe returned an invalid response")
    return result


def _request_id(event: dict) -> str:
    value = _body(event).get("requestId")
    try:
        parsed = uuid.UUID(value) if isinstance(value, str) else None
    except ValueError as exc:
        raise ApiError(400, "requestId must be a UUID") from exc
    if parsed is None or str(parsed) != value.lower():
        raise ApiError(400, "requestId must be a UUID")
    return value


def _counter_value(item: dict[str, Any] | None) -> int:
    value = (item or {}).get("runUnits", 0)
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, result)


def billing_summary(user_id: str) -> dict[str, Any]:
    entitlement = entitlement_for_user(table, user_id)
    counter = table.get_item(
        Key={
            "pk": f"USER#{user_id}",
            "sk": entitlement.counter_sort_key,
        },
        ConsistentRead=True,
    ).get("Item")
    used = min(_counter_value(counter), entitlement.credit_limit)
    available = billing_available()
    return {
        "plan": entitlement.plan,
        "status": entitlement.status,
        "creditsUsed": used,
        "creditsRemaining": max(0, entitlement.credit_limit - used),
        "creditLimit": entitlement.credit_limit,
        "resetsAt": entitlement.resets_at,
        "cancelAtPeriodEnd": entitlement.cancel_at_period_end,
        "billingAvailable": available,
        "checkoutAvailable": available and entitlement.plan != "plus",
        "managementAvailable": available
        and entitlement.stripe_customer_id is not None,
        "supportedStorefrontCountryCode": "USA",
        "price": {
            "currency": "usd",
            "unitAmount": _price_cents(),
            "interval": "month",
        },
        "mode": "live" if _stripe_live_mode() else "test",
    }


def create_checkout(user_id: str, email: str, event: dict) -> dict[str, str]:
    request_id = _request_id(event)
    body = _body(event)
    if body.get("storefrontCountryCode") != "USA":
        raise ApiError(403, "Web subscription checkout is currently available in the U.S. only")
    entitlement = entitlement_for_user(table, user_id)
    if entitlement.plan == "plus":
        raise ApiError(409, "Your Plus subscription is already active")
    price_id = os.environ.get("STRIPE_PLUS_PRICE_ID", "")
    if not price_id.startswith("price_"):
        raise ApiError(503, "Subscriptions are not configured")
    success_url = f"{PUBLIC_WEB_BASE_URL}/billing?status=success"
    cancel_url = f"{PUBLIC_WEB_BASE_URL}/billing?status=canceled"
    form: dict[str, Any] = {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "client_reference_id": user_id,
        "metadata[userId]": user_id,
        "subscription_data[metadata][userId]": user_id,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": "true",
        "origin_context": "mobile_app",
    }
    if _stripe_automatic_tax():
        form["automatic_tax[enabled]"] = "true"
    if entitlement.stripe_customer_id:
        form["customer"] = entitlement.stripe_customer_id
    else:
        form["customer_email"] = email
    key = hashlib.sha256(f"checkout\0{user_id}\0{request_id}".encode()).hexdigest()
    session = _stripe_request(
        "POST", "/v1/checkout/sessions", form=form, idempotency_key=key
    )
    url = session.get("url")
    if not isinstance(url, str) or not url.startswith("https://checkout.stripe.com/"):
        raise ApiError(502, "Stripe did not return a checkout link")
    return {"url": url}


def create_portal(user_id: str, event: dict) -> dict[str, str]:
    request_id = _request_id(event)
    entitlement = entitlement_for_user(table, user_id)
    if not entitlement.stripe_customer_id:
        raise ApiError(409, "No Stripe subscription is connected to this account")
    key = hashlib.sha256(f"portal\0{user_id}\0{request_id}".encode()).hexdigest()
    session = _stripe_request(
        "POST",
        "/v1/billing_portal/sessions",
        form={
            "customer": entitlement.stripe_customer_id,
            "return_url": f"{PUBLIC_WEB_BASE_URL}/billing?status=return",
        },
        idempotency_key=key,
    )
    url = session.get("url")
    if not isinstance(url, str) or not url.startswith("https://billing.stripe.com/"):
        raise ApiError(502, "Stripe did not return a billing link")
    return {"url": url}


def billing_route(
    user_id: str,
    _display_name: str,
    method: str,
    path: str,
    _params: dict,
    event: dict,
) -> dict | None:
    if method == "GET" and path == "/billing":
        return _response(200, billing_summary(user_id))
    if method == "POST" and path == "/billing/checkout":
        return _response(200, create_checkout(user_id, _verified_email(event), event))
    if method == "POST" and path == "/billing/portal":
        return _response(200, create_portal(user_id, event))
    return None


def _raw_body(event: dict) -> bytes:
    body = event.get("body", "")
    if not isinstance(body, str):
        raise ApiError(400, "Invalid webhook body")
    try:
        return base64.b64decode(body, validate=True) if event.get("isBase64Encoded") else body.encode()
    except ValueError as exc:
        raise ApiError(400, "Invalid webhook body") from exc


def _header(event: dict, name: str) -> str:
    headers = event.get("headers") or {}
    value = next(
        (value for key, value in headers.items() if key.lower() == name.lower()), None
    )
    if not isinstance(value, str):
        raise ApiError(400, "Missing Stripe signature")
    return value


def _verified_event(event: dict) -> dict[str, Any]:
    raw = _raw_body(event)
    signature = _header(event, "stripe-signature")
    values: dict[str, list[str]] = {}
    for part in signature.split(","):
        key, separator, value = part.partition("=")
        if separator:
            values.setdefault(key, []).append(value)
    try:
        timestamp = int(values.get("t", [""])[0])
    except ValueError as exc:
        raise ApiError(400, "Invalid Stripe signature") from exc
    if abs(int(time.time()) - timestamp) > STRIPE_SIGNATURE_TOLERANCE_SECONDS:
        raise ApiError(400, "Expired Stripe signature")
    secret = _stripe_configuration()["webhookSecret"].encode()
    expected = hmac.new(
        secret, str(timestamp).encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, value) for value in values.get("v1", [])):
        raise ApiError(400, "Invalid Stripe signature")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(400, "Invalid webhook JSON") from exc
    if not isinstance(parsed, dict):
        raise ApiError(400, "Invalid webhook event")
    return parsed


def _subscription_period(subscription: dict[str, Any]) -> tuple[int, int]:
    start = subscription.get("current_period_start")
    end = subscription.get("current_period_end")
    items = subscription.get("items", {}).get("data", [])
    if (not isinstance(start, int) or not isinstance(end, int)) and items:
        first = items[0] if isinstance(items[0], dict) else {}
        start = first.get("current_period_start")
        end = first.get("current_period_end")
    if not isinstance(start, int) or not isinstance(end, int) or end <= start:
        raise ApiError(400, "Stripe subscription period is invalid")
    return start, end


def _subscription_price_id(subscription: dict[str, Any]) -> str:
    items = subscription.get("items", {}).get("data", [])
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise ApiError(400, "Stripe subscription has no price")
    price = items[0].get("price")
    price_id = price.get("id") if isinstance(price, dict) else None
    if not isinstance(price_id, str):
        raise ApiError(400, "Stripe subscription has no price")
    return price_id


def _event_subscription(stripe_event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    event_type = stripe_event.get("type")
    obj = stripe_event.get("data", {}).get("object")
    if not isinstance(obj, dict):
        raise ApiError(400, "Stripe event data is invalid")
    if event_type == "checkout.session.completed":
        user_id = obj.get("client_reference_id") or obj.get("metadata", {}).get("userId")
        subscription_id = obj.get("subscription")
        if not isinstance(subscription_id, str):
            return None
        subscription = _stripe_request(
            "GET", f"/v1/subscriptions/{urllib.parse.quote(subscription_id)}"
        )
        return user_id, subscription
    if event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        user_id = obj.get("metadata", {}).get("userId")
        return user_id, obj
    return None


def _store_subscription_event(
    stripe_event: dict[str, Any], user_id: str, subscription: dict[str, Any]
) -> None:
    if not user_id or len(user_id) > 128 or user_id != user_id.strip():
        raise ApiError(400, "Stripe event has no valid user reference")
    event_id = stripe_event.get("id")
    created = stripe_event.get("created")
    if not isinstance(event_id, str) or not event_id.startswith("evt_"):
        raise ApiError(400, "Stripe event id is invalid")
    if not isinstance(created, int):
        raise ApiError(400, "Stripe event time is invalid")
    livemode = stripe_event.get("livemode")
    if not isinstance(livemode, bool) or livemode != _stripe_live_mode():
        raise ApiError(400, "Stripe event mode does not match this deployment")
    marker_key = {"pk": "SYSTEM#STRIPE_EVENT", "sk": f"EVENT#{event_id}"}
    if table.get_item(Key=marker_key, ConsistentRead=True).get("Item"):
        return
    state = table.get_item(
        Key={"pk": f"USER#{user_id}", "sk": "STATE"}, ConsistentRead=True
    ).get("Item") or {}
    if state.get("accountStatus") in {"DELETING", "DELETED"}:
        return
    period_start, period_end = _subscription_period(subscription)
    price_id = _subscription_price_id(subscription)
    customer = subscription.get("customer")
    subscription_id = subscription.get("id")
    status = subscription.get("status")
    if not all(isinstance(value, str) for value in (customer, subscription_id, status)):
        raise ApiError(400, "Stripe subscription data is invalid")
    billing_item = {
        "pk": f"USER#{user_id}",
        "sk": "BILLING",
        "entity": "BILLING",
        "provider": "stripe",
        "stripeCustomerId": customer,
        "stripeSubscriptionId": subscription_id,
        "stripePriceId": price_id,
        "subscriptionStatus": status,
        "currentPeriodStart": period_start,
        "currentPeriodEnd": period_end,
        "cancelAtPeriodEnd": subscription.get("cancel_at_period_end") is True,
        "stripeEventCreated": created,
        "stripeEventId": event_id,
        "updatedAt": _now(),
    }
    try:
        table.put_item(
            Item=billing_item,
            ConditionExpression=(
                "attribute_not_exists(stripeEventCreated) OR stripeEventCreated <= :created"
            ),
            ExpressionAttributeValues={":created": created},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass
    expires_at = int((datetime.now(UTC) + timedelta(days=STRIPE_EVENT_RETENTION_DAYS)).timestamp())
    try:
        table.put_item(
            Item={
                **marker_key,
                "entity": "STRIPE_EVENT",
                "eventType": stripe_event.get("type", "unknown"),
                "createdAt": _now(),
                "expiresAt": expires_at,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        pass


def stripe_webhook(event: dict) -> dict:
    stripe_event = _verified_event(event)
    subscription_event = _event_subscription(stripe_event)
    if subscription_event is not None:
        user_id, subscription = subscription_event
        _store_subscription_event(stripe_event, user_id, subscription)
    return _response(200, {"received": True})


def cancel_stripe_subscription_for_account(user_id: str) -> None:
    if not billing_available():
        return
    entitlement = entitlement_for_user(table, user_id)
    if (
        not entitlement.stripe_subscription_id
        or entitlement.status
        not in {"active", "trialing", "past_due", "unpaid", "incomplete"}
    ):
        return
    key = hashlib.sha256(f"account-delete\0{user_id}".encode()).hexdigest()
    _stripe_request(
        "DELETE",
        f"/v1/subscriptions/{urllib.parse.quote(entitlement.stripe_subscription_id)}",
        idempotency_key=key,
    )


__all__ = [
    "billing_route",
    "billing_summary",
    "cancel_stripe_subscription_for_account",
    "stripe_webhook",
]
