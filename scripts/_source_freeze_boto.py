"""Boto3 transport for private read-only freeze capture and disposable drills.

The source-account write guard is unconditional. Every other write requires an
exact disposable resource ID allowlist supplied at construction time. There is
no CLI or environment variable that bypasses the source guard.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from _source_freeze_plan import FreezePlanError, Ref
from _source_writer_preflight_core import SOURCE_ACCOUNT, SOURCE_REGION
from botocore.config import Config
from botocore.exceptions import ClientError

SCHEDULE_UPDATE_FIELDS = (
    "ActionAfterCompletion",
    "Description",
    "EndDate",
    "FlexibleTimeWindow",
    "KmsKeyArn",
    "ScheduleExpression",
    "ScheduleExpressionTimezone",
    "StartDate",
    "State",
    "Target",
)


def _error_code(error: ClientError) -> str:
    return error.response.get("Error", {}).get("Code", "ClientError")


def _json_safe(value: Any) -> Any:
    def convert(item: Any) -> str:
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError(f"AWS response contains unsupported {type(item).__name__}")

    return json.loads(json.dumps(value, default=convert))


def _parse_policy(raw: str) -> dict:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise FreezePlanError("resource policy is not a JSON object")
    return parsed


def _resource_id(ref: Ref) -> str:
    identity = ref.identity
    if ref.kind in {
        "bucket_lifecycle",
        "bucket_policy",
        "lambda_concurrency",
        "event_rule",
    }:
        return identity["name"]
    if ref.kind in {"table_ttl", "table_policy", "agentcore_policy"}:
        return identity["arn"]
    if ref.kind == "queue_mapping":
        return identity["uuid"]
    if ref.kind == "schedule":
        return f"{identity['group']}/{identity['name']}"
    if ref.kind == "ses_rule":
        return f"{identity['rule_set']}/{identity['rule_name']}"
    raise FreezePlanError("unknown resource type")


class BotoFreezeAdapter:
    kind = "aws-disposable"

    def __init__(
        self,
        session: Any,
        expected_account: str,
        allowed_disposable_ids: frozenset[str] = frozenset(),
    ) -> None:
        if session.region_name != SOURCE_REGION:
            raise FreezePlanError(
                "AWS session region differs from reviewed source region"
            )
        if not isinstance(expected_account, str) or len(expected_account) != 12:
            raise FreezePlanError("expected AWS account malformed")
        self.config = Config(
            retries={"total_max_attempts": 2, "mode": "standard"},
            connect_timeout=5,
            read_timeout=15,
        )
        self.session = session
        self.clients: dict[str, Any] = {}
        actual_account = self.client("sts").get_caller_identity().get("Account")
        if actual_account != expected_account:
            raise FreezePlanError("AWS caller account differs from exact target")
        self.account = actual_account
        self.allowed_disposable_ids = allowed_disposable_ids
        self.allow_disposable_writes = bool(allowed_disposable_ids)

    def client(self, service: str) -> Any:
        if service not in self.clients:
            self.clients[service] = self.session.client(service, config=self.config)
        return self.clients[service]

    def _owner(self, ref: Ref) -> dict[str, str]:
        return {"Bucket": ref.identity["name"], "ExpectedBucketOwner": self.account}

    def _read_policy(
        self, service: str, arn: str, *, memory: bool = False
    ) -> dict | None:
        client = self.client(service)
        try:
            if service == "dynamodb":
                result = client.get_resource_policy(ResourceArn=arn)
                return _parse_policy(result["Policy"])
            result = client.get_resource_policy(resourceArn=arn)
            raw = result.get("policy")
            if raw is None:
                if memory:
                    prefix = (
                        f"arn:aws:bedrock-agentcore:{SOURCE_REGION}:"
                        f"{self.account}:memory/"
                    )
                    if not arn.startswith(prefix):
                        raise FreezePlanError("Memory policy ARN differs from target")
                    memory_id = arn[len(prefix) :]
                    if not memory_id or "/" in memory_id:
                        raise FreezePlanError("Memory policy ARN is malformed")
                    described = client.get_memory(
                        memoryId=memory_id, view="full"
                    ).get("memory", {})
                    if (
                        described.get("arn") != arn
                        or described.get("id") != memory_id
                        or described.get("status") != "ACTIVE"
                    ):
                        raise FreezePlanError(
                            "Memory policy absence lacks exact ACTIVE target corroboration"
                        )
                return None
            return _parse_policy(raw)
        except ClientError as error:
            code = _error_code(error)
            if service == "dynamodb" and code == "PolicyNotFoundException":
                return None
            if (
                service == "bedrock-agentcore-control"
                and code == "ResourceNotFoundException"
            ):
                raise FreezePlanError(
                    "AgentCore resource-policy target missing or API unsupported"
                ) from error
            raise

    def read(self, ref: Ref) -> Any:
        kind = ref.kind
        if kind == "bucket_lifecycle":
            try:
                result = self.client("s3").get_bucket_lifecycle_configuration(
                    **self._owner(ref)
                )
            except ClientError as error:
                if _error_code(error) == "NoSuchLifecycleConfiguration":
                    return None
                raise
            keep = {
                key: result[key]
                for key in ("Rules", "TransitionDefaultMinimumObjectSize")
                if key in result
            }
            return _json_safe(keep)
        if kind == "bucket_policy":
            try:
                result = self.client("s3").get_bucket_policy(**self._owner(ref))
            except ClientError as error:
                if _error_code(error) == "NoSuchBucketPolicy":
                    return None
                raise
            return _parse_policy(result["Policy"])
        if kind == "table_ttl":
            result = self.client("dynamodb").describe_time_to_live(
                TableName=ref.identity["name"]
            )
            description = result.get("TimeToLiveDescription", {})
            return {
                "status": description.get("TimeToLiveStatus", "UNKNOWN"),
                "attribute": description.get("AttributeName"),
            }
        if kind == "table_policy":
            return self._read_policy("dynamodb", ref.identity["arn"])
        if kind == "lambda_concurrency":
            result = self.client("lambda").get_function_concurrency(
                FunctionName=ref.identity["name"]
            )
            return result.get("ReservedConcurrentExecutions")
        if kind == "queue_mapping":
            result = self.client("lambda").get_event_source_mapping(
                UUID=ref.identity["uuid"]
            )
            state = result.get("State")
            if state not in {"Enabled", "Disabled"}:
                raise FreezePlanError("queue mapping is transitional or unknown")
            return state == "Enabled"
        if kind == "event_rule":
            result = self.client("events").describe_rule(Name=ref.identity["name"])
            return result.get("State", "UNKNOWN")
        if kind == "schedule":
            result = self.client("scheduler").get_schedule(
                Name=ref.identity["name"], GroupName=ref.identity["group"]
            )
            update = {
                key: result[key] for key in SCHEDULE_UPDATE_FIELDS if key in result
            }
            update["Name"] = ref.identity["name"]
            update["GroupName"] = ref.identity["group"]
            if (
                not {"ScheduleExpression", "FlexibleTimeWindow", "Target", "State"}
                <= update.keys()
            ):
                raise FreezePlanError("schedule update payload incomplete")
            return _json_safe(update)
        if kind == "ses_rule":
            ses = self.client("ses")
            active = ses.describe_active_receipt_rule_set()
            if active.get("Metadata", {}).get("Name") != ref.identity["rule_set"]:
                raise FreezePlanError("SES active rule set changed")
            result = ses.describe_receipt_rule(
                RuleSetName=ref.identity["rule_set"], RuleName=ref.identity["rule_name"]
            )
            rule = result["Rule"]
            if rule.get("Name") != ref.identity["rule_name"]:
                raise FreezePlanError("SES receipt rule identity changed")
            return _json_safe(rule)
        if kind == "agentcore_policy":
            return self._read_policy(
                "bedrock-agentcore-control",
                ref.identity["arn"],
                memory=ref.identity["role"] == "memory",
            )
        raise FreezePlanError("unsupported AWS read control")

    def _guard_write(self, ref: Ref) -> None:
        if self.account == SOURCE_ACCOUNT:
            raise FreezePlanError(
                "source-account AWS writes are unconditionally disabled"
            )
        if any(
            value.startswith("arn:") and f":{SOURCE_REGION}:{self.account}:" not in value
            for value in ref.identity.values()
        ):
            raise FreezePlanError("cross-account or cross-region ARN write disabled")
        if ref.kind == "table_ttl" or ref.kind == "table_policy":
            identity = ref.identity
            if identity["arn"] != (
                f"arn:aws:dynamodb:{SOURCE_REGION}:{self.account}:table/"
                f"{identity['name']}"
            ):
                raise FreezePlanError("DynamoDB table name and ARN differ")
        if _resource_id(ref) not in self.allowed_disposable_ids:
            raise FreezePlanError("AWS write resource is not in disposable allowlist")

    def write(self, ref: Ref, expected: Any, value: Any) -> None:
        self._guard_write(ref)
        if self.read(ref) != expected:
            raise FreezePlanError("AWS state drifted immediately before write")
        kind = ref.kind
        if kind == "bucket_lifecycle":
            s3 = self.client("s3")
            if value is None:
                s3.delete_bucket_lifecycle(**self._owner(ref))
            else:
                parameters: dict[str, Any] = {
                    **self._owner(ref),
                    "LifecycleConfiguration": {"Rules": value["Rules"]},
                }
                if "TransitionDefaultMinimumObjectSize" in value:
                    parameters["TransitionDefaultMinimumObjectSize"] = value[
                        "TransitionDefaultMinimumObjectSize"
                    ]
                s3.put_bucket_lifecycle_configuration(**parameters)
            return
        if kind == "bucket_policy":
            s3 = self.client("s3")
            if value is None:
                s3.delete_bucket_policy(**self._owner(ref))
            else:
                s3.put_bucket_policy(
                    **self._owner(ref), Policy=json.dumps(value, sort_keys=True)
                )
            return
        if kind == "table_ttl":
            attribute = value.get("attribute") or expected.get("attribute")
            if not attribute:
                raise FreezePlanError("cannot update TTL without original attribute")
            self.client("dynamodb").update_time_to_live(
                TableName=ref.identity["name"],
                TimeToLiveSpecification={
                    "Enabled": value["status"] == "ENABLED",
                    "AttributeName": attribute,
                },
            )
            return
        if kind == "table_policy":
            dynamodb = self.client("dynamodb")
            arn = ref.identity["arn"]
            try:
                revision = dynamodb.get_resource_policy(ResourceArn=arn)["RevisionId"]
            except ClientError as error:
                if _error_code(error) != "PolicyNotFoundException":
                    raise
                revision = "NO_POLICY"
            if value is None:
                if revision != "NO_POLICY":
                    dynamodb.delete_resource_policy(
                        ResourceArn=arn, ExpectedRevisionId=revision
                    )
            else:
                dynamodb.put_resource_policy(
                    ResourceArn=arn,
                    Policy=json.dumps(value, sort_keys=True),
                    ExpectedRevisionId=revision,
                )
            return
        if kind == "lambda_concurrency":
            lambdas = self.client("lambda")
            if value is None:
                lambdas.delete_function_concurrency(FunctionName=ref.identity["name"])
            else:
                lambdas.put_function_concurrency(
                    FunctionName=ref.identity["name"],
                    ReservedConcurrentExecutions=value,
                )
            return
        if kind == "queue_mapping":
            self.client("lambda").update_event_source_mapping(
                UUID=ref.identity["uuid"], Enabled=value
            )
            return
        if kind == "event_rule":
            events = self.client("events")
            method = events.disable_rule if value == "DISABLED" else events.enable_rule
            method(Name=ref.identity["name"])
            return
        if kind == "schedule":
            self.client("scheduler").update_schedule(**value)
            return
        if kind == "ses_rule":
            self.client("ses").update_receipt_rule(
                RuleSetName=ref.identity["rule_set"], Rule=value
            )
            return
        if kind == "agentcore_policy":
            control = self.client("bedrock-agentcore-control")
            arn = ref.identity["arn"]
            if value is None:
                control.delete_resource_policy(resourceArn=arn)
            else:
                control.put_resource_policy(
                    resourceArn=arn, policy=json.dumps(value, sort_keys=True)
                )
            return
        raise FreezePlanError("unsupported AWS write control")
