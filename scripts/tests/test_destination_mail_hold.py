"""Destination mail hold requires exact live topology and aged CloudTrail writes."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _destination_mail_hold import (
    ACCOUNT,
    HOLD_FILTER,
    RECEIVER_LOGICAL,
    REGION,
    STACK,
    SUBSCRIPTION_LOGICAL,
    TOPIC_LOGICAL,
    HoldError,
    check,
    evaluate_events,
)

NOW = datetime(2026, 9, 30, 4, 0, tzinfo=UTC)
TOPIC = f"arn:aws:sns:{REGION}:{ACCOUNT}:mail-topic"
SUB = f"arn:aws:sns:{REGION}:{ACCOUNT}:mail-topic:subscription"
RECEIVER = f"amplify-d17sj7dvhx07c-mai-{RECEIVER_LOGICAL}-example"
RECEIVER_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{RECEIVER}"


def _event(name: str, request: dict, *, minutes_ago: int = 20) -> dict:
    return {
        "EventName": name,
        "EventTime": NOW - timedelta(minutes=minutes_ago),
        "CloudTrailEvent": json.dumps({"requestParameters": request}),
    }


def _events() -> list[dict]:
    return [
        _event(
            "SetSubscriptionAttributes",
            {
                "subscriptionArn": SUB,
                "attributeName": "FilterPolicy",
                "attributeValue": json.dumps(HOLD_FILTER),
            },
        ),
        _event(
            "PutFunctionConcurrency20171031",
            {"functionName": RECEIVER, "reservedConcurrentExecutions": 0},
        ),
    ]


class _Paginator:
    def __init__(self, client, name: str):
        self.client = client
        self.name = name

    def paginate(self, **kwargs):
        yield self.client.pages[self.name](kwargs)


class _Client:
    def __init__(self, **methods):
        self.methods = methods
        self.pages = {}

    def __getattr__(self, name):
        return self.methods[name]

    def get_paginator(self, name: str):
        return _Paginator(self, name)


class _Session:
    region_name = REGION

    def __init__(self, clients):
        self.clients = clients

    def client(self, name: str, **_kwargs):
        return self.clients[name]


def _session(
    *, filter_policy: dict = HOLD_FILTER, account: str = ACCOUNT,
    active_rule: dict | None = None,
):
    cfn = _Client(
        describe_stacks=lambda StackName: {
            "Stacks": [{
                "StackId": f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{StackName}/id"
            }]
        }
    )
    app_resources = [
        {"LogicalResourceId": TOPIC_LOGICAL, "ResourceType": "AWS::SNS::Topic", "PhysicalResourceId": TOPIC},
        {"LogicalResourceId": SUBSCRIPTION_LOGICAL, "ResourceType": "AWS::SNS::Subscription", "PhysicalResourceId": SUB},
        {"LogicalResourceId": RECEIVER_LOGICAL, "ResourceType": "AWS::Lambda::Function", "PhysicalResourceId": RECEIVER},
        {"LogicalResourceId": "BotEmailSesDeliveryRole123", "ResourceType": "AWS::IAM::Role", "PhysicalResourceId": "mail-role"},
        {"LogicalResourceId": "BotEmailReceiptRule123", "ResourceType": "AWS::SES::ReceiptRule", "PhysicalResourceId": "heytim-production-bot-mail|HeyTimBotInbox"},
    ]
    capture_resources = [
        {"LogicalResourceId": "BotEmailQuarantine123", "ResourceType": "AWS::S3::Bucket", "PhysicalResourceId": "quarantine-bucket"},
    ]
    cfn.pages["list_stack_resources"] = lambda kwargs: {
        "StackResourceSummaries": [
            *(app_resources if kwargs["StackName"] == STACK else capture_resources),
        ]
    }
    sns = _Client(
        get_subscription_attributes=lambda **_kwargs: {
            "Attributes": {
                "TopicArn": TOPIC,
                "Endpoint": RECEIVER_ARN,
                "Protocol": "lambda",
                "FilterPolicyScope": "MessageAttributes",
                "FilterPolicy": json.dumps(filter_policy),
            }
        }
    )
    sns.pages["list_subscriptions_by_topic"] = lambda _kwargs: {
        "Subscriptions": [{
            "SubscriptionArn": SUB,
            "Owner": ACCOUNT,
            "Protocol": "lambda",
            "Endpoint": RECEIVER_ARN,
            "TopicArn": TOPIC,
        }]
    }
    trail = _Client()
    trail.pages["lookup_events"] = lambda kwargs: {
        "Events": [
            event for event in _events()
            if event["EventName"] == kwargs["LookupAttributes"][0]["AttributeValue"]
        ]
    }
    return _Session({
        "sts": _Client(get_caller_identity=lambda: {"Account": account}),
        "cloudformation": cfn,
        "ses": _Client(describe_active_receipt_rule_set=lambda: active_rule or {}),
        "iam": _Client(get_role=lambda **_kwargs: {
            "Role": {"Arn": f"arn:aws:iam::{ACCOUNT}:role/mail-role"}
        }),
        "sns": sns,
        "lambda": _Client(get_function_concurrency=lambda **_kwargs: {
            "ReservedConcurrentExecutions": 0
        }),
        "cloudtrail": trail,
    })


def test_exact_aged_hold_passes() -> None:
    check(_session(), now=NOW)


def test_wrong_account_stops_before_resource_reads() -> None:
    with pytest.raises(HoldError, match="account mismatch"):
        check(_session(account="188757775631"), now=NOW)


def test_live_filter_must_be_exact() -> None:
    with pytest.raises(HoldError, match="filter is not held"):
        check(_session(filter_policy={}), now=NOW)


def test_exact_active_store_only_rule_is_allowed() -> None:
    active = {
        "Metadata": {"Name": "heytim-production-bot-mail"},
        "Rules": [{
            "Name": "HeyTimBotInbox",
            "Enabled": True,
            "ScanEnabled": True,
            "Recipients": ["bots.heytim.ai"],
            "Actions": [{"S3Action": {
                "BucketName": "quarantine-bucket",
                "ObjectKeyPrefix": "received/",
                "TopicArn": TOPIC,
                "IamRoleArn": f"arn:aws:iam::{ACCOUNT}:role/mail-role",
            }}],
        }],
    }
    check(_session(active_rule=active), now=NOW)
    active["Rules"][0]["Actions"] = [{"BounceAction": {}}]
    with pytest.raises(HoldError, match="not exact store-only capture"):
        check(_session(active_rule=active), now=NOW)


def test_new_hold_event_has_not_settled() -> None:
    events = _events()
    events[0] = _event(
        "SetSubscriptionAttributes",
        {
            "subscriptionArn": SUB,
            "attributeName": "FilterPolicy",
            "attributeValue": json.dumps(HOLD_FILTER),
        },
        minutes_ago=14,
    )
    with pytest.raises(HoldError, match="SNS filter has not been stable"):
        evaluate_events(events, subscription_arn=SUB, receiver=RECEIVER, now=NOW)


def test_released_concurrency_blocks_even_after_old_zero_write() -> None:
    events = _events() + [
        _event("DeleteFunctionConcurrency20171031", {"functionName": RECEIVER}, minutes_ago=5)
    ]
    with pytest.raises(HoldError, match="Lambda concurrency has not been stable"):
        evaluate_events(events, subscription_arn=SUB, receiver=RECEIVER, now=NOW)


def test_scope_change_in_settling_window_blocks() -> None:
    events = _events() + [
        _event(
            "SetSubscriptionAttributes",
            {
                "subscriptionArn": SUB,
                "attributeName": "FilterPolicyScope",
                "attributeValue": "MessageAttributes",
            },
            minutes_ago=2,
        )
    ]
    with pytest.raises(HoldError, match="SNS filter scope has not been stable"):
        evaluate_events(events, subscription_arn=SUB, receiver=RECEIVER, now=NOW)
