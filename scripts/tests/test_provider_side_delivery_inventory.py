"""Read-only provider-side delivery inventory tests."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import provider_side_delivery_inventory as provider


def test_pagination_and_safe_metadata_projection(monkeypatch) -> None:
    end = datetime.now(UTC) - timedelta(minutes=1)
    start = end - timedelta(hours=2)
    calls = []
    monkeypatch.setattr(provider, "_secret", lambda _session, name: {"secretKey": "sk_live_fake"} if "stripe" in name else {"appId": provider.GITHUB_APP, "privateKey": "unprinted"})
    monkeypatch.setattr(provider, "_github_jwt", lambda _secret: "unprinted-jwt")
    monkeypatch.setattr(provider, "_stripe_marker_presence", lambda _session, _table, ids: {event_id: True for event_id in ids})
    monkeypatch.setattr(provider, "_source_stripe_state", lambda _session, _table, _key, _fetch: {
        "markers": [], "billingRowCount": 0, "billingRowsWithoutMarker": 0,
    })

    def fetch(url, token, service):
        calls.append((url, service))
        assert token in {"sk_live_fake", "unprinted-jwt"}
        if "/webhook_endpoints/" in url:
            return {"id": provider.STRIPE_ENDPOINT, "url": provider.SOURCE_STRIPE_URL,
                    "status": "enabled", "enabled_events": list(provider.STRIPE_TYPES),
                    "secret": "should-not-appear"}, None
        if "/v1/events?" in url:
            if "delivery_success=false" in url:
                return {"data": [], "has_more": False}, None
            if "starting_after=" in url:
                return {"data": [], "has_more": False}, None
            return {"data": [{
                "id": "evt_123456789", "type": provider.STRIPE_TYPES[0],
                "created": int(start.timestamp()) + 60, "livemode": True,
                "pending_webhooks": 0,
                "data": {"object": {"client_secret": "should-not-appear"}},
            }], "has_more": True}, None
        if url.endswith("/app/hook/config"):
            return {"url": provider.SOURCE_GITHUB_URL, "secret": "should-not-appear"}, None
        if "/app/hook/deliveries/" in url:
            return {"url": provider.SOURCE_GITHUB_URL,
                    "request": {"payload": {"body": "should-not-appear"}}}, None
        if "/app/hook/deliveries?" in url:
            return [{
                "id": 12345678, "guid": "123e4567-e89b-12d3-a456-426614174000",
                "delivered_at": provider._iso(start + timedelta(minutes=3)),
                "status_code": 202, "event": "issues", "action": "opened",
                "installation_id": 101, "repository_id": 202,
                "request": {"payload": {"body": "should-not-appear"}},
            }], None
        raise AssertionError(url)

    result = provider.inventory(object(), start, end, "Data", fetch)
    assert result["stripe"]["events"][0]["sourceMarkerPresent"] is True
    assert result["stripe"]["events"][0]["undeliveredToSomeEndpoint"] is False
    assert result["github"]["deliveries"][0]["endpointOwner"] == "source"
    assert result["stripe"]["endpointAttemptListingComplete"] is False
    assert result["plaid"]["transactionDeliveryListingComplete"] is False
    serialized = json.dumps(result)
    assert "should-not-appear" not in serialized
    assert "sk_live_fake" not in serialized
    assert "unprinted-jwt" not in serialized
    assert len(calls) == 7


def test_source_marker_reconciliation_projects_only_metadata() -> None:
    class Paginator:
        def __init__(self, operation):
            self.operation = operation

        def paginate(self, **kwargs):
            assert "ProjectionExpression" in kwargs
            if self.operation == "query":
                return [{"Items": [{"sk": {"S": "EVENT#evt_123456789"},
                                    "entity": {"S": "STRIPE_EVENT"},
                                    "eventType": {"S": "customer.subscription.updated"}}]}]
            return [{"Items": [{"entity": {"S": "BILLING"},
                                "provider": {"S": "stripe"},
                                "stripeEventId": {"S": "evt_123456789"}}]}]

    class Table:
        def describe_table(self, **kwargs):
            return {"Table": {"TableName": kwargs["TableName"],
                              "TableArn": f"arn:aws:dynamodb:us-east-1:{provider.SOURCE_ACCOUNT}:table/{kwargs['TableName']}"}}

        def get_paginator(self, operation):
            return Paginator(operation)

    class Session:
        def client(self, name, **_kwargs):
            assert name == "dynamodb"
            return Table()

    def fetch(url, token, service):
        assert url == "https://api.stripe.com/v1/events/evt_123456789"
        assert token == "unprinted-key" and service == "stripe"
        return {"id": "evt_123456789", "type": "customer.subscription.updated",
                "created": 1_800_000_000, "data": {"object": {"secret": "should-not-appear"}}}, None

    state = provider._source_stripe_state(Session(), "Data", "unprinted-key", fetch)
    assert state["markers"][0]["providerEventFound"] is True
    assert state["markers"][0]["typeMatches"] is True
    assert state["markers"][0]["linkedToBilling"] is True
    assert state["billingRowsWithoutMarker"] == 0
    assert "should-not-appear" not in json.dumps(state)


def test_stripe_and_github_page_safety() -> None:
    end = datetime.now(UTC)
    start = end - timedelta(minutes=5)
    with pytest.raises(ValueError, match="repeated an event"):
        provider._stripe_events(start, end, "key", lambda *_: ({
            "data": [{"id": "evt_123456789", "type": provider.STRIPE_TYPES[0],
                      "created": int(start.timestamp()), "livemode": True}],
            "has_more": True,
        }, None))
    with pytest.raises(ValueError, match="not allowlisted"):
        provider._next_link('<https://evil.example/app/hook/deliveries>; rel="next"')
    with pytest.raises(ValueError, match="not allowlisted"):
        provider._request_json("https://evil.example/v1/events", "secret", "stripe")


def test_private_output_is_mode_0600_and_no_overwrite() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "metadata.json"
        provider._private_write(path, {"status": "INVENTORY_ONLY"})
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        with pytest.raises(FileExistsError):
            provider._private_write(path, {"status": "changed"})
        assert json.loads(path.read_text())["status"] == "INVENTORY_ONLY"
