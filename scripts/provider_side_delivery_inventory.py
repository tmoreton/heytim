"""Read-only Stripe and GitHub App delivery metadata inventory.

Application credentials remain in process memory. The output is a private
mode-0600 file with allowlisted metadata only; no webhook payload or token is
written or printed. This tool performs GET requests only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "API" / "amplify" / "functions"))
from shared.github_app import github_app_jwt

SOURCE_ACCOUNT = "188757775631"
REGION = "us-east-1"
STRIPE_ENDPOINT = "we_1UHW7fA7YzCs1pRZGFtVDD4J"
GITHUB_APP = "4931494"
STRIPE_TYPES = (
    "checkout.session.completed", "customer.subscription.created",
    "customer.subscription.updated", "customer.subscription.deleted",
)
SOURCE_STRIPE_URL = "https://twrxzanvwg.execute-api.us-east-1.amazonaws.com/public/webhooks/stripe"
DESTINATION_STRIPE_URL = "https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com/public/webhooks/stripe"
SOURCE_GITHUB_URL = "https://twrxzanvwg.execute-api.us-east-1.amazonaws.com/public/webhooks/github"
DESTINATION_GITHUB_URL = "https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com/public/webhooks/github"
MAX_PAGE_BYTES = 16 * 1024 * 1024
MAX_PAGES = 50
STRIPE_ID = re.compile(r"evt_[A-Za-z0-9]{5,120}\Z")
GITHUB_GUID = re.compile(r"[A-Za-z0-9-]{8,128}\Z")


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("A UTC timestamp is required")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _owner(url: str, provider: str) -> str:
    expected = {
        "stripe": (SOURCE_STRIPE_URL, DESTINATION_STRIPE_URL),
        "github": (SOURCE_GITHUB_URL, DESTINATION_GITHUB_URL),
    }[provider]
    return "source" if url == expected[0] else "destination" if url == expected[1] else "unknown"


def _request_json(url: str, token: str, provider: str) -> tuple[Any, str | None]:
    parsed = urllib.parse.urlsplit(url)
    expected_host = "api.stripe.com" if provider == "stripe" else "api.github.com"
    if parsed.scheme != "https" or parsed.netloc != expected_host or parsed.username or parsed.password:
        raise ValueError("Provider URL is not allowlisted")
    if provider == "stripe" and not parsed.path.startswith("/v1/"):
        raise ValueError("Stripe path is not allowlisted")
    if provider == "github" and not parsed.path.startswith("/app/hook"):
        raise ValueError("GitHub path is not allowlisted")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if provider == "github":
        headers["X-GitHub-Api-Version"] = "2026-03-10"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310: HTTPS host allowlist above
            raw = response.read(MAX_PAGE_BYTES + 1)
            link = response.headers.get("Link")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{provider}_http_{exc.code}") from None
    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError("Provider page exceeded the read limit")
    return json.loads(raw), link


def _next_link(link: str | None) -> str | None:
    if not link:
        return None
    for part in link.split(","):
        match = re.fullmatch(r'\s*<([^>]+)>;\s*rel="next"\s*', part)
        if match:
            url = match.group(1)
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != "api.github.com" or parsed.path != "/app/hook/deliveries":
                raise ValueError("GitHub pagination URL is not allowlisted")
            return url
    return None


def _source_session(profile: str) -> Any:
    session = boto3.Session(profile_name=profile, region_name=REGION)
    if session.client("sts").get_caller_identity().get("Account") != SOURCE_ACCOUNT:
        raise ValueError("Source AWS account does not match")
    return session


def _secret(session: Any, name: str) -> dict[str, Any]:
    client = session.client("secretsmanager", config=Config(
        retries={"total_max_attempts": 3, "mode": "standard"},
        connect_timeout=5, read_timeout=10,
    ))
    value = client.get_secret_value(SecretId=name)
    document = json.loads(value.get("SecretString", "{}"))
    if not isinstance(document, dict):
        raise ValueError("Application credential is invalid")  # noqa: TRY004 - malformed provider response
    return document


def _stripe_key(secret: dict[str, Any]) -> str:
    key = secret.get("secretKey") or secret.get("STRIPE_SECRET_KEY")
    if not isinstance(key, str) or not key.startswith(("sk_live_", "rk_live_")):
        raise ValueError("Live Stripe API key is unavailable")
    return key


def _github_jwt(secret: dict[str, Any]) -> str:
    if str(secret.get("appId")) != GITHUB_APP or not isinstance(secret.get("privateKey"), str):
        raise ValueError("GitHub App credential does not match the reviewed App")
    return github_app_jwt(GITHUB_APP, secret["privateKey"])


def _stripe_page_url(start: datetime, end: datetime, cursor: str | None,
                     undelivered: bool) -> str:
    query: list[tuple[str, str]] = [
        ("created[gte]", str(int(start.timestamp()))),
        ("created[lte]", str(int(end.timestamp()))),
        ("limit", "100"),
    ]
    query.extend(("types[]", value) for value in STRIPE_TYPES)
    if cursor:
        query.append(("starting_after", cursor))
    if undelivered:
        query.append(("delivery_success", "false"))
    return "https://api.stripe.com/v1/events?" + urllib.parse.urlencode(query)


def _stripe_events(start: datetime, end: datetime, key: str, fetch: Callable,
                   undelivered: bool = False) -> list[dict]:
    events: list[dict] = []
    cursor = None
    seen = set()
    for _ in range(MAX_PAGES):
        value, _ = fetch(_stripe_page_url(start, end, cursor, undelivered), key, "stripe")
        if not isinstance(value, dict) or not isinstance(value.get("data"), list) or type(value.get("has_more")) is not bool:
            raise ValueError("Stripe event listing is malformed")
        page = value["data"]
        for item in page:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not STRIPE_ID.fullmatch(item["id"]):
                raise ValueError("Stripe event ID is invalid")
            if item["id"] in seen:
                raise ValueError("Stripe pagination repeated an event")
            seen.add(item["id"])
            if item.get("type") not in STRIPE_TYPES or type(item.get("created")) is not int:
                raise ValueError("Stripe event metadata is invalid")
            events.append({
                "id": item["id"], "type": item["type"],
                "createdAtUTC": _iso(datetime.fromtimestamp(item["created"], UTC)),
                "livemode": item.get("livemode") is True,
                "pendingWebhooks": item.get("pending_webhooks") if type(item.get("pending_webhooks")) is int else None,
            })
        if not value["has_more"]:
            return events
        if not page:
            raise ValueError("Stripe pagination ended before has_more")
        cursor = page[-1]["id"]
    raise ValueError("Stripe event pagination exceeded the safety limit")


def _stripe_marker_presence(session: Any, table_name: str, event_ids: list[str]) -> dict[str, bool]:
    table = session.client("dynamodb", config=Config(retries={"total_max_attempts": 3, "mode": "standard"}))
    description = table.describe_table(TableName=table_name)["Table"]
    if description.get("TableArn", "").split(":")[4] != SOURCE_ACCOUNT or description.get("TableName") != table_name:
        raise ValueError("Source marker table does not match")
    result = {}
    for event_id in event_ids:
        response = table.get_item(
            TableName=table_name,
            Key={"pk": {"S": "SYSTEM#STRIPE_EVENT"}, "sk": {"S": f"EVENT#{event_id}"}},
            ConsistentRead=True,
            ProjectionExpression="#entity",
            ExpressionAttributeNames={"#entity": "entity"},
        )
        result[event_id] = response.get("Item", {}).get("entity", {}).get("S") == "STRIPE_EVENT"
    return result


def _source_stripe_state(session: Any, table_name: str, key: str,
                         fetch: Callable) -> dict:
    table = session.client("dynamodb", config=Config(retries={"total_max_attempts": 3, "mode": "standard"}))
    description = table.describe_table(TableName=table_name)["Table"]
    if description.get("TableArn", "").split(":")[4] != SOURCE_ACCOUNT or description.get("TableName") != table_name:
        raise ValueError("Source marker table does not match")
    markers = []
    for page in table.get_paginator("query").paginate(
        TableName=table_name,
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": {"S": "SYSTEM#STRIPE_EVENT"}, ":prefix": {"S": "EVENT#"},
        },
        ProjectionExpression="sk,#entity,eventType",
        ExpressionAttributeNames={"#entity": "entity"},
        ConsistentRead=True,
    ):
        for item in page.get("Items", []):
            event_id = item.get("sk", {}).get("S", "").removeprefix("EVENT#")
            if item.get("entity", {}).get("S") != "STRIPE_EVENT" or not STRIPE_ID.fullmatch(event_id):
                raise ValueError("Source Stripe marker identity is invalid")
            markers.append({"id": event_id, "markerEventType": item.get("eventType", {}).get("S", "unknown")})
    billing_ids = []
    for page in table.get_paginator("scan").paginate(
        TableName=table_name,
        ProjectionExpression="#entity,#provider,stripeEventId",
        ExpressionAttributeNames={"#entity": "entity", "#provider": "provider"},
        ConsistentRead=True,
    ):
        for item in page.get("Items", []):
            if item.get("entity", {}).get("S") == "BILLING" and item.get("provider", {}).get("S") == "stripe":
                event_id = item.get("stripeEventId", {}).get("S", "")
                if event_id and not STRIPE_ID.fullmatch(event_id):
                    raise ValueError("Source billing event identity is invalid")
                billing_ids.append(event_id)
    if len(markers) > 500 or len(billing_ids) > 500:
        raise ValueError("Source Stripe metadata exceeds the safety limit")
    for marker in markers:
        try:
            provider_event, _ = fetch(f"https://api.stripe.com/v1/events/{marker['id']}", key, "stripe")
        except RuntimeError as exc:
            if str(exc) != "stripe_http_404":
                raise
            provider_event = None
        marker["providerEventFound"] = isinstance(provider_event, dict) and provider_event.get("id") == marker["id"]
        marker["providerEventType"] = provider_event.get("type") if marker["providerEventFound"] else None
        marker["providerCreatedAtUTC"] = (
            _iso(datetime.fromtimestamp(provider_event["created"], UTC))
            if marker["providerEventFound"] and type(provider_event.get("created")) is int else None
        )
        marker["typeMatches"] = marker["providerEventFound"] and marker["markerEventType"] == marker["providerEventType"]
        marker["linkedToBilling"] = marker["id"] in billing_ids
    marker_ids = {item["id"] for item in markers}
    return {
        "markers": markers,
        "billingRowCount": len(billing_ids),
        "billingRowsWithoutMarker": sum(event_id not in marker_ids for event_id in billing_ids),
    }


def _github_deliveries(start: datetime, end: datetime, jwt_token: str,
                       fetch: Callable) -> list[dict]:
    url = "https://api.github.com/app/hook/deliveries?per_page=100"
    seen_urls = set()
    deliveries = []
    for _ in range(MAX_PAGES):
        if url in seen_urls:
            raise ValueError("GitHub pagination repeated a page")
        seen_urls.add(url)
        value, link = fetch(url, jwt_token, "github")
        if not isinstance(value, list):
            raise ValueError("GitHub delivery listing is malformed")  # noqa: TRY004 - malformed provider response
        for item in value:
            if not isinstance(item, dict) or type(item.get("id")) is not int or not isinstance(item.get("guid"), str) or not GITHUB_GUID.fullmatch(item["guid"]):
                raise ValueError("GitHub delivery ID is invalid")
            delivered_at = _utc(item.get("delivered_at"))
            if start <= delivered_at <= end:
                deliveries.append({
                    "id": item["id"], "guid": item["guid"],
                    "deliveredAtUTC": _iso(delivered_at),
                    "statusCode": item.get("status_code") if type(item.get("status_code")) is int else None,
                    "event": item.get("event") if isinstance(item.get("event"), str) else "unknown",
                    "action": item.get("action") if isinstance(item.get("action"), str) else None,
                    "redelivery": item.get("redelivery") is True,
                    "installationId": item.get("installation_id") if type(item.get("installation_id")) is int else None,
                    "repositoryId": item.get("repository_id") if type(item.get("repository_id")) is int else None,
                    "endpointOwner": "unknown",
                })
        next_url = _next_link(link)
        if next_url is None:
            return deliveries
        url = next_url
    raise ValueError("GitHub delivery pagination exceeded the safety limit")


def _github_endpoint_owners(deliveries: list[dict], jwt_token: str, fetch: Callable) -> None:
    for item in deliveries:
        # GitHub's delivery-detail response includes a body; discard it in
        # process memory and retain only the destination URL classification.
        value, _ = fetch(f"https://api.github.com/app/hook/deliveries/{item['id']}", jwt_token, "github")
        if not isinstance(value, dict):
            raise ValueError("GitHub delivery detail is malformed")  # noqa: TRY004 - malformed provider response
        item["endpointOwner"] = _owner(value.get("url", ""), "github")


def inventory(session: Any, start: datetime, end: datetime, table_name: str,
              fetch: Callable = _request_json) -> dict:
    if end <= start or end > datetime.now(UTC) + timedelta(minutes=2):
        raise ValueError("Inventory interval is invalid")
    if datetime.now(UTC) - start > timedelta(days=3):
        raise ValueError("GitHub's three-day history cannot cover this interval")
    stripe_key = _stripe_key(_secret(session, "heytim/stripe/production"))
    github_token = _github_jwt(_secret(session, "frogbot/oauth/github-production"))
    stripe_endpoint, _ = fetch(f"https://api.stripe.com/v1/webhook_endpoints/{STRIPE_ENDPOINT}", stripe_key, "stripe")
    if not isinstance(stripe_endpoint, dict) or stripe_endpoint.get("id") != STRIPE_ENDPOINT:
        raise ValueError("Stripe endpoint does not match")
    stripe_events = _stripe_events(start, end, stripe_key, fetch)
    undelivered = _stripe_events(start, end, stripe_key, fetch, undelivered=True)
    marker_presence = _stripe_marker_presence(session, table_name, [item["id"] for item in stripe_events])
    source_stripe_state = _source_stripe_state(session, table_name, stripe_key, fetch)
    undelivered_ids = {entry["id"] for entry in undelivered}
    for item in stripe_events:
        item["sourceMarkerPresent"] = marker_presence[item["id"]]
        item["undeliveredToSomeEndpoint"] = item["id"] in undelivered_ids
    github_config, _ = fetch("https://api.github.com/app/hook/config", github_token, "github")
    if not isinstance(github_config, dict):
        raise ValueError("GitHub App hook config is malformed")  # noqa: TRY004 - malformed provider response
    github_deliveries = _github_deliveries(start, end, github_token, fetch)
    _github_endpoint_owners(github_deliveries, github_token, fetch)
    return {
        "schemaVersion": 1,
        "status": "INVENTORY_ONLY",
        "observedAtUTC": _iso(datetime.now(UTC)),
        "interval": {"from": _iso(start), "through": _iso(end)},
        "sourceAccount": SOURCE_ACCOUNT,
        "stripe": {
            "endpointId": STRIPE_ENDPOINT, "currentEndpointOwner": _owner(stripe_endpoint.get("url", ""), "stripe"),
            "endpointStatus": stripe_endpoint.get("status") if isinstance(stripe_endpoint.get("status"), str) else "unknown",
            "enabledEventsMatch": set(stripe_endpoint.get("enabled_events", [])) == set(STRIPE_TYPES),
            "events": stripe_events,
            "sourceState": source_stripe_state,
            "createdEventListingComplete": True,
            "endpointAttemptListingComplete": False,
            "note": "Stripe Events covers creation time, not all retries during the interval; delivery_success=false is across endpoints, not this endpoint's attempt ledger.",
        },
        "github": {
            "appId": GITHUB_APP, "currentEndpointOwner": _owner(github_config.get("url", ""), "github"),
            "deliveries": github_deliveries,
            "deliveryListingCompleteWithinRetention": True,
        },
        "plaid": {
            "transactionDeliveryListingComplete": False,
            "reason": "Plaid webhook_events/list excludes TRANSACTIONS; recover only through per-Item transactions/sync after an authorized reconnect.",
        },
        "note": "Metadata-only read-only inventory; never a replay instruction or cutover authorization. No provider or AWS writes were made.",
    }


def _private_write(path: Path, value: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        offset = 0
        while offset < len(body):
            offset += os.write(fd, body[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--source-table", required=True)
    parser.add_argument("--from-utc", required=True)
    parser.add_argument("--through-utc", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        session = _source_session(args.profile)
        result = inventory(session, _utc(args.from_utc), _utc(args.through_utc), args.source_table)
        _private_write(args.output, result)
        print(json.dumps({
            "status": result["status"], "stripeCreatedEvents": len(result["stripe"]["events"]),
            "githubDeliveryAttempts": len(result["github"]["deliveries"]),
            "stripeEndpointAttemptsComplete": False,
            "plaidTransactionDeliveryListingComplete": False,
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, BotoCoreError, ClientError, json.JSONDecodeError) as exc:
        # Never echo API error bodies, credentials, payloads, or resource IDs.
        print(f"Provider-side inventory failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
