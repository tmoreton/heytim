"""Read-only source mail-capture inventory checks using in-memory AWS clients."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _source_mail_capture_preflight import inspect_mail_capture
from _source_writer_preflight_core import (
    SOURCE_ACCOUNT,
    SOURCE_REGION,
    Report,
    fingerprint,
)

BUCKET = "source-quarantine-raw-mail"
TOPIC = f"arn:aws:sns:{SOURCE_REGION}:{SOURCE_ACCOUNT}:source-mail"
SUBSCRIPTION = f"{TOPIC}:capture-subscription"
CAPTURE = f"arn:aws:sqs:{SOURCE_REGION}:{SOURCE_ACCOUNT}:source-capture"
FAILURES = f"arn:aws:sqs:{SOURCE_REGION}:{SOURCE_ACCOUNT}:source-failures"
CAPTURE_URL = (
    f"https://sqs.{SOURCE_REGION}.amazonaws.com/{SOURCE_ACCOUNT}/source-capture"
)
FAILURES_URL = (
    f"https://sqs.{SOURCE_REGION}.amazonaws.com/{SOURCE_ACCOUNT}/source-failures"
)
ROLE_NAME = "source-ses-role"
ROLE = f"arn:aws:iam::{SOURCE_ACCOUNT}:role/{ROLE_NAME}"
RECEIVER_NAME = "source-mail-receiver"
RECEIVER = f"arn:aws:lambda:{SOURCE_REGION}:{SOURCE_ACCOUNT}:function:{RECEIVER_NAME}"
RULE_SET = "source-set"
RULE_NAME = "HeyTimBotInbox"


def _resource(kind: str, logical: str, physical: str) -> dict[str, str]:
    return {
        "ResourceType": kind,
        "LogicalResourceId": f"{logical}ABC123",
        "PhysicalResourceId": physical,
    }


def _queue_policy(arn: str) -> str:
    return json.dumps(
        {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "sns.amazonaws.com"},
                    "Action": "sqs:SendMessage",
                    "Resource": arn,
                    "Condition": {
                        "ArnEquals": {"aws:SourceArn": TOPIC},
                        "StringEquals": {"aws:SourceAccount": SOURCE_ACCOUNT},
                    },
                }
            ]
        }
    )


def _queue_attributes(arn: str) -> dict[str, str]:
    return {
        "QueueArn": arn,
        "SqsManagedSseEnabled": "true",
        "MessageRetentionPeriod": "1209600",
        "Policy": _queue_policy(arn),
        "ApproximateNumberOfMessages": "0",
        "ApproximateNumberOfMessagesNotVisible": "0",
        "ApproximateNumberOfMessagesDelayed": "0",
    }


class Fixture:
    def __init__(self) -> None:
        self.resources = [
            _resource(
                "AWS::SES::ReceiptRule",
                "BotEmailReceiptRule",
                f"{RULE_SET}|{RULE_NAME}",
            ),
            _resource("AWS::SNS::Topic", "IncomingBotMailTopic", TOPIC),
            _resource(
                "AWS::SNS::Subscription",
                "BotEmailInboundCaptureSubscription",
                SUBSCRIPTION,
            ),
            _resource("AWS::IAM::Role", "BotEmailSesDeliveryRole", ROLE_NAME),
            _resource("AWS::Lambda::Function", "BotEmailReceiver", RECEIVER_NAME),
            _resource("AWS::S3::Bucket", "BotEmailQuarantine", BUCKET),
            _resource("AWS::SQS::Queue", "BotEmailInboundCapture", CAPTURE_URL),
            _resource(
                "AWS::SQS::Queue", "BotEmailInboundCaptureFailures", FAILURES_URL
            ),
        ]
        self.rule = {
            "Name": RULE_NAME,
            "Enabled": True,
            "ScanEnabled": True,
            "Recipients": ["bots.heytim.ai"],
            "Actions": [
                {
                    "S3Action": {
                        "BucketName": BUCKET,
                        "ObjectKeyPrefix": "received/",
                        "TopicArn": TOPIC,
                        "IamRoleArn": ROLE,
                    }
                }
            ],
        }
        self.active = {"Metadata": {"Name": RULE_SET}, "Rules": [self.rule]}
        self.role = {
            "RoleName": ROLE_NAME,
            "Arn": ROLE,
            "AssumeRolePolicyDocument": {
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ses.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                        "Condition": {
                            "StringEquals": {
                                "aws:SourceAccount": SOURCE_ACCOUNT,
                                "aws:SourceArn": (
                                    f"arn:aws:ses:{SOURCE_REGION}:{SOURCE_ACCOUNT}:"
                                    f"receipt-rule-set/{RULE_SET}:receipt-rule/{RULE_NAME}"
                                ),
                            }
                        },
                    }
                ]
            },
        }
        self.subscription = {
            "SubscriptionArn": SUBSCRIPTION,
            "TopicArn": TOPIC,
            "Protocol": "sqs",
            "Endpoint": CAPTURE,
        }
        self.subscriptions = [self.subscription]
        self.subscription_attributes = {
            **self.subscription,
            "RawMessageDelivery": "false",
            "RedrivePolicy": json.dumps({"deadLetterTargetArn": FAILURES}),
        }
        self.queues = {
            CAPTURE_URL: _queue_attributes(CAPTURE),
            FAILURES_URL: _queue_attributes(FAILURES),
        }
        self.location: dict[str, Any] = {"LocationConstraint": SOURCE_REGION}
        self.encryption = {
            "ServerSideEncryptionConfiguration": {
                "Rules": [
                    {
                        "ApplyServerSideEncryptionByDefault": {
                            "SSEAlgorithm": "AES256"
                        },
                        "BucketKeyEnabled": False,
                    }
                ]
            }
        }
        self.public = {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        }
        self.lifecycle = {"Rules": [{"Status": "Enabled", "Expiration": {"Days": 14}}]}
        self.policy = {
            "Statement": [
                {
                    "Sid": "EnforceSSL",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "s3:*",
                    "Resource": [f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"],
                    "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                }
            ]
        }
        self.bucket_names = {
            "inbound_mail": "source-live-mail",
            "inbound_quarantine": BUCKET,
        }
        self.queue_arns = {
            "inbound_capture": CAPTURE,
            "inbound_capture_failures": FAILURES,
        }

    def get_role(self, *, RoleName: str) -> dict:
        assert RoleName == ROLE_NAME
        return {"Role": self.role}

    def describe_active_receipt_rule_set(self) -> dict:
        return self.active

    def can_paginate(self, operation: str) -> bool:
        return operation == "list_subscriptions_by_topic"

    def get_paginator(self, operation: str) -> Fixture:
        assert operation == "list_subscriptions_by_topic"
        return self

    def paginate(self, *, TopicArn: str) -> list[dict]:
        assert TopicArn == TOPIC
        return [{"Subscriptions": self.subscriptions}]

    def get_subscription_attributes(self, *, SubscriptionArn: str) -> dict:
        assert SubscriptionArn == SUBSCRIPTION
        return {"Attributes": self.subscription_attributes}

    def get_queue_attributes(self, *, QueueUrl: str, AttributeNames: list[str]) -> dict:
        assert AttributeNames == ["All"]
        return {"Attributes": self.queues[QueueUrl]}

    def _owner(self, values: dict) -> None:
        assert values == {"Bucket": BUCKET, "ExpectedBucketOwner": SOURCE_ACCOUNT}

    def head_bucket(self, **values: str) -> dict:
        self._owner(values)
        return {}

    def get_bucket_location(self, **values: str) -> dict:
        self._owner(values)
        return self.location

    def get_bucket_encryption(self, **values: str) -> dict:
        self._owner(values)
        return self.encryption

    def get_public_access_block(self, **values: str) -> dict:
        self._owner(values)
        return self.public

    def get_bucket_lifecycle_configuration(self, **values: str) -> dict:
        self._owner(values)
        return self.lifecycle

    def get_bucket_policy(self, **values: str) -> dict:
        self._owner(values)
        return {"Policy": json.dumps(self.policy)}

    def inspect(self) -> Report:
        report = Report()
        inspect_mail_capture(
            report,
            self.resources,
            self,
            self,
            self,
            self,
            self,
            self.bucket_names,
            self.queue_arns,
        )
        return report


def test_exact_store_only_capture_is_ready_and_sanitized() -> None:
    fixture = Fixture()
    report = fixture.inspect()
    assert not report.blockers
    checks = {item["label"]: item for item in report.checks}
    assert checks["receipt_rule"]["matching_source_rules"] == 1
    assert checks["receipt_rule"]["enabled"] == 1
    assert checks["bucket_inbound_quarantine"]["id_sha256_12"] == fingerprint(BUCKET)
    capture = checks["mail_capture"]
    assert capture["state"] == "READY"
    assert capture["bucket_sha256_12"] == fingerprint(BUCKET)
    assert capture["topic_arn_sha256_12"] == fingerprint(TOPIC)
    assert capture["subscription_arn_sha256_12"] == fingerprint(SUBSCRIPTION)
    assert capture["queue_arn_sha256_12"] == fingerprint(CAPTURE)
    assert capture["failure_queue_arn_sha256_12"] == fingerprint(FAILURES)
    assert capture["role_arn_sha256_12"] == fingerprint(ROLE)
    encoded = json.dumps(report.data())
    assert BUCKET not in encoded and TOPIC not in encoded and ROLE not in encoded


def test_capture_queue_may_hold_mail_and_known_noop_lambda_may_subscribe() -> None:
    fixture = Fixture()
    fixture.queues[CAPTURE_URL]["ApproximateNumberOfMessages"] = "8"
    fixture.subscriptions.append(
        {
            "SubscriptionArn": f"{TOPIC}:receiver-subscription",
            "TopicArn": TOPIC,
            "Protocol": "lambda",
            "Endpoint": RECEIVER,
        }
    )
    assert not fixture.inspect().blockers


@pytest.mark.parametrize("kind", ["other_lambda", "extra_sqs", "pending_lambda"])
def test_unknown_or_extra_subscriber_blocks(kind: str) -> None:
    fixture = Fixture()
    other = {
        "SubscriptionArn": f"{TOPIC}:other",
        "TopicArn": TOPIC,
        "Protocol": "lambda",
        "Endpoint": RECEIVER if kind == "pending_lambda" else RECEIVER + "-other",
    }
    if kind == "extra_sqs":
        other["Protocol"] = "sqs"
        other["Endpoint"] = CAPTURE
    if kind == "pending_lambda":
        other["SubscriptionArn"] = "PendingConfirmation"
    fixture.subscriptions.append(other)
    assert "mail_capture_not_ready" in fixture.inspect().blockers


def test_ses_rule_and_role_must_match_source_quarantine() -> None:
    fixture = Fixture()
    fixture.rule["Actions"][0]["S3Action"]["BucketName"] = "old-mail-bucket"
    assert "mail_capture_not_ready" in fixture.inspect().blockers
    fixture = Fixture()
    fixture.active["Rules"].append(
        {
            "Name": "Catchall",
            "Enabled": True,
            "Recipients": [],
            "Actions": [{"StopAction": {"Scope": "RuleSet"}}],
        }
    )
    assert "mail_capture_not_ready" in fixture.inspect().blockers
    fixture = Fixture()
    fixture.role["AssumeRolePolicyDocument"]["Statement"][0]["Condition"][
        "StringEquals"
    ]["aws:SourceAccount"] = "820323452649"
    assert "mail_capture_not_ready" in fixture.inspect().blockers


@pytest.mark.parametrize(
    "field,value",
    [
        ("RawMessageDelivery", "true"),
        ("RedrivePolicy", "{}"),
        ("Endpoint", FAILURES),
    ],
)
def test_subscription_must_be_sqs_envelope_with_exact_redrive(
    field: str, value: str
) -> None:
    fixture = Fixture()
    fixture.subscription_attributes[field] = value
    assert "mail_capture_not_ready" in fixture.inspect().blockers


@pytest.mark.parametrize(
    "kind",
    [
        "broad_policy",
        "extra_broad_policy",
        "short_retention",
        "no_sse",
        "missing_count",
        "dlq_nonempty",
    ],
)
def test_queue_security_retention_and_dlq_gate(kind: str) -> None:
    fixture = Fixture()
    if kind == "broad_policy":
        policy = json.loads(fixture.queues[CAPTURE_URL]["Policy"])
        policy["Statement"][0]["Condition"]["StringEquals"] = {}
        fixture.queues[CAPTURE_URL]["Policy"] = json.dumps(policy)
    elif kind == "extra_broad_policy":
        policy = json.loads(fixture.queues[CAPTURE_URL]["Policy"])
        policy["Statement"].append(
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "sqs:SendMessage",
                "Resource": CAPTURE,
            }
        )
        fixture.queues[CAPTURE_URL]["Policy"] = json.dumps(policy)
    elif kind == "short_retention":
        fixture.queues[CAPTURE_URL]["MessageRetentionPeriod"] = "345600"
    elif kind == "no_sse":
        fixture.queues[CAPTURE_URL]["SqsManagedSseEnabled"] = "false"
    elif kind == "missing_count":
        del fixture.queues[CAPTURE_URL]["ApproximateNumberOfMessages"]
    else:
        fixture.queues[FAILURES_URL]["ApproximateNumberOfMessages"] = "1"
    assert "mail_capture_not_ready" in fixture.inspect().blockers


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_region",
        "no_sse",
        "public",
        "short_lifecycle",
        "no_tls",
        "frozen",
        "conditional_put_deny",
    ],
)
def test_quarantine_bucket_must_be_private_retained_and_writable(kind: str) -> None:
    fixture = Fixture()
    if kind == "wrong_region":
        fixture.location["LocationConstraint"] = "us-west-2"
    elif kind == "no_sse":
        fixture.encryption["ServerSideEncryptionConfiguration"]["Rules"][0][
            "ApplyServerSideEncryptionByDefault"
        ]["SSEAlgorithm"] = "aws:kms"
    elif kind == "public":
        fixture.public["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] = False
    elif kind == "short_lifecycle":
        fixture.lifecycle["Rules"][0]["Expiration"]["Days"] = 7
    elif kind == "no_tls":
        fixture.policy["Statement"] = []
    elif kind == "conditional_put_deny":
        fixture.policy["Statement"].append(
            {
                "Sid": "OtherPutDeny",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:PutObject",
                "Resource": f"arn:aws:s3:::{BUCKET}/received/*",
                "Condition": {"StringEquals": {"aws:SourceAccount": SOURCE_ACCOUNT}},
            }
        )
    else:
        fixture.policy["Statement"].append(
            {
                "Sid": "HeyTimSourceWriteFreeze",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:PutObject*",
                "Resource": f"arn:aws:s3:::{BUCKET}/*",
            }
        )
    assert "mail_capture_not_ready" in fixture.inspect().blockers


def test_quarantine_disabled_lifecycle_is_safe() -> None:
    fixture = Fixture()
    fixture.lifecycle["Rules"][0]["Status"] = "Disabled"
    assert not fixture.inspect().blockers


def test_missing_cfn_resource_fails_closed_without_aws_calls() -> None:
    fixture = Fixture()
    fixture.resources = [
        item
        for item in fixture.resources
        if item["ResourceType"] != "AWS::SNS::Subscription"
    ]
    report = fixture.inspect()
    assert "mail_capture_resource_inventory_incomplete" in report.blockers
    assert {item["label"]: item for item in report.checks}["mail_capture"][
        "state"
    ] == "BLOCKED"


def test_wrong_cfn_identity_fails_closed() -> None:
    fixture = Fixture()
    fixture.queue_arns["inbound_capture"] = CAPTURE.replace(
        SOURCE_ACCOUNT, "820323452649"
    )
    assert "mail_capture_not_ready" in fixture.inspect().blockers
    fixture = Fixture()
    fixture.bucket_names["inbound_quarantine"] = "wrong-bucket"
    assert "mail_capture_not_ready" in fixture.inspect().blockers
