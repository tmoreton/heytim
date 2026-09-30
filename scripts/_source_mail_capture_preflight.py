"""Read-only, sanitized proof of the source bot-mail quarantine path."""

from __future__ import annotations

import json
from fnmatch import fnmatchcase
from typing import Any

from _source_mail_capture import active_store_only_match
from _source_writer_preflight_core import (
    ABSENT,
    SOURCE_ACCOUNT,
    SOURCE_REGION,
    Report,
    _one,
    fingerprint,
    pages,
    read,
)

_QUEUE_SECONDS = 14 * 24 * 60 * 60
_BUCKET_PUBLIC_BLOCK = (
    "BlockPublicAcls",
    "IgnorePublicAcls",
    "BlockPublicPolicy",
    "RestrictPublicBuckets",
)
SOURCE_LAMBDA_HOLD_FILTER = {
    "heytim_cutover_capture_hold": ["source-188757775631-20260930"]
}


def _statements(value: Any) -> list[dict] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None
    statements = value.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or not all(
        isinstance(item, dict) for item in statements
    ):
        return None
    return statements


def _values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    return set()


def _queue_publish_policy(value: Any, queue_arn: str, topic_arn: str) -> bool:
    statements = _statements(value)
    if statements is None:
        return False
    found = False
    for item in statements:
        if item.get("Effect") != "Allow":
            continue
        actions = {action.casefold() for action in _values(item.get("Action"))}
        if not ({"sqs:sendmessage", "sqs:*", "*"} & actions):
            continue
        principal = item.get("Principal")
        resources = _values(item.get("Resource"))
        if queue_arn not in resources and "*" not in resources:
            continue
        condition = item.get("Condition")
        arn_equals = condition.get("ArnEquals") if isinstance(condition, dict) else None
        string_equals = (
            condition.get("StringEquals") if isinstance(condition, dict) else None
        )
        scoped = (
            isinstance(arn_equals, dict)
            and isinstance(string_equals, dict)
            and arn_equals.get("aws:SourceArn") == topic_arn
            and string_equals.get("aws:SourceAccount") == SOURCE_ACCOUNT
            and resources == {queue_arn}
            and principal == {"Service": "sns.amazonaws.com"}
            and "NotAction" not in item
            and "NotResource" not in item
        )
        if not scoped:
            return False
        found = True
    return found


def _queue_ready(attributes: Any, expected_arn: str, topic_arn: str) -> bool:
    if not isinstance(attributes, dict):
        return False
    if attributes.get("QueueArn") != expected_arn:
        return False
    if attributes.get("SqsManagedSseEnabled") != "true":
        return False
    if attributes.get("MessageRetentionPeriod") != str(_QUEUE_SECONDS):
        return False
    try:
        if any(
            int(attributes.get(key, "-1")) < 0
            for key in (
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            )
        ):
            return False
    except (TypeError, ValueError):
        return False
    return _queue_publish_policy(attributes.get("Policy"), expected_arn, topic_arn)


def _queue_empty(attributes: Any) -> bool:
    if not isinstance(attributes, dict):
        return False
    try:
        return all(
            int(attributes.get(key, "-1")) == 0
            for key in (
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            )
        )
    except (TypeError, ValueError):
        return False


def _bucket_tls_and_writable(policy: Any, bucket: str) -> bool:
    statements = _statements(policy)
    if statements is None:
        return False
    bucket_arn = f"arn:aws:s3:::{bucket}"
    object_arn = f"{bucket_arn}/*"
    tls_deny = False
    for item in statements:
        if item.get("Effect") != "Deny":
            continue
        resources = _values(item.get("Resource"))
        sample_object = f"{bucket_arn}/received/capture-probe"
        if not any(fnmatchcase(sample_object, resource) for resource in resources):
            continue
        actions = {action.casefold() for action in _values(item.get("Action"))}
        condition = item.get("Condition")
        secure_transport = (
            condition.get("Bool") if isinstance(condition, dict) else None
        )
        if item.get("Sid") == "HeyTimSourceWriteFreeze":
            return False
        can_deny_put = bool(
            {
                "s3:putobject",
                "s3:putobject*",
                "s3:*",
                "*",
            }
            & actions
        )
        is_tls_deny = (
            "s3:*" in actions
            and {bucket_arn, object_arn} <= resources
            and isinstance(secure_transport, dict)
            and secure_transport.get("aws:SecureTransport") in {"false", False}
            and item.get("Principal") in ("*", {"AWS": "*"})
        )
        if (
            can_deny_put or "NotAction" in item or "NotResource" in item
        ) and not is_tls_deny:
            return False
        if is_tls_deny:
            tls_deny = True
    return tls_deny


