"""Exact-account AWS reads for the private bot-mail overlap review."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import boto3
from _bot_email_replay_mime import MAX_MIME_BYTES
from _bot_email_replay_plan import (
    DESTINATION_ACCOUNT,
    REGION,
    SOURCE_ACCOUNT,
    ReplayError,
    digest,
    parse_capture,
)
from boto3.dynamodb.conditions import Attr


def write_private(path: Path, value: dict) -> None:
    if not path.is_absolute():
        raise ReplayError("Private manifest path must be absolute")
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def read_private(path: Path) -> dict:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
        ):
            raise ReplayError("Private JSON must be an owner-only regular file (0600)")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as stream:
            value = json.load(stream)
    finally:
        os.close(descriptor)
    if not isinstance(value, dict):
        raise ReplayError("Private JSON must be an object")
    return value


def _stack_resources(cfn: Any, stack_name: str, account: str) -> list[dict]:
    stacks = cfn.describe_stacks(StackName=stack_name).get("Stacks", [])
    if len(stacks) != 1 or not stacks[0]["StackStatus"].endswith("_COMPLETE"):
        raise ReplayError("CloudFormation stack is not complete")
    pending = [stacks[0]["StackId"]]
    seen: set[str] = set()
    resources: list[dict] = []
    while pending:
        stack_id = pending.pop()
        if stack_id in seen:
            continue
        if f":{REGION}:{account}:" not in stack_id:
            raise ReplayError("CloudFormation stack is in an unexpected account or region")
        seen.add(stack_id)
        for page in cfn.get_paginator("list_stack_resources").paginate(StackName=stack_id):
            for item in page.get("StackResourceSummaries", []):
                resources.append(item)
                if item["ResourceType"] == "AWS::CloudFormation::Stack":
                    pending.append(item["PhysicalResourceId"])
    return resources


def _physical(resources: list[dict], kind: str, logical: str) -> str:
    found = [
        item["PhysicalResourceId"]
        for item in resources
        if item.get("ResourceType") == kind
        and item.get("LogicalResourceId", "").startswith(logical)
        and not item.get("LogicalResourceId", "").startswith(logical + "Failures")
        and not item.get("LogicalResourceId", "").startswith(logical + "DeadLetter")
        and isinstance(item.get("PhysicalResourceId"), str)
    ]
    if len(found) != 1:
        raise ReplayError(f"Expected exactly one {logical} CloudFormation resource")
    return found[0]


def _capture_contract(queue: dict, failures: dict, subscriptions: list[dict],
                      subscription: dict, *, topic_arn: str, queue_arn: str,
                      failure_arn: str, account: str) -> None:
    for label, attributes, expected_arn in (
        ("capture", queue, queue_arn), ("capture failure", failures, failure_arn)
    ):
        if (
            attributes.get("QueueArn") != expected_arn
            or attributes.get("MessageRetentionPeriod") != "1209600"
            or attributes.get("SqsManagedSseEnabled") != "true"
        ):
            raise ReplayError(f"{label} queue identity, retention, or encryption changed")
    if any(int(failures.get(name, "0")) != 0 for name in (
        "ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"
    )):
        raise ReplayError("SNS capture delivery failure queue is nonempty")
    matches = [item for item in subscriptions
               if item.get("Protocol") == "sqs" and item.get("Endpoint") == queue_arn]
    if len(matches) != 1 or matches[0].get("SubscriptionArn") in {None, "PendingConfirmation"}:
        raise ReplayError("Exact SNS-to-capture-queue subscription is absent")
    try:
        redrive = json.loads(subscription.get("RedrivePolicy", "{}"))
    except (TypeError, ValueError) as exc:
        raise ReplayError("SNS capture subscription redrive policy is invalid") from exc
    if (
        subscription.get("TopicArn") != topic_arn
        or subscription.get("Endpoint") != queue_arn
        or subscription.get("RawMessageDelivery") != "false"
        or redrive.get("deadLetterTargetArn") != failure_arn
    ):
        raise ReplayError("SNS capture subscription delivery contract changed")
    try:
        policy = json.loads(queue.get("Policy", "{}"))
    except (TypeError, ValueError) as exc:
        raise ReplayError("Capture queue policy is invalid") from exc
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    if not any(
        item.get("Effect") == "Allow"
        and item.get("Principal") == {"Service": "sns.amazonaws.com"}
        and "sqs:SendMessage" in (
            [item.get("Action")] if isinstance(item.get("Action"), str)
            else item.get("Action", [])
        )
        and queue_arn in (
            [item.get("Resource")] if isinstance(item.get("Resource"), str)
            else item.get("Resource", [])
        )
        and item.get("Condition", {}).get("ArnEquals", {}).get("aws:SourceArn") == topic_arn
        and item.get("Condition", {}).get("StringEquals", {}).get("aws:SourceAccount") == account
        for item in statements if isinstance(item, dict)
    ):
        raise ReplayError("Capture queue lacks the exact account/topic SNS grant")


class Account:
    """One profile with physical resources proven against CloudFormation."""

    def __init__(self, *, profile: str, expected_account: str, app_stack: str,
                 capture_stack: str) -> None:
        if expected_account not in {SOURCE_ACCOUNT, DESTINATION_ACCOUNT}:
            raise ReplayError("Unexpected AWS account")
        self.account = expected_account
        self.app_stack = app_stack
        self.capture_stack = capture_stack
        self.session = boto3.Session(profile_name=profile, region_name=REGION)
        if self.session.client("sts").get_caller_identity().get("Account") != expected_account:
            raise ReplayError("AWS profile is in the wrong account")
        self.cfn = self.session.client("cloudformation")
        self.s3 = self.session.client("s3")
        self.sqs = self.session.client("sqs")
        self.sns = self.session.client("sns")
        self.ddb = self.session.resource("dynamodb")
        app = _stack_resources(self.cfn, app_stack, expected_account)
        capture = _stack_resources(self.cfn, capture_stack, expected_account)
        self.table_name = _physical(app, "AWS::DynamoDB::Table", "Data")
        self.raw_bucket = _physical(app, "AWS::S3::Bucket", "IncomingBotMail")
        self.topic_arn = _physical(app, "AWS::SNS::Topic", "IncomingBotMailTopic")
        self.job_queue_name = _physical(app, "AWS::SQS::Queue", "AgentJobs")
        self.quarantine_bucket = _physical(capture, "AWS::S3::Bucket", "BotEmailQuarantine")
        self.queue_name = _physical(capture, "AWS::SQS::Queue", "BotEmailInboundCapture")
        self.failure_queue_name = _physical(capture, "AWS::SQS::Queue", "BotEmailInboundCaptureFailures")
        self.queue_url = self.sqs.get_queue_url(
            QueueName=self.queue_name,
            QueueOwnerAWSAccountId=expected_account,
        )["QueueUrl"]
        self.job_queue_url = self.sqs.get_queue_url(
            QueueName=self.job_queue_name,
            QueueOwnerAWSAccountId=expected_account,
        )["QueueUrl"]
        self.failure_queue_url = self.sqs.get_queue_url(
            QueueName=self.failure_queue_name,
            QueueOwnerAWSAccountId=expected_account,
        )["QueueUrl"]
        attributes = self.sqs.get_queue_attributes(
            QueueUrl=self.queue_url,
            AttributeNames=["All"],
        )["Attributes"]
        self.queue_arn = attributes["QueueArn"]
        failure_attributes = self.sqs.get_queue_attributes(
            QueueUrl=self.failure_queue_url, AttributeNames=["All"]
        )["Attributes"]
        self.failure_queue_arn = failure_attributes["QueueArn"]
        if not self.queue_arn.startswith(f"arn:aws:sqs:{REGION}:{expected_account}:"):
            raise ReplayError("Capture queue ARN is in the wrong account or region")
        if self.topic_arn.startswith(f"arn:aws:sns:{REGION}:{expected_account}:") is False:
            raise ReplayError("Incoming mail SNS topic is in the wrong account or region")
        subscriptions = [
            item
            for page in self.sns.get_paginator("list_subscriptions_by_topic").paginate(
                TopicArn=self.topic_arn
            )
            for item in page.get("Subscriptions", [])
        ]
        matching = [item for item in subscriptions
                    if item.get("Protocol") == "sqs" and item.get("Endpoint") == self.queue_arn]
        if len(matching) != 1:
            raise ReplayError("Exact SNS capture subscription is missing")
        subscription = self.sns.get_subscription_attributes(
            SubscriptionArn=matching[0]["SubscriptionArn"]
        )["Attributes"]
        _capture_contract(
            attributes, failure_attributes, subscriptions, subscription,
            topic_arn=self.topic_arn, queue_arn=self.queue_arn,
            failure_arn=self.failure_queue_arn, account=expected_account,
        )
        detail = self.ddb.meta.client.describe_table(TableName=self.table_name)["Table"]
        if (
            detail["TableStatus"] != "ACTIVE"
            or not detail["TableArn"].startswith(f"arn:aws:dynamodb:{REGION}:{expected_account}:")
            or [(part["AttributeName"], part["KeyType"]) for part in detail["KeySchema"]]
            != [("pk", "HASH"), ("sk", "RANGE")]
        ):
            raise ReplayError("Application table identity or schema changed")
        for bucket in (self.raw_bucket, self.quarantine_bucket):
            self.s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=expected_account)
        self.table = self.ddb.Table(self.table_name)

    def manifest(self) -> dict:
        return {
            "account": self.account,
            "region": REGION,
            "appStack": self.app_stack,
            "captureStack": self.capture_stack,
            "table": self.table_name,
            "rawBucket": self.raw_bucket,
            "quarantineBucket": self.quarantine_bucket,
            "topicArn": self.topic_arn,
            "queueArn": self.queue_arn,
            "queueUrl": self.queue_url,
            "failureQueueArn": self.failure_queue_arn,
            "jobQueueUrl": self.job_queue_url,
        }

    def verify_manifest(self, expected: dict) -> None:
        if self.manifest() != expected:
            raise ReplayError("Live account resources differ from private capture snapshot")

    def queue_counts(self) -> dict[str, int]:
        attributes = self.sqs.get_queue_attributes(
            QueueUrl=self.queue_url,
            AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
        )["Attributes"]
        return {
            "visible": int(attributes.get("ApproximateNumberOfMessages", "0")),
            "notVisible": int(attributes.get("ApproximateNumberOfMessagesNotVisible", "0")),
        }

    def read_mime(self, bucket: str, key: str) -> bytes:
        if bucket not in {self.raw_bucket, self.quarantine_bucket}:
            raise ReplayError("MIME bucket differs from exact CloudFormation resources")
        response = self.s3.get_object(
            Bucket=bucket, Key=key, ExpectedBucketOwner=self.account
        )
        if response.get("ContentLength", MAX_MIME_BYTES + 1) > MAX_MIME_BYTES:
            response["Body"].close()
            raise ReplayError("MIME exceeds bounded replay size")
        with response["Body"] as stream:
            raw = stream.read(MAX_MIME_BYTES + 1)
        if len(raw) > MAX_MIME_BYTES or len(raw) != response.get("ContentLength"):
            raise ReplayError("MIME length changed while reading")
        return raw


def _capture_queue(account: Account, max_messages: int) -> list[dict]:
    found: dict[str, dict] = {}
    handles: list[str] = []
    empty = 0
    try:
        while empty < 3:
            response = account.sqs.receive_message(
                QueueUrl=account.queue_url,
                MaxNumberOfMessages=10,
                VisibilityTimeout=30,
                WaitTimeSeconds=1,
                MessageSystemAttributeNames=["SentTimestamp"],
            )
            messages = response.get("Messages", [])
            empty = empty + 1 if not messages else 0
            for item in messages:
                handles.append(item["ReceiptHandle"])
                message_id = item["MessageId"]
                if message_id in found and found[message_id]["body"] != item["Body"]:
                    raise ReplayError("SQS message ID was reused with different content")
                found[message_id] = {
                    "account": account.account,
                    "sqsMessageId": message_id,
                    "body": item["Body"],
                    "sentTimestampMs": item.get("Attributes", {}).get("SentTimestamp", ""),
                }
                if len(found) > max_messages:
                    raise ReplayError("Capture queue exceeds the reviewed snapshot bound")
        return list(found.values())
    finally:
        # Review may take hours; no snapshot call may keep customer mail hidden.
        for handle in handles:
            account.sqs.change_message_visibility(
                QueueUrl=account.queue_url, ReceiptHandle=handle, VisibilityTimeout=0
            )


def capture_snapshot(source: Account, destination: Account, max_messages: int) -> dict:
    if max_messages < 1 or max_messages > 10000:
        raise ReplayError("Capture snapshot bound must be between 1 and 10000")
    accounts = {source.account: source.manifest(), destination.account: destination.manifest()}
    before = {item.account: item.queue_counts() for item in (source, destination)}
    captured: list[dict] = []
    for account in (source, destination):
        for entry in _capture_queue(account, max_messages):
            parsed = parse_capture(
                entry["body"], account.account, entry["sqsMessageId"],
                account.topic_arn, {account.raw_bucket, account.quarantine_bucket},
            )
            raw = account.read_mime(parsed[0]["bucket"], parsed[0]["key"])
            if not raw:
                raise ReplayError("Captured MIME is empty")
            header = str(BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
                         .get("Message-ID", "")).strip().lower()
            evidence = {
                "mimeSha256": hashlib.sha256(raw).hexdigest(),
                "mimeBytes": len(raw),
                "headerMessageId": header,
            }
            entry["observations"] = [{**item, **evidence} for item in parsed]
            captured.append(entry)
    quarantine_refs = {
        (item["account"], observation["bucket"], observation["key"])
        for item in captured
        for observation in item["observations"]
    }
    retained_inbox_refs: set[str] = set()
    for page in destination.table.meta.client.get_paginator("scan").paginate(
        TableName=destination.table_name,
        ConsistentRead=True,
        FilterExpression=Attr("entity").eq("BOT_EMAIL"),
        ProjectionExpression="rawObjectKey",
    ):
        for row in page.get("Items", []):
            key = row.get("rawObjectKey")
            if isinstance(key, str):
                retained_inbox_refs.add(key)
    unclassified = []
    for account in (source, destination):
        buckets = [account.quarantine_bucket]
        if account.account == DESTINATION_ACCOUNT:
            buckets.append(account.raw_bucket)
        for bucket in buckets:
            for page in account.s3.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix="received/", ExpectedBucketOwner=account.account
            ):
                for item in page.get("Contents", []):
                    key = item["Key"]
                    if (account.account, bucket, key) in quarantine_refs:
                        continue
                    if bucket == destination.raw_bucket and key in retained_inbox_refs:
                        continue
                    if not key.startswith("received/") or item["Size"] > MAX_MIME_BYTES:
                        raise ReplayError("Unexpected unclassified MIME object")
                    raw = account.read_mime(bucket, key)
                    unclassified.append({
                        "account": account.account,
                        "bucket": bucket,
                        "key": key,
                        "mimeBytes": len(raw),
                        "mimeSha256": hashlib.sha256(raw).hexdigest(),
                    })
    after = {item.account: item.queue_counts() for item in (source, destination)}
    snapshot = {
        "schemaVersion": 1,
        "inventoryOnly": True,
        "accounts": accounts,
        "queueCountsBefore": before,
        "queueCountsAfter": after,
        "messages": sorted(captured, key=lambda item: (item["account"], item["sqsMessageId"])),
        "unclassifiedObjects": sorted(unclassified, key=lambda item: (
            item["account"], item["bucket"], item["key"]
        )),
    }
    snapshot["snapshotDigest"] = digest(snapshot)
    return snapshot
