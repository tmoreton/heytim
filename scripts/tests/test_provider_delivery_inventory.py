"""Metadata-only provider inventory tests with fake AWS clients."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from provider_delivery_inventory import (
    DESTINATION_ACCOUNT, REGION, SOURCE_ACCOUNT, _private_identities, inventory,
)


class FakePaginator:
    def __init__(self, operation: str):
        self.operation = operation

    def paginate(self, **kwargs):
        assert "ProjectionExpression" in kwargs
        assert "body" not in kwargs["ProjectionExpression"]
        if self.operation == "scan":
            return [{"Items": [
                {"entity": {"S": "STRIPE_EVENT"}},
                {"entity": {"S": "BILLING"}, "provider": {"S": "stripe"}},
                {"entity": {"S": "CONNECTION"}, "provider": {"S": "plaid"}},
                {"entity": {"S": "PLAID_ITEM_MAPPING"}},
                {"entity": {"S": "GITHUB_ROUTINE_SUBSCRIPTION"}},
            ]}]
        if kwargs["ProjectionExpression"] == "#entity":
            return [{"Items": [{"entity": {"S": "GITHUB_ROUTINE_SUBSCRIPTION"}}]}]
        return [{"Items": [{
            "entity": {"S": "GROUP_MESSAGE"},
            "eventType": {"S": "github.issue.opened"},
            "eventId": {"S": "delivery-12345678"},
            "routineId": {"S": "routine-1"},
        }]}]


class FakeDynamo:
    def __init__(self, account: str):
        self.account = account
        self.reads = []

    def describe_table(self, **kwargs):
        return {"Table": {"TableName": kwargs["TableName"],
                          "TableArn": f"arn:aws:dynamodb:{REGION}:{self.account}:table/{kwargs['TableName']}",
                          "ItemCount": 5}}

    def get_paginator(self, operation):
        assert operation in {"scan", "query"}
        return FakePaginator(operation)

    def get_item(self, **kwargs):
        self.reads.append(kwargs)
        assert kwargs["ConsistentRead"] is True
        assert "ProjectionExpression" in kwargs
        assert "body" not in kwargs["ProjectionExpression"]
        key = kwargs["Key"]
        if key["pk"]["S"] == "SYSTEM#STRIPE_EVENT":
            return {"Item": {"entity": {"S": "STRIPE_EVENT"}}}
        if key["sk"]["S"] == "BILLING":
            return {"Item": {"entity": {"S": "BILLING"}, "provider": {"S": "stripe"}}}
        if key["pk"]["S"].startswith("PLAID_ITEM#"):
            return {"Item": {"entity": {"S": "PLAID_ITEM_MAPPING"}}}
        if key["sk"]["S"].startswith("PLAID_SYNC#"):
            return {"Item": {"entity": {"S": "PLAID_SYNC"}, "status": {"S": "ready"},
                             "revision": {"N": "3"}, "webhookConfigured": {"BOOL": True}}}
        return {}


class FakeSQS:
    def get_queue_attributes(self, **kwargs):
        assert kwargs["AttributeNames"]
        return {"Attributes": {
            "QueueArn": f"arn:aws:sqs:{REGION}:{DESTINATION_ACCOUNT}:jobs",
            "ApproximateNumberOfMessages": "0", "ApproximateNumberOfMessagesDelayed": "0",
            "ApproximateNumberOfMessagesNotVisible": "1",
        }}


class FakeSession:
    region_name = REGION

    def __init__(self, actual: str):
        self.actual = actual
        self.called = []
        self.ddb = FakeDynamo(actual)

    def client(self, service: str, **kwargs):
        self.called.append(service)
        if service == "sts":
            return self
        if service == "dynamodb":
            return self.ddb
        if service == "sqs":
            return FakeSQS()
        raise AssertionError(service)

    def get_caller_identity(self):
        return {"Account": self.actual}


def test_wrong_account_stops_before_dynamodb() -> None:
    session = FakeSession(SOURCE_ACCOUNT)
    with pytest.raises(ValueError, match="account mismatch"):
        inventory(session, DESTINATION_ACCOUNT, "Data", _private_identities(None))
    assert session.called == ["sts"]


def test_inventory_projects_metadata_and_reports_exact_checks_without_ids() -> None:
    session = FakeSession(DESTINATION_ACCOUNT)
    ids = {
        "stripeEvents": [{"id": "evt_123456789"}],
        "stripeBilling": [{"userId": "owner-1"}],
        "githubIndexes": [{"installationId": "123", "repositoryId": "456"}],
        "githubMessages": [{"groupId": "group-1", "deliveryId": "delivery-12345678", "routineId": "routine-1"}],
        "plaidItems": [{"environment": "production", "itemId": "item_12345678"}],
        "plaidSync": [{"userId": "owner-1", "connectionId": "connection_1234567890abcdef1234"}],
    }
    result = inventory(session, DESTINATION_ACCOUNT, "Data", ids, "https://sqs.example.invalid/jobs")
    assert result["status"] == "INVENTORY_ONLY"
    assert result["projectedCounts"]["plaid_connections"] == 1
    assert result["exactChecks"]["stripeEvents"] == [{"markerPresent": True}]
    assert result["exactChecks"]["githubMessages"] == [{"matchingMessageCount": 1}]
    assert result["exactChecks"]["plaidSync"][0]["revision"] == 3
    assert result["jobsQueue"]["inFlightApproximate"] == 1
    output = json.dumps(result)
    assert "item_12345678" not in output and "owner-1" not in output
    assert len(session.ddb.reads) == 4


def test_identity_file_is_private_and_rejects_payloads() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "identities.json"
        path.write_text('{"stripeEvents":[{"id":"evt_123456789"}]}')
        os.chmod(path, 0o600)
        assert _private_identities(path)["stripeEvents"] == [{"id": "evt_123456789"}]
        path.write_text('{"stripeEvents":[],"rawBody":"secret"}')
        with pytest.raises(ValueError, match="unapproved"):
            _private_identities(path)
        os.chmod(path, 0o644)
        with pytest.raises(ValueError, match="0600"):
            _private_identities(path)
