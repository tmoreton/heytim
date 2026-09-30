"""Safety tests for the read-only source writer preflight."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _source_writer_bucket_probe import inspect_runtime_bucket
from _source_writer_cli_transport import CliError, CliSession, GuardedSession
from _source_writer_preflight_core import (
    EXPECTED,
    SOURCE_ACCOUNT,
    SOURCE_REGION,
    Report,
    has_freeze_deny,
    inspect_email_and_logs,
    inspect_queues,
    read,
)
from source_writer_preflight import inventory


class WrongAccountSession:
    region_name = SOURCE_REGION

    def __init__(self) -> None:
        self.clients: list[str] = []

    def client(self, name: str, **_kwargs: object) -> object:
        self.clients.append(name)
        if name != "sts":
            raise AssertionError("A wrong account must not be inventoried")
        return self

    def get_caller_identity(self) -> dict[str, str]:
        return {"Account": "820323452649"}


def test_wrong_account_stops_before_any_service_inventory() -> None:
    session = WrongAccountSession()
    report = inventory(session, "ignored-stack")
    assert session.clients == ["sts"]
    assert "source_account_or_region_mismatch" in report.blockers
    assert SOURCE_ACCOUNT == "188757775631"


def test_mail_capture_queue_may_hold_notifications_but_its_dlq_must_be_empty() -> None:
    class Queues:
        def get_queue_attributes(self, *, QueueUrl: str, AttributeNames: list[str]) -> dict:
            assert len(AttributeNames) == 4
            count = "3" if QueueUrl.endswith("BotEmailInboundCapture") else "0"
            return {"Attributes": {
                "QueueArn": f"arn:aws:sqs:{SOURCE_REGION}:{SOURCE_ACCOUNT}:{QueueUrl}",
                "ApproximateNumberOfMessages": count,
                "ApproximateNumberOfMessagesNotVisible": "0",
                "ApproximateNumberOfMessagesDelayed": "0",
            }}

    resources = [
        {
            "ResourceType": "AWS::SQS::Queue",
            "LogicalResourceId": f"{logical}1234",
            "PhysicalResourceId": logical,
        }
        for logical in EXPECTED["queue"].values()
    ]
    report = Report()
    inspect_queues(report, resources, Queues())
    assert not report.blockers

    resources[-1]["PhysicalResourceId"] = "BotEmailInboundCapture"
    report = Report()
    inspect_queues(report, resources, Queues())
    assert "queue_inbound_capture_failures_not_drained" in report.blockers


def test_active_ses_rule_accepts_both_cloudformation_physical_id_forms() -> None:
    class SES:
        def __init__(self, enabled: bool) -> None:
            self.enabled = enabled

        def describe_active_receipt_rule_set(self) -> dict:
            return {
                "Metadata": {"Name": "inboxai-inboxai-cc"},
                "Rules": [{"Name": "HeyTimBotInbox", "Enabled": self.enabled}],
            }

    for physical_id in (
        "HeyTimBotInbox",
        "inboxai-inboxai-cc|HeyTimBotInbox",
    ):
        resources = [{
            "ResourceType": "AWS::SES::ReceiptRule",
            "LogicalResourceId": "BotEmailReceiptRule1234",
            "PhysicalResourceId": physical_id,
        }]
        report = Report()
        inspect_email_and_logs(report, resources, SES(True), object())
        assert "receipt_rule_not_proven_enabled" not in report.blockers
        assert any(
            check.get("label") == "receipt_rule"
            and check.get("matching_source_rules") == 1
            and check.get("enabled") == 1
            for check in report.checks
        )

        disabled_report = Report()
        inspect_email_and_logs(disabled_report, resources, SES(False), object())
        assert "receipt_rule_not_proven_enabled" in disabled_report.blockers

    mismatched = [{
        "ResourceType": "AWS::SES::ReceiptRule",
        "LogicalResourceId": "BotEmailReceiptRule1234",
        "PhysicalResourceId": "other-set|HeyTimBotInbox",
    }]
    report = Report()
    inspect_email_and_logs(report, mismatched, SES(True), object())
    assert "receipt_rule_not_proven_enabled" in report.blockers


def test_freeze_deny_requires_exact_unconditional_coverage() -> None:
    arn = "arn:aws:dynamodb:us-east-1:188757775631:table/example"
    actions = {"dynamodb:PutItem", "dynamodb:DeleteItem"}
    statement = {
        "Sid": "HeyTimSourceWriteFreeze",
        "Effect": "Deny",
        "Principal": "*",
        "Action": sorted(actions),
        "Resource": arn,
    }
    assert has_freeze_deny({"Statement": [statement]}, arn, actions)
    assert not has_freeze_deny({"Statement": [statement]}, arn + "-other", actions)
    assert not has_freeze_deny(
        {"Statement": [{**statement, "Condition": {}}]}, arn, actions
    )
    assert not has_freeze_deny(
        {"Statement": [{**statement, "Action": "dynamodb:PutItem"}]}, arn, actions
    )


def test_api_error_message_is_not_in_evidence() -> None:
    report = Report()

    def denied() -> object:
        raise ClientError(
            {
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "secret-customer-value",
                }
            },
            "DescribeTable",
        )

    assert read(report, "table_application", denied) is None
    encoded = json.dumps(report.data())
    assert "secret-customer-value" not in encoded
    assert "AccessDeniedException" in encoded
    assert "table_application_unreadable" in report.blockers


def test_both_transports_reject_write_operations_before_calling_aws() -> None:
    cli = CliSession("default", SOURCE_REGION).client("s3")
    try:
        cli.put_object(Bucket="bucket", Key="key", Body="value")
    except CliError as error:
        assert error.code == "OperationNotReadOnly"
    else:
        raise AssertionError("CLI transport allowed a write")

    class FakeBotoSession:
        region_name = SOURCE_REGION

        def client(self, _service: str, **_kwargs: object) -> object:
            return self

        def put_object(self, **_kwargs: object) -> object:
            raise AssertionError("AWS write was called")

    guarded = GuardedSession(FakeBotoSession()).client("s3")
    try:
        guarded.put_object(Bucket="bucket", Key="key", Body="value")
    except CliError as error:
        assert error.code == "OperationNotReadOnly"
    else:
        raise AssertionError("SDK transport allowed a write")


def test_runtime_bucket_inventory_fails_closed_and_sanitizes_object_keys() -> None:
    class FakePaginator:
        def paginate(self, **_kwargs: object) -> list[dict]:
            return [
                {
                    "Versions": [{"Key": "users/private-person/secret.jpg"}],
                    "DeleteMarkers": [{"Key": "groups/private-group/old.txt"}],
                }
            ]

    class FakeS3:
        def head_bucket(self, **kwargs: object) -> dict:
            assert kwargs["ExpectedBucketOwner"] == SOURCE_ACCOUNT
            return {}

        def get_bucket_location(self, **_kwargs: object) -> dict:
            return {"LocationConstraint": None}

        def get_bucket_versioning(self, **_kwargs: object) -> dict:
            return {"Status": "Enabled"}

        def get_bucket_lifecycle_configuration(self, **_kwargs: object) -> dict:
            return {"Rules": [{"Status": "Enabled"}]}

        def get_bucket_replication(self, **_kwargs: object) -> dict:
            raise ClientError(
                {"Error": {"Code": "ReplicationConfigurationNotFoundError"}},
                "GetBucketReplication",
            )

        def get_bucket_policy(self, **_kwargs: object) -> dict:
            raise ClientError(
                {"Error": {"Code": "NoSuchBucketPolicy"}}, "GetBucketPolicy"
            )

        def can_paginate(self, _operation: str) -> bool:
            return True

        def get_paginator(self, _operation: str) -> FakePaginator:
            return FakePaginator()

    report = Report()
    inspect_runtime_bucket(
        report, FakeS3(), "unexpected-bucket", {"files": "expected-bucket"}
    )
    encoded = json.dumps(report.data())
    assert "agentcore_runtime_bucket_outside_stack" in report.blockers
    assert "agentcore_runtime_bucket_not_frozen" in report.blockers
    assert "private-person" not in encoded
    assert "secret.jpg" not in encoded
    assert '"versions": 1' in encoded
    assert '"delete_markers": 1' in encoded