def _lifecycle_safe(value: Any) -> bool:
    if value is ABSENT:
        return True
    if not isinstance(value, dict) or not isinstance(value.get("Rules"), list):
        return False
    for rule in value["Rules"]:
        if not isinstance(rule, dict):
            return False
        if rule.get("Status") == "Disabled":
            continue
        if rule.get("Status") != "Enabled" or rule.get("Transitions"):
            return False
        expiration = rule.get("Expiration")
        if not isinstance(expiration, dict):
            return False
        days = expiration.get("Days")
        if not isinstance(days, int) or isinstance(days, bool) or days < 14:
            return False
        if set(expiration) != {"Days"}:
            return False
    return True


def _sse_s3(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    configuration = value.get("ServerSideEncryptionConfiguration")
    rules = configuration.get("Rules") if isinstance(configuration, dict) else None
    if not isinstance(rules, list) or len(rules) != 1 or not isinstance(rules[0], dict):
        return False
    default = rules[0].get("ApplyServerSideEncryptionByDefault")
    return isinstance(default, dict) and default == {"SSEAlgorithm": "AES256"}


def _public_blocked(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    config = value.get("PublicAccessBlockConfiguration")
    return isinstance(config, dict) and all(
        config.get(key) is True for key in _BUCKET_PUBLIC_BLOCK
    )


def _role_trust_ok(role: Any, rule_set: str, rule_name: str) -> bool:
    if not isinstance(role, dict):
        return False
    trust = _statements(role.get("AssumeRolePolicyDocument"))
    if trust is None:
        return False
    expected_source = (
        f"arn:aws:ses:{SOURCE_REGION}:{SOURCE_ACCOUNT}:"
        f"receipt-rule-set/{rule_set}:receipt-rule/{rule_name}"
    )
    allowed = [item for item in trust if item.get("Effect") == "Allow"]
    return len(allowed) == 1 and all(
        item.get("Effect") == "Allow"
        and item.get("Principal") == {"Service": "ses.amazonaws.com"}
        and _values(item.get("Action")) == {"sts:AssumeRole"}
        and isinstance(item.get("Condition"), dict)
        and item["Condition"].get("StringEquals")
        == {"aws:SourceAccount": SOURCE_ACCOUNT, "aws:SourceArn": expected_source}
        and "NotAction" not in item
        and "NotPrincipal" not in item
        for item in allowed
    )


def _subscription_ready(
    subscriptions: Any,
    attributes: Any,
    lambda_attributes: Any,
    *,
    subscription_arn: str,
    topic_arn: str,
    queue_arn: str,
    failure_queue_arn: str,
    receiver_arn: str,
) -> bool:
    if not isinstance(subscriptions, list) or len(subscriptions) != 2:
        return False
    if not all(isinstance(item, dict) for item in subscriptions) or not isinstance(
        attributes, dict
    ) or not isinstance(lambda_attributes, dict):
        return False
    expected = {
        "SubscriptionArn": subscription_arn,
        "TopicArn": topic_arn,
        "Protocol": "sqs",
        "Endpoint": queue_arn,
    }
    capture = [
        item
        for item in subscriptions
        if item.get("SubscriptionArn") == subscription_arn
    ]
    if len(capture) != 1 or any(
        capture[0].get(key) != value for key, value in expected.items()
    ):
        return False
    others = [item for item in subscriptions if item is not capture[0]]
    if len(others) != 1 or not (
        others[0].get("TopicArn") == topic_arn
        and others[0].get("Protocol") == "lambda"
        and others[0].get("Endpoint") == receiver_arn
        and isinstance(others[0].get("SubscriptionArn"), str)
        and others[0]["SubscriptionArn"].startswith(
            f"arn:aws:sns:{SOURCE_REGION}:{SOURCE_ACCOUNT}:"
        )
    ):
        return False
    expected_lambda = {
        "SubscriptionArn": others[0]["SubscriptionArn"],
        "TopicArn": topic_arn,
        "Protocol": "lambda",
        "Endpoint": receiver_arn,
    }
    if any(lambda_attributes.get(key) != value for key, value in expected_lambda.items()):
        return False
    if lambda_attributes.get("FilterPolicyScope") != "MessageAttributes":
        return False
    try:
        held_filter = json.loads(lambda_attributes.get("FilterPolicy", ""))
    except (TypeError, ValueError):
        return False
    if held_filter != SOURCE_LAMBDA_HOLD_FILTER:
        return False
    if any(attributes.get(key) != value for key, value in expected.items()):
        return False
    if attributes.get("RawMessageDelivery") != "false":
        return False
    redrive = attributes.get("RedrivePolicy")
    if not isinstance(redrive, str):
        return False
    try:
        redrive = json.loads(redrive)
    except json.JSONDecodeError:
        return False
    return redrive == {"deadLetterTargetArn": failure_queue_arn}


def inspect_mail_capture(
    report: Report,
    resources: list[dict],
    ses: Any,
    sns: Any,
    sqs: Any,
    s3: Any,
    iam: Any,
    bucket_names: dict[str, str],
    queue_arns: dict[str, str],
) -> None:
    """Record only hashes/counts and block on any unproven capture component."""
    expected = (
        ("AWS::SES::ReceiptRule", "receipt_rule", "BotEmailReceiptRule"),
        ("AWS::SNS::Topic", "mail_topic", "IncomingBotMailTopic"),
        (
            "AWS::SNS::Subscription",
            "mail_subscription",
            "BotEmailInboundCaptureSubscription",
        ),
        ("AWS::IAM::Role", "mail_role", "BotEmailSesDeliveryRole"),
        ("AWS::Lambda::Function", "mail_receiver", "BotEmailReceiver"),
        ("AWS::S3::Bucket", "bucket_inbound_quarantine", "BotEmailQuarantine"),
        ("AWS::SQS::Queue", "queue_inbound_capture", "BotEmailInboundCapture"),
        (
            "AWS::SQS::Queue",
            "queue_inbound_capture_failures",
            "BotEmailInboundCaptureFailures",
        ),
    )
    found = {
        label: _one(report, resources, kind, label, prefix)
        for kind, label, prefix in expected
    }
    if not all(found.values()):
        report.block("mail_capture_resource_inventory_incomplete")
        report.add("mail_capture", state="BLOCKED")
        return

    bucket = found["bucket_inbound_quarantine"]["PhysicalResourceId"]
    topic_arn = found["mail_topic"]["PhysicalResourceId"]
    subscription_arn = found["mail_subscription"]["PhysicalResourceId"]
    role_name = found["mail_role"]["PhysicalResourceId"]
    receiver_name = found["mail_receiver"]["PhysicalResourceId"]
    receiver_arn = (
        receiver_name
        if receiver_name.startswith("arn:")
        else f"arn:aws:lambda:{SOURCE_REGION}:{SOURCE_ACCOUNT}:function:{receiver_name}"
    )
    queue_url = found["queue_inbound_capture"]["PhysicalResourceId"]
    failure_url = found["queue_inbound_capture_failures"]["PhysicalResourceId"]
    queue_arn = queue_arns.get("inbound_capture", "")
    failure_arn = queue_arns.get("inbound_capture_failures", "")
    role_response = read(
        report, "mail_capture_role", lambda: iam.get_role(RoleName=role_name)
    )
    role = role_response.get("Role", {}) if isinstance(role_response, dict) else {}
    if not isinstance(role, dict):
        role = {}
    role_arn = role.get("Arn", "")
    active = read(
        report, "mail_capture_active_set", ses.describe_active_receipt_rule_set
    )
    active_metadata = active.get("Metadata") if isinstance(active, dict) else None
    rule_set = (
        active_metadata.get("Name", "") if isinstance(active_metadata, dict) else ""
    )
    rule_name = "HeyTimBotInbox"
    receipt_physical = found["receipt_rule"]["PhysicalResourceId"]
    matches = (
        [
            rule
            for rule in active.get("Rules", [])
            if isinstance(rule, dict) and rule.get("Name") == rule_name
        ]
        if isinstance(active, dict) and isinstance(active.get("Rules"), list)
        else []
    )
    rule_ok = receipt_physical in {
        rule_name,
        f"{rule_set}|{rule_name}",
    } and active_store_only_match(
        active,
        rule_set=rule_set,
        rule_name=rule_name,
        bucket=bucket,
        topic_arn=topic_arn,
        role_arn=role_arn,
    )
    report.add(
        "receipt_rule",
        state="OBSERVED" if rule_ok else "UNKNOWN",
        matching_source_rules=len(matches),
        enabled=sum(rule.get("Enabled") is True for rule in matches),
    )

    subscriptions = pages(
        report,
        "mail_capture_subscriptions",
        sns,
        "list_subscriptions_by_topic",
        "Subscriptions",
        TopicArn=topic_arn,
    )
    sub_response = read(
        report,
        "mail_capture_subscription_attributes",
        lambda: sns.get_subscription_attributes(SubscriptionArn=subscription_arn),
    )
    sub_attrs = (
        sub_response.get("Attributes", {}) if isinstance(sub_response, dict) else {}
    )
    lambda_subscriptions = [
        item for item in subscriptions or []
        if isinstance(item, dict) and item.get("Protocol") == "lambda"
    ]
    lambda_sub_response = (
        read(
            report,
            "mail_capture_lambda_subscription_attributes",
            lambda: sns.get_subscription_attributes(
                SubscriptionArn=lambda_subscriptions[0]["SubscriptionArn"]
            ),
        )
        if len(lambda_subscriptions) == 1
        and isinstance(lambda_subscriptions[0].get("SubscriptionArn"), str)
        and lambda_subscriptions[0]["SubscriptionArn"].startswith(
            f"arn:aws:sns:{SOURCE_REGION}:{SOURCE_ACCOUNT}:"
        )
        else None
    )
    lambda_sub_attrs = (
        lambda_sub_response.get("Attributes", {})
        if isinstance(lambda_sub_response, dict)
        else {}
    )
    capture_response = read(
        report,
        "mail_capture_queue_attributes",
        lambda: sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["All"]),
    )
    failure_response = read(
        report,
        "mail_capture_failure_queue_attributes",
        lambda: sqs.get_queue_attributes(QueueUrl=failure_url, AttributeNames=["All"]),
    )
    capture_attrs = (
        capture_response.get("Attributes", {})
        if isinstance(capture_response, dict)
        else {}
    )
    failure_attrs = (
        failure_response.get("Attributes", {})
        if isinstance(failure_response, dict)
        else {}
    )

    owner = {"Bucket": bucket, "ExpectedBucketOwner": SOURCE_ACCOUNT}
    head = read(report, "mail_capture_bucket_owner", lambda: s3.head_bucket(**owner))
    location = read(
        report, "mail_capture_bucket_region", lambda: s3.get_bucket_location(**owner)
    )
    encryption = read(
        report,
        "mail_capture_bucket_encryption",
        lambda: s3.get_bucket_encryption(**owner),
    )
    public = read(
        report,
        "mail_capture_bucket_public_block",
        lambda: s3.get_public_access_block(**owner),
    )
    lifecycle = read(
        report,
        "mail_capture_bucket_lifecycle",
        lambda: s3.get_bucket_lifecycle_configuration(**owner),
        {"NoSuchLifecycleConfiguration"},
    )
    policy_response = read(
        report,
        "mail_capture_bucket_policy",
        lambda: s3.get_bucket_policy(**owner),
    )
    policy = (
        policy_response.get("Policy") if isinstance(policy_response, dict) else None
    )
    bucket_ok = (
        head is not None
        and isinstance(location, dict)
        and (location.get("LocationConstraint") or "us-east-1") == SOURCE_REGION
        and _sse_s3(encryption)
        and _public_blocked(public)
        and _lifecycle_safe(lifecycle)
        and _bucket_tls_and_writable(policy, bucket)
    )
    report.add(
        "bucket_inbound_quarantine",
        state="OBSERVED" if bucket_ok else "UNKNOWN",
        id_sha256_12=fingerprint(bucket),
    )

    identities_ok = (
        bucket_names.get("inbound_quarantine") == bucket
        and topic_arn.startswith(f"arn:aws:sns:{SOURCE_REGION}:{SOURCE_ACCOUNT}:")
        and subscription_arn.startswith(
            f"arn:aws:sns:{SOURCE_REGION}:{SOURCE_ACCOUNT}:"
        )
        and queue_arn.startswith(f"arn:aws:sqs:{SOURCE_REGION}:{SOURCE_ACCOUNT}:")
        and failure_arn.startswith(f"arn:aws:sqs:{SOURCE_REGION}:{SOURCE_ACCOUNT}:")
        and role_arn.startswith(f"arn:aws:iam::{SOURCE_ACCOUNT}:role/")
        and role.get("RoleName") == role_name
        and role_arn == role.get("Arn")
        and queue_arn != failure_arn
        and bucket
        not in {
            value
            for label, value in bucket_names.items()
            if label != "inbound_quarantine"
        }
    )
    role_ok = _role_trust_ok(role, rule_set, rule_name)
    subscription_ok = _subscription_ready(
        subscriptions,
        sub_attrs,
        lambda_sub_attrs,
        subscription_arn=subscription_arn,
        topic_arn=topic_arn,
        queue_arn=queue_arn,
        failure_queue_arn=failure_arn,
        receiver_arn=receiver_arn,
    )
    queues_ok = (
        _queue_ready(capture_attrs, queue_arn, topic_arn)
        and _queue_ready(failure_attrs, failure_arn, topic_arn)
        and _queue_empty(failure_attrs)
    )
    ready = all(
        (identities_ok, rule_ok, role_ok, subscription_ok, queues_ok, bucket_ok)
    )
    if not ready:
        report.block("mail_capture_not_ready")
    report.add(
        "mail_capture",
        state="READY" if ready else "BLOCKED",
        bucket_sha256_12=fingerprint(bucket),
        topic_arn_sha256_12=fingerprint(topic_arn),
        subscription_arn_sha256_12=fingerprint(subscription_arn),
        queue_arn_sha256_12=fingerprint(queue_arn),
        failure_queue_arn_sha256_12=fingerprint(failure_arn),
        role_arn_sha256_12=fingerprint(role_arn),
    )
