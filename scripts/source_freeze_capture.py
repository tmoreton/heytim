"""Capture private source freeze settings from exact-account read-only inventory.

This command has no apply or restore mode. It binds each discovered physical
resource to a recent sanitized preflight and saves settings outside the repo.
An incomplete capture fails without creating a snapshot.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
from _source_freeze_boto import BotoFreezeAdapter
from _source_freeze_plan import FreezePlanError, validate_preflight
from _source_mail_capture import active_store_only_match
from _source_mail_capture_preflight import _subscription_ready
from _source_writer_cli_transport import GuardedSession
from _source_writer_preflight_core import (
    EXPECTED,
    SOURCE_ACCOUNT,
    SOURCE_REGION,
    Report,
    discover_stack,
)
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from source_freeze_executor import capture, save_snapshot
from source_writer_preflight import _function_label

STATE = Path(__file__).resolve().parents[1] / "agentcore/.cli/deployed-state.json"
READ_CONFIG = Config(
    retries={"total_max_attempts": 2, "mode": "standard"},
    connect_timeout=5,
    read_timeout=15,
)


def _exact(resources: list[dict], kind: str, prefix: str) -> str:
    longer_queue_prefixes = (
        tuple(
            value
            for value in EXPECTED["queue"].values()
            if value.startswith(prefix) and value != prefix
        )
        if kind == "AWS::SQS::Queue"
        else ()
    )
    matches = [
        item["PhysicalResourceId"]
        for item in resources
        if item["ResourceType"] == kind
        and item["LogicalResourceId"].startswith(prefix)
        and not item["LogicalResourceId"].startswith(longer_queue_prefixes)
        and item.get("PhysicalResourceId")
    ]
    if len(matches) != 1:
        raise FreezePlanError(f"source {kind}/{prefix} missing or ambiguous")
    return matches[0]


def _pages(client: Any, operation: str, key: str, **params: Any) -> list[dict]:
    if not client.can_paginate(operation):
        raise FreezePlanError("source inventory paginator unavailable")
    return [
        item
        for page in client.get_paginator(operation).paginate(**params)
        for item in page.get(key, [])
    ]


def _deployed_agentcore() -> tuple[dict, dict]:
    data = json.loads(STATE.read_text())["targets"]["development"]["resources"]
    if len(data["runtimes"]) != 1 or len(data["memories"]) != 1:
        raise FreezePlanError("deployed AgentCore state is ambiguous")
    return next(iter(data["runtimes"].values())), next(iter(data["memories"].values()))


def discover_manifest(
    session: Any, stack_name: str, mail_stack_name: str | None = None
) -> dict[str, Any]:
    """Discover private physical IDs using a read-only allowlisted session."""
    if session.region_name != SOURCE_REGION:
        raise FreezePlanError("source region mismatch")
    if session.client("sts", config=READ_CONFIG).get_caller_identity().get(
        "Account"
    ) != SOURCE_ACCOUNT:
        raise FreezePlanError("source account mismatch")
    guarded = GuardedSession(session)
    report = Report()
    resources = discover_stack(
        report, guarded.client("cloudformation", config=READ_CONFIG), stack_name
    )
    if resources is None or report.blockers:
        raise FreezePlanError("source stack discovery incomplete")
    if mail_stack_name:
        if mail_stack_name == stack_name:
            raise FreezePlanError("mail capture stack must be distinct")
        mail_resources = discover_stack(
            report, guarded.client("cloudformation", config=READ_CONFIG), mail_stack_name
        )
        if mail_resources is None or report.blockers:
            raise FreezePlanError("mail capture stack discovery incomplete")
        resources.extend(mail_resources)

    dynamodb = guarded.client("dynamodb", config=READ_CONFIG)
    tables = {}
    for label, prefix in EXPECTED["table"].items():
        name = _exact(resources, "AWS::DynamoDB::Table", prefix)
        table = dynamodb.describe_table(TableName=name)["Table"]
        if table.get("TableName") != name:
            raise FreezePlanError("table identity mismatch")
        tables[label] = {"name": name, "arn": table["TableArn"]}

    buckets = {
        label: _exact(resources, "AWS::S3::Bucket", prefix)
        for label, prefix in EXPECTED["bucket"].items()
    }
    lambdas = guarded.client("lambda", config=READ_CONFIG)
    function_names: dict[str, str] = {}
    for item in resources:
        if item["ResourceType"] != "AWS::Lambda::Function":
            continue
        name = item["PhysicalResourceId"]
        config = lambdas.get_function_configuration(FunctionName=name)
        label = _function_label(item["LogicalResourceId"], config.get("Handler", ""))
        if label in {"availability_probe", "deployment_custom_resource"}:
            continue
        if label is None or label in function_names:
            raise FreezePlanError("Lambda inventory unclassified or ambiguous")
        function_names[label] = name

    receiver_concurrency = lambdas.get_function_concurrency(
        FunctionName=function_names["email_receiver"]
    )
    if receiver_concurrency.get("ReservedConcurrentExecutions") != 0:
        raise FreezePlanError("source mail receiver concurrency is not held at zero")

    sqs = guarded.client("sqs", config=READ_CONFIG)
    queue_arns = {}
    for label in ("jobs", "outbound_mail", "inbound_capture", "inbound_capture_failures"):
        url = _exact(resources, "AWS::SQS::Queue", EXPECTED["queue"][label])
        queue_arns[label] = sqs.get_queue_attributes(
            QueueUrl=url, AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]
    mappings = {}
    for label, queue_label in (("worker", "jobs"), ("email_sender", "outbound_mail")):
        found = _pages(
            lambdas,
            "list_event_source_mappings",
            "EventSourceMappings",
            FunctionName=function_names[label],
        )
        if len(found) != 1 or found[0].get("EventSourceArn") != queue_arns[queue_label]:
            raise FreezePlanError("queue mapping inventory changed")
        mappings[label] = found[0]["UUID"]

    rules = {
        "catalog_rule": _exact(resources, "AWS::Events::Rule", "CatalogRefresh"),
        "public_availability_rule": _exact(
            resources, "AWS::Events::Rule", "PublicAvailabilitySchedule"
        ),
    }
    group = _exact(resources, "AWS::Scheduler::ScheduleGroup", "TaskSchedules")
    scheduler = guarded.client("scheduler", config=READ_CONFIG)
    schedules = [
        {"group": group, "name": item["Name"]}
        for item in _pages(scheduler, "list_schedules", "Schedules", GroupName=group)
    ]

    receipt_physical = _exact(resources, "AWS::SES::ReceiptRule", "BotEmailReceiptRule")
    topic_arn = _exact(resources, "AWS::SNS::Topic", "IncomingBotMailTopic")
    subscription_arn = _exact(
        resources, "AWS::SNS::Subscription", "BotEmailInboundCaptureSubscription"
    )
    role_name = _exact(resources, "AWS::IAM::Role", "BotEmailSesDeliveryRole")
    role_arn = guarded.client("iam", config=READ_CONFIG).get_role(RoleName=role_name)[
        "Role"
    ]["Arn"]
    mail_capture = {
        "topic_arn": topic_arn,
        "subscription_arn": subscription_arn,
        "queue_arn": queue_arns["inbound_capture"],
        "failure_queue_arn": queue_arns["inbound_capture_failures"],
        "role_arn": role_arn,
    }
    sns = guarded.client("sns", config=READ_CONFIG)
    subscriptions = _pages(
        sns, "list_subscriptions_by_topic", "Subscriptions", TopicArn=topic_arn
    )
    receiver_arn = (
        f"arn:aws:lambda:{SOURCE_REGION}:{SOURCE_ACCOUNT}:function:"
        f"{function_names['email_receiver']}"
    )
    lambda_subscribers = [
        item for item in subscriptions
        if item.get("Protocol") == "lambda" and item.get("Endpoint") == receiver_arn
    ]
    if len(lambda_subscribers) != 1:
        raise FreezePlanError("source mail receiver subscription missing or ambiguous")
    subscription = sns.get_subscription_attributes(
        SubscriptionArn=subscription_arn
    )["Attributes"]
    lambda_subscription = sns.get_subscription_attributes(
        SubscriptionArn=lambda_subscribers[0]["SubscriptionArn"]
    )["Attributes"]
    if not _subscription_ready(
        subscriptions,
        subscription,
        lambda_subscription,
        subscription_arn=subscription_arn,
        topic_arn=topic_arn,
        queue_arn=mail_capture["queue_arn"],
        failure_queue_arn=mail_capture["failure_queue_arn"],
        receiver_arn=receiver_arn,
    ):
        raise FreezePlanError("mail capture subscription differs from held route")
    ses = guarded.client("ses", config=READ_CONFIG)
    active = ses.describe_active_receipt_rule_set()
    rule_set = active.get("Metadata", {}).get("Name")
    rule_name = receipt_physical.rsplit("|", 1)[-1]
    if receipt_physical != f"{rule_set}|{rule_name}":
        raise FreezePlanError("source SES rule physical identity is not exact")
    if not active_store_only_match(
        active,
        rule_set=rule_set,
        rule_name=rule_name,
        bucket=buckets["inbound_quarantine"],
        topic_arn=topic_arn,
        role_arn=role_arn,
    ):
        raise FreezePlanError("active SES source rule is not store-only capture")

    deployed_runtime, deployed_memory = _deployed_agentcore()
    core = guarded.client("bedrock-agentcore-control", config=READ_CONFIG)
    runtime = core.get_agent_runtime(agentRuntimeId=deployed_runtime["runtimeId"])
    memory = core.get_memory(memoryId=deployed_memory["memoryId"], view="full")[
        "memory"
    ]
    if (
        runtime.get("agentRuntimeArn") != deployed_runtime["runtimeArn"]
        or memory.get("arn") != deployed_memory["memoryArn"]
    ):
        raise FreezePlanError("AgentCore deployed identity differs from source")
    bucket = runtime.get("environmentVariables", {}).get("HEYTIM_FILES_BUCKET")
    if not bucket or bucket in buckets.values():
        raise FreezePlanError("AgentCore runtime bucket is missing or overlaps")
    s3 = guarded.client("s3", config=READ_CONFIG)
    s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=SOURCE_ACCOUNT)
    region = s3.get_bucket_location(
        Bucket=bucket, ExpectedBucketOwner=SOURCE_ACCOUNT
    ).get("LocationConstraint") or "us-east-1"
    if region != SOURCE_REGION:
        raise FreezePlanError("AgentCore runtime bucket region mismatch")
    buckets["runtime_files"] = bucket
    endpoints = _pages(
        core,
        "list_agent_runtime_endpoints",
        "runtimeEndpoints",
        agentRuntimeId=deployed_runtime["runtimeId"],
    )
    if len(endpoints) != 1:
        raise FreezePlanError("AgentCore endpoint inventory is not singular")
    manifest = {
        "account": SOURCE_ACCOUNT,
        "region": SOURCE_REGION,
        "buckets": buckets,
        "tables": tables,
        "lambdas": function_names,
        "mappings": mappings,
        "event_rules": rules,
        "schedules": schedules,
        "ses": {"rule_set": rule_set, "rule_name": rule_name},
        "mail_capture": mail_capture,
        "agentcore": {
            "runtime": deployed_runtime["runtimeArn"],
            "endpoint": endpoints[0]["agentRuntimeEndpointArn"],
            "memory": deployed_memory["memoryArn"],
        },
    }
    return manifest


def _recent_evidence(path: Path) -> dict[str, Any]:
    evidence = json.loads(path.read_text())
    observed = datetime.fromisoformat(evidence["observed_at_utc"])
    if observed.tzinfo is None or not (
        timedelta(seconds=-60) <= datetime.now(UTC) - observed <= timedelta(minutes=15)
    ):
        raise FreezePlanError("source preflight is stale or has an invalid timestamp")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-name", required=True)
    parser.add_argument("--mail-stack-name")
    parser.add_argument("--profile")
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    args = parser.parse_args()
    try:
        session = boto3.Session(profile_name=args.profile, region_name=SOURCE_REGION)
        adapter = BotoFreezeAdapter(session, SOURCE_ACCOUNT)
        manifest = discover_manifest(session, args.stack_name, args.mail_stack_name)
        evidence = _recent_evidence(args.preflight)
        validate_preflight(manifest, evidence)
        snapshot = capture(adapter, manifest, evidence)
        save_snapshot(args.snapshot, snapshot)
    except (
        FreezePlanError,
        BotoCoreError,
        ClientError,
        NoCredentialsError,
        OSError,
        KeyError,
        ValueError,
    ) as error:
        code = type(error).__name__
        if isinstance(error, ClientError):
            code = error.response.get("Error", {}).get("Code", "ClientError")
        detail = f": {error}" if isinstance(error, FreezePlanError) else ""
        print(
            f"NO-GO: source read-only capture incomplete ({code}){detail}",
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": "NO_GO",
                "source_account_match": True,
                "source_region_match": True,
                "captured_controls": len(snapshot.observed),
                "snapshot_sha256": snapshot.digest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
