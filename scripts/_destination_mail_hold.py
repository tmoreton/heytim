"""Read-only proof that destination SNS mail delivery was held for 15 minutes.

The existing CloudFormation SNS-to-Lambda subscription must stay in place while
the private capture-only backend is reviewed. A matching SNS filter and Lambda
reserved concurrency of zero are required, along with older CloudTrail writes
that established both settings. This module never changes AWS resources.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from _source_mail_capture import active_store_only_match
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

ACCOUNT = "820323452649"
REGION = "us-east-1"
STACK = (
    "amplify-d17sj7dvhx07c-main-branch-9753991d3b-"
    "FrogBotAppE7B48881-1EYK8R7KWHYX9"
)
TOPIC_LOGICAL = "IncomingBotMailTopicBA1536B5"
SUBSCRIPTION_LOGICAL = "BotEmailReceiverIncomingBotMailTopicDC446F7D"
RECEIVER_LOGICAL = "BotEmailReceiver67BBC43A"
CAPTURE_STACK = "HeyTimDestinationMailCapture"
HOLD_FILTER = {
    "heytim_cutover_capture_hold": ["destination-820323452649-20260930"]
}
READ_CONFIG = Config(
    retries={"total_max_attempts": 2, "mode": "standard"},
    connect_timeout=5,
    read_timeout=15,
)
MIN_HOLD = timedelta(minutes=15)
LOOKBACK = timedelta(hours=24)


class HoldError(Exception):
    """A mail receiver hold could not be proven."""


def _single(resources: list[dict], logical: str, kind: str) -> str:
    found = [
        item.get("PhysicalResourceId")
        for item in resources
        if item.get("LogicalResourceId") == logical
        and item.get("ResourceType") == kind
    ]
    if len(found) != 1 or not isinstance(found[0], str) or not found[0]:
        raise HoldError(f"CloudFormation {logical} is missing or ambiguous")
    return found[0]


def _one_prefix(resources: list[dict], prefix: str, kind: str) -> str:
    found = [
        item.get("PhysicalResourceId")
        for item in resources
        if item.get("LogicalResourceId", "").startswith(prefix)
        and item.get("ResourceType") == kind
    ]
    if len(found) != 1 or not isinstance(found[0], str) or not found[0]:
        raise HoldError(f"CloudFormation {prefix} is missing or ambiguous")
    return found[0]


def _pages(client: Any, operation: str, result_key: str, **kwargs: Any) -> list[dict]:
    return [
        item
        for page in client.get_paginator(operation).paginate(**kwargs)
        for item in page.get(result_key, [])
    ]


def _event_request(item: dict) -> dict:
    try:
        event = json.loads(item["CloudTrailEvent"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HoldError("CloudTrail event could not be verified") from exc
    request = event.get("requestParameters")
    if not isinstance(request, dict):
        raise HoldError("CloudTrail request parameters are missing")
    return request


def _event_time(item: dict) -> datetime:
    value = item.get("EventTime")
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise HoldError("CloudTrail event time is missing")
    return value.astimezone(UTC)


def _filter_value(value: Any) -> bool:
    try:
        return json.loads(value) == HOLD_FILTER
    except (TypeError, ValueError):
        return False


def evaluate_events(
    events: list[dict], *, subscription_arn: str, receiver: str, now: datetime
) -> None:
    """Require old successful hold writes and no later relevant mutation."""
    filter_events: list[tuple[datetime, bool]] = []
    scope_events: list[tuple[datetime, bool]] = []
    concurrency_events: list[tuple[datetime, bool]] = []
    receiver_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{receiver}"
    for item in events:
        name = item.get("EventName")
        if name not in {
            "SetSubscriptionAttributes",
            "PutFunctionConcurrency",
            "DeleteFunctionConcurrency",
        }:
            continue
        request = _event_request(item)
        when = _event_time(item)
        if name == "SetSubscriptionAttributes":
            if request.get("subscriptionArn") != subscription_arn:
                continue
            attribute = request.get("attributeName")
            if attribute == "FilterPolicy":
                filter_events.append(
                    (when, _filter_value(request.get("attributeValue")))
                )
            elif attribute == "FilterPolicyScope":
                scope_events.append(
                    (when, request.get("attributeValue") == "MessageAttributes")
                )
        elif request.get("functionName") in {receiver, receiver_arn}:
            concurrency_events.append(
                (
                    when,
                    name == "PutFunctionConcurrency"
                    and request.get("reservedConcurrentExecutions") == 0,
                )
            )
    cutoff = now - MIN_HOLD
    for label, values, required in (
        ("SNS filter", filter_events, True),
        ("SNS filter scope", scope_events, False),
        ("Lambda concurrency", concurrency_events, True),
    ):
        if required and not values:
            raise HoldError(f"{label} hold event is absent from CloudTrail")
        if values:
            latest_time, latest_held = max(values, key=lambda entry: entry[0])
            if not latest_held or latest_time > cutoff:
                raise HoldError(f"{label} has not been stable for 15 minutes")


def check(session: Any, *, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    if session.region_name != REGION:
        raise HoldError("destination region mismatch")
    if session.client("sts", config=READ_CONFIG).get_caller_identity().get(
        "Account"
    ) != ACCOUNT:
        raise HoldError("destination account mismatch")
    cfn = session.client("cloudformation", config=READ_CONFIG)
    stack = cfn.describe_stacks(StackName=STACK).get("Stacks", [])
    expected_stack_arn = f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{STACK}/"
    if len(stack) != 1 or not stack[0].get("StackId", "").startswith(
        expected_stack_arn
    ):
        raise HoldError("destination app stack identity mismatch")
    resources = _pages(
        cfn, "list_stack_resources", "StackResourceSummaries", StackName=STACK
    )
    topic_arn = _single(resources, TOPIC_LOGICAL, "AWS::SNS::Topic")
    subscription_arn = _single(
        resources, SUBSCRIPTION_LOGICAL, "AWS::SNS::Subscription"
    )
    receiver = _single(resources, RECEIVER_LOGICAL, "AWS::Lambda::Function")
    if not topic_arn.startswith(f"arn:aws:sns:{REGION}:{ACCOUNT}:") or not (
        subscription_arn.startswith(f"arn:aws:sns:{REGION}:{ACCOUNT}:")
        and receiver.startswith("amplify-d17sj7dvhx07c-")
        and RECEIVER_LOGICAL in receiver
    ):
        raise HoldError("destination mail resource identity mismatch")

    ses = session.client("ses", config=READ_CONFIG)
    active = ses.describe_active_receipt_rule_set()
    if active.get("Metadata") or active.get("Rules"):
        capture_stack = cfn.describe_stacks(StackName=CAPTURE_STACK).get("Stacks", [])
        expected_capture_arn = (
            f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{CAPTURE_STACK}/"
        )
        if len(capture_stack) != 1 or not capture_stack[0].get(
            "StackId", ""
        ).startswith(expected_capture_arn):
            raise HoldError("destination standalone capture stack is not exact")
        capture_resources = _pages(
            cfn, "list_stack_resources", "StackResourceSummaries",
            StackName=CAPTURE_STACK,
        )
        bucket = _one_prefix(
            capture_resources, "BotEmailQuarantine", "AWS::S3::Bucket"
        )
        role_name = _one_prefix(resources, "BotEmailSesDeliveryRole", "AWS::IAM::Role")
        role_arn = session.client("iam", config=READ_CONFIG).get_role(
            RoleName=role_name
        )["Role"]["Arn"]
        receipt_rule = _one_prefix(
            resources, "BotEmailReceiptRule", "AWS::SES::ReceiptRule"
        )
        if (
            receipt_rule != "heytim-production-bot-mail|HeyTimBotInbox"
            or role_arn.split(":")[4] != ACCOUNT
            or not active_store_only_match(
                active,
                rule_set="heytim-production-bot-mail",
                rule_name="HeyTimBotInbox",
                bucket=bucket,
                topic_arn=topic_arn,
                role_arn=role_arn,
            )
        ):
            raise HoldError("destination active SES rule is not exact store-only capture")

    sns = session.client("sns", config=READ_CONFIG)
    receiver_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{receiver}"
    subscriptions = _pages(
        sns, "list_subscriptions_by_topic", "Subscriptions", TopicArn=topic_arn
    )
    lambdas = [item for item in subscriptions if item.get("Protocol") == "lambda"]
    if len(lambdas) != 1 or lambdas[0] != {
        "SubscriptionArn": subscription_arn,
        "Owner": ACCOUNT,
        "Protocol": "lambda",
        "Endpoint": receiver_arn,
        "TopicArn": topic_arn,
    }:
        raise HoldError("destination mail receiver subscription is not exact")
    attributes = sns.get_subscription_attributes(SubscriptionArn=subscription_arn)[
        "Attributes"
    ]
    if (
        attributes.get("TopicArn") != topic_arn
        or attributes.get("Endpoint") != receiver_arn
        or attributes.get("Protocol") != "lambda"
        or attributes.get("FilterPolicyScope") != "MessageAttributes"
        or not _filter_value(attributes.get("FilterPolicy"))
    ):
        raise HoldError("destination mail receiver filter is not held")
    concurrency = session.client("lambda", config=READ_CONFIG).get_function_concurrency(
        FunctionName=receiver
    )
    if concurrency.get("ReservedConcurrentExecutions") != 0:
        raise HoldError("destination mail receiver concurrency is not zero")

    cloudtrail = session.client("cloudtrail", config=READ_CONFIG)
    events: list[dict] = []
    for name in (
        "SetSubscriptionAttributes",
        "PutFunctionConcurrency",
        "DeleteFunctionConcurrency",
    ):
        events.extend(
            _pages(
                cloudtrail,
                "lookup_events",
                "Events",
                LookupAttributes=[{"AttributeKey": "EventName", "AttributeValue": name}],
                StartTime=now - LOOKBACK,
                EndTime=now,
            )
        )
    evaluate_events(
        events, subscription_arn=subscription_arn, receiver=receiver, now=now
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    args = parser.parse_args(argv)
    try:
        check(boto3.Session(profile_name=args.profile, region_name=REGION))
    except (HoldError, BotoCoreError, ClientError, NoCredentialsError) as exc:
        print(f"NO-GO: destination mail receiver hold: {exc}", file=sys.stderr)
        return 1
    print("Destination mail receiver filter and concurrency held for at least 15 minutes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
