"""Read-only, fail-closed source-writer inventory for the HeyTim account cutover.

This never prints customer records, environment values, policy bodies, addresses,
tokens, or full physical identifiers. It cannot itself authorize a write freeze.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from _source_writer_cli_transport import CliError
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

SOURCE_ACCOUNT = "188757775631"
SOURCE_REGION = "us-east-1"
FREEZE_SID = "HeyTimSourceWriteFreeze"
ABSENT = object()
EXPECTED = {
    "table": {"application": "Data", "invite": "InviteAccess"},
    "bucket": {
        "legacy_files": "UserFiles",
        "files": "HeyTimUserFiles",
        "inbound_mail": "IncomingBotMail",
    },
    "queue": {
        "jobs": "AgentJobs",
        "jobs_dlq": "AgentJobsDeadLetter",
        "outbound_mail": "BotEmailOutbox",
        "outbound_mail_dlq": "BotEmailOutboxFailures",
        "inbound_mail_dlq": "BotEmailDeliveryFailures",
        "inbound_capture": "BotEmailInboundCapture",
        "inbound_capture_failures": "BotEmailInboundCaptureFailures",
    },
    "event_rule": {
        "catalog_refresh": "CatalogRefresh",
        "public_availability": "PublicAvailabilitySchedule",
    },
    "schedule_group": {"tasks": "TaskSchedules"},
    "receipt_rule": {"inbound_mail": "BotEmailReceiptRule"},
}
FUNCTION_HANDLERS = {
    "api": "api.handler.handler",
    "public_api": "api.public_handler.handler",
    "worker": "worker.handler.handler",
    "email_receiver": "email_ingest.handler.handler",
    "email_sender": "email_send.handler.handler",
    "autofix_dispatcher": "autofix_dispatcher.handler.handler",
}
TABLE_DENY = {
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:BatchWriteItem",
    "dynamodb:PartiQLInsert",
    "dynamodb:PartiQLUpdate",
    "dynamodb:PartiQLDelete",
}
BUCKET_DENY = {
    "s3:PutObject*",
    "s3:DeleteObject*",
    "s3:AbortMultipartUpload",
    "s3:RestoreObject",
}
MEMORY_DENY = {
    "bedrock-agentcore:UpdateMemory",
    "bedrock-agentcore:DeleteMemory",
    "bedrock-agentcore:CreateEvent",
    "bedrock-agentcore:IngestData",
    "bedrock-agentcore:DeleteEvent",
    "bedrock-agentcore:DeleteMemoryRecord",
    "bedrock-agentcore:BatchCreateMemoryRecords",
    "bedrock-agentcore:BatchUpdateMemoryRecords",
    "bedrock-agentcore:BatchDeleteMemoryRecords",
    "bedrock-agentcore:StartMemoryExtractionJob",
}
NO_POLICY_CODES = {
    "ResourceNotFoundException",
    "PolicyNotFoundException",
    "NoSuchBucketPolicy",
}
NO_LIFECYCLE_CODES = {"NoSuchLifecycleConfiguration"}
NO_REPLICATION_CODES = {"ReplicationConfigurationNotFoundError"}
SAFE_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,79}$")


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    return (
        {part for part in value if isinstance(part, str)}
        if isinstance(value, list)
        else set()
    )


def has_freeze_deny(policy: Any, resource: str, actions: set[str]) -> bool:
    """Recognize only an unconditional, exact-resource Deny with reviewed actions."""
    if isinstance(policy, str):
        try:
            policy = json.loads(policy)
        except json.JSONDecodeError:
            return False
    if not isinstance(policy, dict):
        return False
    statements = policy.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    for statement in statements:
        if not isinstance(statement, dict):
            continue
        principal = statement.get("Principal")
        if principal not in ("*", {"AWS": "*"}):
            continue
        if (
            statement.get("Sid") == FREEZE_SID
            and statement.get("Effect") == "Deny"
            and "Condition" not in statement
            and "NotAction" not in statement
            and "NotResource" not in statement
            and resource in _string_set(statement.get("Resource"))
            and actions <= _string_set(statement.get("Action"))
        ):
            return True
    return False


def _error_code(error: Exception) -> str:
    if isinstance(error, CliError):
        return error.code
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "ClientError")
        return (
            code
            if isinstance(code, str) and SAFE_CODE.fullmatch(code)
            else "ClientError"
        )
    return type(error).__name__


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.blockers: list[str] = []

    def add(self, label: str, **state: Any) -> None:
        self.checks.append({"label": label, **state})

    def block(self, code: str) -> None:
        if code not in self.blockers:
            self.blockers.append(code)

    def data(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "observed_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "source_account": SOURCE_ACCOUNT,
            "source_region": SOURCE_REGION,
            "status": "NO_GO" if self.blockers else "INVENTORY_ONLY",
            "checks": self.checks,
            "blockers": sorted(self.blockers),
            "note": "Read-only inventory; never a cutover approval or complete freeze proof.",
        }


def read(
    report: Report, label: str, call: Callable[[], Any], absent: set[str] = frozenset()
) -> Any:
    try:
        return call()
    except (ClientError, BotoCoreError, NoCredentialsError, CliError) as error:
        code = _error_code(error)
        if code in absent:
            return ABSENT
        report.add(label, state="UNKNOWN", error_code=code)
        report.block(f"{label}_unreadable")
        return None


def pages(
    report: Report, label: str, client: Any, operation: str, key: str, **params: Any
) -> list[dict] | None:
    def fetch() -> list[dict]:
        if not client.can_paginate(operation):
            raise ValueError("paginator unavailable")
        return [
            item
            for page in client.get_paginator(operation).paginate(**params)
            for item in page.get(key, [])
        ]

    try:
        return read(report, label, fetch)
    except ValueError:
        report.add(label, state="UNKNOWN", error_code="PaginatorUnavailable")
        report.block(f"{label}_unreadable")
        return None


def _one(
    report: Report, resources: list[dict], kind: str, label: str, prefix: str
) -> dict | None:
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
        r
        for r in resources
        if r["ResourceType"] == kind
        and r["LogicalResourceId"].startswith(prefix)
        and not r["LogicalResourceId"].startswith(longer_queue_prefixes)
    ]
    if len(matches) != 1 or not matches[0].get("PhysicalResourceId"):
        report.add(label, state="UNKNOWN", match_count=len(matches))
        report.block(f"{label}_missing_or_ambiguous")
        return None
    return matches[0]


def discover_stack(report: Report, cfn: Any, stack_name: str) -> list[dict] | None:
    stack = read(report, "stack", lambda: cfn.describe_stacks(StackName=stack_name))
    if stack is None:
        return None
    stacks = stack.get("Stacks", [])
    if len(stacks) != 1 or stacks[0].get("StackStatus", "").endswith("DELETE_COMPLETE"):
        report.block("source_stack_not_live")
        return None
    pending = [stacks[0]["StackId"]]
    seen: set[str] = set()
    resources: list[dict] = []
    while pending:
        stack_id = pending.pop()
        if stack_id in seen:
            continue
        seen.add(stack_id)
        if f":{SOURCE_REGION}:{SOURCE_ACCOUNT}:" not in stack_id:
            report.block("nested_stack_account_or_region_mismatch")
            return None
        found = pages(
            report,
            "stack_resources",
            cfn,
            "list_stack_resources",
            "StackResourceSummaries",
            StackName=stack_id,
        )
        if found is None:
            return None
        resources.extend(found)
        pending.extend(
            r["PhysicalResourceId"]
            for r in found
            if r["ResourceType"] == "AWS::CloudFormation::Stack"
            and r.get("PhysicalResourceId")
        )
    report.add(
        "stack", state="OBSERVED", nested_stacks=len(seen), resources=len(resources)
    )
    return resources


def note_unclassified_resources(report: Report, resources: list[dict]) -> None:
    kinds = {
        "AWS::DynamoDB::Table": ("table",),
        "AWS::S3::Bucket": ("bucket",),
        "AWS::SQS::Queue": ("queue",),
        "AWS::Events::Rule": ("event_rule",),
        "AWS::Scheduler::ScheduleGroup": ("schedule_group",),
        "AWS::SES::ReceiptRule": ("receipt_rule",),
    }
    for resource_type, (kind,) in kinds.items():
        known_prefixes = tuple(EXPECTED[kind].values())
        auxiliary_prefixes = (
            ("AuditLogs", "HeyTimGatewaySchemas") if kind == "bucket" else ()
        )
        auxiliary = [
            r
            for r in resources
            if r["ResourceType"] == resource_type
            and r["LogicalResourceId"].startswith(auxiliary_prefixes)
        ]
        if auxiliary:
            report.add(f"auxiliary_{kind}", state="OBSERVED", count=len(auxiliary))
            report.block(f"auxiliary_{kind}_requires_review")
        unknown = [
            r
            for r in resources
            if r["ResourceType"] == resource_type
            and not r["LogicalResourceId"].startswith(
                known_prefixes + auxiliary_prefixes
            )
        ]
        if unknown:
            report.add(
                f"unclassified_{kind}",
                state="UNKNOWN",
                count=len(unknown),
                id_sha256_12=[
                    fingerprint(r.get("PhysicalResourceId", "")) for r in unknown
                ],
            )
            report.block(f"unclassified_{kind}_requires_review")


def inspect_tables(
    report: Report, resources: list[dict], dynamodb: Any
) -> dict[str, str]:
    names: dict[str, str] = {}
    for label, logical in EXPECTED["table"].items():
        ref = _one(report, resources, "AWS::DynamoDB::Table", f"table_{label}", logical)
        if not ref:
            continue
        name = ref["PhysicalResourceId"]
        desc = read(
            report,
            f"table_{label}_describe",
            lambda name=name: dynamodb.describe_table(TableName=name),
        )
        ttl = read(
            report,
            f"table_{label}_ttl",
            lambda name=name: dynamodb.describe_time_to_live(TableName=name),
        )
        if desc is None or ttl is None:
            continue
        table = desc["Table"]
        arn = table["TableArn"]
        if f":{SOURCE_REGION}:{SOURCE_ACCOUNT}:" not in arn:
            report.block(f"table_{label}_account_or_region_mismatch")
        policy = read(
            report,
            f"table_{label}_policy",
            lambda arn=arn: dynamodb.get_resource_policy(ResourceArn=arn),
            NO_POLICY_CODES,
        )
        frozen = (
            policy is not None
            and policy is not ABSENT
            and has_freeze_deny(policy.get("Policy"), arn, TABLE_DENY)
        )
        ttl_state = ttl.get("TimeToLiveDescription", {}).get(
            "TimeToLiveStatus", "UNKNOWN"
        )
        replica_count = len(table.get("Replicas", []))
        report.add(
            f"table_{label}",
            state=table.get("TableStatus", "UNKNOWN"),
            id_sha256_12=fingerprint(name),
            ttl=ttl_state,
            replicas=replica_count,
            freeze_deny=frozen,
        )
        if ttl_state != "DISABLED" or replica_count or not frozen:
            report.block(f"table_{label}_not_frozen")
        names[label] = name
    return names


def inspect_buckets(report: Report, resources: list[dict], s3: Any) -> dict[str, str]:
    names: dict[str, str] = {}
    for label, logical in EXPECTED["bucket"].items():
        ref = _one(report, resources, "AWS::S3::Bucket", f"bucket_{label}", logical)
        if not ref:
            continue
        name = ref["PhysicalResourceId"]
        owner = {"Bucket": name, "ExpectedBucketOwner": SOURCE_ACCOUNT}
        location = read(
            report,
            f"bucket_{label}_location",
            lambda owner=owner: s3.get_bucket_location(**owner),
        )
        version = read(
            report,
            f"bucket_{label}_versioning",
            lambda owner=owner: s3.get_bucket_versioning(**owner),
        )
        lifecycle = read(
            report,
            f"bucket_{label}_lifecycle",
            lambda owner=owner: s3.get_bucket_lifecycle_configuration(**owner),
            NO_LIFECYCLE_CODES,
        )
        replication = read(
            report,
            f"bucket_{label}_replication",
            lambda owner=owner: s3.get_bucket_replication(**owner),
            NO_REPLICATION_CODES,
        )
        policy = read(
            report,
            f"bucket_{label}_policy",
            lambda owner=owner: s3.get_bucket_policy(**owner),
            NO_POLICY_CODES,
        )
        if any(
            value is None
            for value in (location, version, lifecycle, replication, policy)
        ):
            continue
        bucket_region = location.get("LocationConstraint") or "us-east-1"
        if bucket_region != SOURCE_REGION:
            report.block(f"bucket_{label}_region_mismatch")
        lifecycle_rules = [] if lifecycle is ABSENT else lifecycle.get("Rules", [])
        replication_rules = (
            []
            if replication is ABSENT
            else replication.get("ReplicationConfiguration", {}).get("Rules", [])
        )
        enabled_lifecycle = sum(r.get("Status") == "Enabled" for r in lifecycle_rules)
        enabled_replication = sum(
            r.get("Status") == "Enabled" for r in replication_rules
        )
        arn = f"arn:aws:s3:::{name}/*"
        frozen = policy is not ABSENT and has_freeze_deny(
            policy.get("Policy"), arn, BUCKET_DENY
        )
        status = version.get("Status", "Unversioned")
        report.add(
            f"bucket_{label}",
            state="OBSERVED",
            id_sha256_12=fingerprint(name),
            region_matches=bucket_region == SOURCE_REGION,
            versioning=status,
            lifecycle_enabled=enabled_lifecycle,
            replication_enabled=enabled_replication,
            freeze_deny=frozen,
        )
        if enabled_lifecycle or enabled_replication or not frozen:
            report.block(f"bucket_{label}_not_frozen")
        if label != "inbound_mail" and status != "Enabled":
            report.block(f"bucket_{label}_version_history_unavailable")
        names[label] = name
    return names


def inspect_queues(report: Report, resources: list[dict], sqs: Any) -> dict[str, str]:
    arns: dict[str, str] = {}
    for label, logical in EXPECTED["queue"].items():
        ref = _one(report, resources, "AWS::SQS::Queue", f"queue_{label}", logical)
        if not ref:
            continue
        url = ref["PhysicalResourceId"]
        attrs = read(
            report,
            f"queue_{label}_attributes",
            lambda url=url: sqs.get_queue_attributes(
                QueueUrl=url,
                AttributeNames=[
                    "QueueArn",
                    "ApproximateNumberOfMessages",
                    "ApproximateNumberOfMessagesNotVisible",
                    "ApproximateNumberOfMessagesDelayed",
                ],
            ),
        )
        if attrs is None:
            continue
        data = attrs.get("Attributes", {})
        arn = data.get("QueueArn", "")
        if f":{SOURCE_REGION}:{SOURCE_ACCOUNT}:" not in arn:
            report.block(f"queue_{label}_account_or_region_mismatch")
        counts = {
            key: int(data.get(key, "-1"))
            for key in (
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            )
        }
        report.add(
            f"queue_{label}",
            state="OBSERVED",
            id_sha256_12=fingerprint(url),
            visible=counts["ApproximateNumberOfMessages"],
            in_flight=counts["ApproximateNumberOfMessagesNotVisible"],
            delayed=counts["ApproximateNumberOfMessagesDelayed"],
        )
        # This unconsumed queue deliberately holds inbound SES notifications
        # while application writers are stopped. Its subscription DLQ must
        # remain empty; failures there need investigation before a cutover.
        if label != "inbound_capture" and any(value != 0 for value in counts.values()):
            report.block(f"queue_{label}_not_drained")
        arns[label] = arn
    return arns


def inspect_email_and_logs(
    report: Report,
    resources: list[dict],
    ses: Any,
    logs: Any,
    dispatcher_env: dict[str, str] | None = None,
) -> None:
    rule = _one(
        report,
        resources,
        "AWS::SES::ReceiptRule",
        "receipt_rule",
        "BotEmailReceiptRule",
    )
    result = read(
        report, "active_receipt_rules", lambda: ses.describe_active_receipt_rule_set()
    )
    if result is not None:
        active = result.get("Rules", [])
        physical = rule.get("PhysicalResourceId", "") if rule else ""
        matches = [
            r
            for r in active
            if r.get("Name") == physical
            or (physical and physical.endswith("|" + r.get("Name", "")))
        ]
        report.add(
            "receipt_rule",
            state="OBSERVED",
            active_rules=len(active),
            matching_source_rules=len(matches),
            enabled=sum(r.get("Enabled") is True for r in matches),
        )
        if len(matches) != 1 or matches[0].get("Enabled") is not False:
            report.block("receipt_rule_not_proven_disabled")
    if dispatcher_env is None:
        report.block("autofix_subscription_sources_unknown")
        return
    names = [
        part
        for part in dispatcher_env.get("AUTOFIX_ALLOWED_LOG_GROUPS", "").split(",")
        if part
    ]
    if len(names) != 2:
        report.block("autofix_subscription_sources_unknown")
        return
    for index, name in enumerate(names):
        filters = pages(
            report,
            f"autofix_subscription_{index}",
            logs,
            "describe_subscription_filters",
            "subscriptionFilters",
            logGroupName=name,
        )
        if filters is not None:
            report.add(
                f"autofix_subscription_{index}", state="OBSERVED", count=len(filters)
            )
            if filters:
                report.block("autofix_log_delivery_pending_reconciliation")
