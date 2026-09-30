"""Botocore Stubber contracts for the guarded freeze AWS transport."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _source_freeze_boto import BotoFreezeAdapter
from _source_freeze_plan import FreezePlanError, Ref
from _source_writer_preflight_core import SOURCE_ACCOUNT, SOURCE_REGION

DESTINATION = "820323452649"
FIXTURE_MEMORY_ID = "FixtureMemory-0123456789"
OTHER_MEMORY_ID = "OtherMemory-0123456789"


class StubSession:
    region_name = SOURCE_REGION

    def __init__(self, clients: dict[str, Any]):
        self.clients = clients

    def client(self, service: str, **_kwargs: Any) -> Any:
        return self.clients[service]


@contextmanager
def aws_adapter(
    services: set[str],
    account: str = DESTINATION,
    allowed: frozenset[str] = frozenset(),
) -> Iterator[tuple[BotoFreezeAdapter, dict[str, Stubber]]]:
    session = boto3.Session(
        aws_access_key_id="stub-access",
        aws_secret_access_key="stub-secret",
        region_name=SOURCE_REGION,
    )
    clients = {service: session.client(service) for service in services | {"sts"}}
    stubs = {service: Stubber(client) for service, client in clients.items()}
    stubs["sts"].add_response(
        "get_caller_identity",
        {
            "Account": account,
            "Arn": f"arn:aws:iam::{account}:role/fixture",
            "UserId": "fixture",
        },
        {},
    )
    for stub in stubs.values():
        stub.activate()
    try:
        yield BotoFreezeAdapter(StubSession(clients), account, allowed), stubs
        for stub in stubs.values():
            stub.assert_no_pending_responses()
    finally:
        for stub in stubs.values():
            stub.deactivate()


def ref(key: str, kind: str, **identity: str) -> Ref:
    return Ref(key, kind, "fixture", identity)


def test_source_account_write_guard_precedes_all_resource_calls() -> None:
    target = ref("policy_bucket", "bucket_policy", name="source-bucket")
    with aws_adapter({"s3"}, SOURCE_ACCOUNT, frozenset({"source-bucket"})) as (
        adapter,
        _,
    ), pytest.raises(FreezePlanError, match="unconditionally disabled"):
        adapter.write(target, None, {"Statement": []})


def test_exact_account_and_region_bind_before_capture() -> None:
    session = boto3.Session(
        aws_access_key_id="stub-access",
        aws_secret_access_key="stub-secret",
        region_name="us-west-2",
    )
    with pytest.raises(FreezePlanError, match="region"):
        BotoFreezeAdapter(session, DESTINATION)
    with aws_adapter(set(), DESTINATION) as (adapter, _):
        assert adapter.account == DESTINATION


def test_disposable_credentials_cannot_write_source_arn() -> None:
    name = "source-table"
    arn = f"arn:aws:dynamodb:{SOURCE_REGION}:{SOURCE_ACCOUNT}:table/{name}"
    target = ref("policy", "table_policy", name=name, arn=arn)
    with aws_adapter({"dynamodb"}, allowed=frozenset({arn})) as (
        adapter,
        _,
    ), pytest.raises(FreezePlanError, match="cross-account"):
        adapter.write(target, None, {"Statement": []})


def test_aws_write_failure_propagates_without_followup_mutation() -> None:
    bucket = "fixture-bucket"
    target = ref("policy", "bucket_policy", name=bucket)
    owner = {"Bucket": bucket, "ExpectedBucketOwner": DESTINATION}
    frozen = {"Version": "2012-10-17", "Statement": []}
    with aws_adapter({"s3"}, allowed=frozenset({bucket})) as (adapter, stubs):
        stubs["s3"].add_client_error(
            "get_bucket_policy",
            "NoSuchBucketPolicy",
            http_status_code=404,
            expected_params=owner,
        )
        stubs["s3"].add_client_error(
            "put_bucket_policy",
            "AccessDenied",
            http_status_code=403,
            expected_params={
                **owner,
                "Policy": json.dumps(frozen, sort_keys=True),
            },
        )
        with pytest.raises(ClientError) as error:
            adapter.write(target, None, frozen)
        assert error.value.response["Error"]["Code"] == "AccessDenied"


def test_aws_state_drift_refuses_write() -> None:
    bucket = "fixture-bucket"
    target = ref("policy", "bucket_policy", name=bucket)
    owner = {"Bucket": bucket, "ExpectedBucketOwner": DESTINATION}
    with aws_adapter({"s3"}, allowed=frozenset({bucket})) as (adapter, stubs):
        stubs["s3"].add_response(
            "get_bucket_policy", {"Policy": json.dumps({"Statement": []})}, owner
        )
        with pytest.raises(FreezePlanError, match="drifted"):
            adapter.write(target, None, {"Statement": []})


def test_s3_lifecycle_preserves_small_object_default_and_owner() -> None:
    bucket = "fixture-bucket"
    target = ref("lifecycle", "bucket_lifecycle", name=bucket)
    owner = {"Bucket": bucket, "ExpectedBucketOwner": DESTINATION}
    original = {
        "Rules": [
            {
                "ID": "expire",
                "Status": "Enabled",
                "Filter": {"Prefix": "users/"},
                "Expiration": {"Days": 30},
            }
        ],
        "TransitionDefaultMinimumObjectSize": "varies_by_storage_class",
    }
    disabled = {
        **original,
        "Rules": [
            {
                "ID": "expire",
                "Status": "Disabled",
                "Filter": {"Prefix": "users/"},
                "Expiration": {"Days": 30},
            }
        ],
    }
    with aws_adapter({"s3"}, allowed=frozenset({bucket})) as (adapter, stubs):
        s3 = stubs["s3"]
        s3.add_response("get_bucket_lifecycle_configuration", original, owner)
        assert adapter.read(target) == original
        s3.add_response("get_bucket_lifecycle_configuration", original, owner)
        s3.add_response(
            "put_bucket_lifecycle_configuration",
            {},
            {
                **owner,
                "LifecycleConfiguration": {"Rules": disabled["Rules"]},
                "TransitionDefaultMinimumObjectSize": "varies_by_storage_class",
            },
        )
        adapter.write(target, original, disabled)
        s3.add_response("get_bucket_lifecycle_configuration", disabled, owner)
        s3.add_response(
            "put_bucket_lifecycle_configuration",
            {},
            {
                **owner,
                "LifecycleConfiguration": {"Rules": original["Rules"]},
                "TransitionDefaultMinimumObjectSize": "varies_by_storage_class",
            },
        )
        adapter.write(target, disabled, original)


def test_s3_absent_policy_roundtrips_as_absence() -> None:
    bucket = "fixture-bucket"
    target = ref("policy", "bucket_policy", name=bucket)
    owner = {"Bucket": bucket, "ExpectedBucketOwner": DESTINATION}
    frozen = {
        "Version": "2012-10-17",
        "Statement": [{"Sid": "FixtureDeny", "Effect": "Deny"}],
    }
    with aws_adapter({"s3"}, allowed=frozenset({bucket})) as (adapter, stubs):
        s3 = stubs["s3"]
        s3.add_client_error(
            "get_bucket_policy",
            "NoSuchBucketPolicy",
            http_status_code=404,
            expected_params=owner,
        )
        assert adapter.read(target) is None
        s3.add_client_error(
            "get_bucket_policy",
            "NoSuchBucketPolicy",
            http_status_code=404,
            expected_params=owner,
        )
        s3.add_response(
            "put_bucket_policy",
            {},
            {**owner, "Policy": json.dumps(frozen, sort_keys=True)},
        )
        adapter.write(target, None, frozen)
        s3.add_response("get_bucket_policy", {"Policy": json.dumps(frozen)}, owner)
        s3.add_response("delete_bucket_policy", {}, owner)
        adapter.write(target, frozen, None)


def test_dynamodb_ttl_and_no_policy_revision_payloads() -> None:
    name = "fixture-table"
    arn = f"arn:aws:dynamodb:{SOURCE_REGION}:{DESTINATION}:table/{name}"
    ttl_ref = ref("ttl", "table_ttl", name=name, arn=arn)
    policy_ref = ref("policy", "table_policy", name=name, arn=arn)
    before = {"status": "ENABLED", "attribute": "expiresAt"}
    after = {"status": "DISABLED", "attribute": "expiresAt"}
    frozen = {
        "Version": "2012-10-17",
        "Statement": [{"Sid": "FixtureDeny", "Effect": "Deny"}],
    }
    with aws_adapter({"dynamodb"}, allowed=frozenset({arn})) as (adapter, stubs):
        ddb = stubs["dynamodb"]
        ttl_result = {
            "TimeToLiveDescription": {
                "TimeToLiveStatus": "ENABLED",
                "AttributeName": "expiresAt",
            }
        }
        ddb.add_response("describe_time_to_live", ttl_result, {"TableName": name})
        assert adapter.read(ttl_ref) == before
        ddb.add_response("describe_time_to_live", ttl_result, {"TableName": name})
        ddb.add_response(
            "update_time_to_live",
            {
                "TimeToLiveSpecification": {
                    "Enabled": False,
                    "AttributeName": "expiresAt",
                }
            },
            {
                "TableName": name,
                "TimeToLiveSpecification": {
                    "Enabled": False,
                    "AttributeName": "expiresAt",
                },
            },
        )
        adapter.write(ttl_ref, before, after)
        ddb.add_client_error(
            "get_resource_policy",
            "PolicyNotFoundException",
            http_status_code=404,
            expected_params={"ResourceArn": arn},
        )
        assert adapter.read(policy_ref) is None
        ddb.add_client_error(
            "get_resource_policy",
            "PolicyNotFoundException",
            http_status_code=404,
            expected_params={"ResourceArn": arn},
        )
        ddb.add_client_error(
            "get_resource_policy",
            "PolicyNotFoundException",
            http_status_code=404,
            expected_params={"ResourceArn": arn},
        )
        ddb.add_response(
            "put_resource_policy",
            {"RevisionId": "revision-1"},
            {
                "ResourceArn": arn,
                "Policy": json.dumps(frozen, sort_keys=True),
                "ExpectedRevisionId": "NO_POLICY",
            },
        )
        adapter.write(policy_ref, None, frozen)
        ddb.add_response(
            "get_resource_policy",
            {"Policy": json.dumps(frozen), "RevisionId": "revision-1"},
            {"ResourceArn": arn},
        )
        ddb.add_response(
            "get_resource_policy",
            {"Policy": json.dumps(frozen), "RevisionId": "revision-1"},
            {"ResourceArn": arn},
        )
        ddb.add_response(
            "delete_resource_policy",
            {"RevisionId": "revision-2"},
            {"ResourceArn": arn, "ExpectedRevisionId": "revision-1"},
        )
        adapter.write(policy_ref, frozen, None)


def test_lambda_mapping_concurrency_and_event_rule_payloads() -> None:
    function = "fixture-function"
    uuid = "00000000-0000-4000-8000-000000000001"
    rule = "fixture-rule"
    concurrency = ref("concurrency", "lambda_concurrency", name=function)
    mapping = ref("mapping", "queue_mapping", uuid=uuid)
    event = ref("event", "event_rule", name=rule)
    with aws_adapter(
        {"lambda", "events"}, allowed=frozenset({function, uuid, rule})
    ) as (adapter, stubs):
        lambdas, events = stubs["lambda"], stubs["events"]
        lambdas.add_response("get_function_concurrency", {}, {"FunctionName": function})
        assert adapter.read(concurrency) is None
        lambdas.add_response("get_function_concurrency", {}, {"FunctionName": function})
        lambdas.add_response(
            "put_function_concurrency",
            {"ReservedConcurrentExecutions": 0},
            {"FunctionName": function, "ReservedConcurrentExecutions": 0},
        )
        adapter.write(concurrency, None, 0)
        lambdas.add_response(
            "get_event_source_mapping",
            {"UUID": uuid, "State": "Enabled"},
            {"UUID": uuid},
        )
        assert adapter.read(mapping) is True
        lambdas.add_response(
            "get_event_source_mapping",
            {"UUID": uuid, "State": "Enabled"},
            {"UUID": uuid},
        )
        lambdas.add_response(
            "update_event_source_mapping",
            {"UUID": uuid, "State": "Disabling"},
            {"UUID": uuid, "Enabled": False},
        )
        adapter.write(mapping, True, False)
        events.add_response(
            "describe_rule",
            {
                "Name": rule,
                "Arn": f"arn:aws:events:{SOURCE_REGION}:{DESTINATION}:rule/{rule}",
                "State": "ENABLED",
                "EventBusName": "default",
            },
            {"Name": rule},
        )
        assert adapter.read(event) == "ENABLED"
        events.add_response(
            "describe_rule",
            {
                "Name": rule,
                "Arn": f"arn:aws:events:{SOURCE_REGION}:{DESTINATION}:rule/{rule}",
                "State": "ENABLED",
                "EventBusName": "default",
            },
            {"Name": rule},
        )
        events.add_response("disable_rule", {}, {"Name": rule})
        adapter.write(event, "ENABLED", "DISABLED")


def test_schedule_ses_and_agentcore_full_update_payloads() -> None:
    schedule = ref(
        "schedule", "schedule", group="fixture-group", name="fixture-schedule"
    )
    receipt = ref(
        "ses", "ses_rule", rule_set="fixture-set", rule_name="fixture-receipt"
    )
    arn = f"arn:aws:bedrock-agentcore:{SOURCE_REGION}:{DESTINATION}:runtime/fixture"
    runtime = ref("runtime", "agentcore_policy", arn=arn, role="runtime")
    schedule_get = {
        "Name": "fixture-schedule",
        "GroupName": "fixture-group",
        "State": "ENABLED",
        "ScheduleExpression": "rate(1 hour)",
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "Target": {
            "Arn": "arn:aws:lambda:us-east-1:820323452649:function:fixture",
            "RoleArn": "arn:aws:iam::820323452649:role/fixture",
        },
        "Description": "fixture",
        "ScheduleExpressionTimezone": "UTC",
        "StartDate": datetime(2026, 10, 1, tzinfo=UTC),
    }
    schedule_snapshot = {
        **schedule_get,
        "StartDate": "2026-10-01T00:00:00+00:00",
    }
    schedule_after = {**schedule_snapshot, "State": "DISABLED"}
    rule = {
        "Name": "fixture-receipt",
        "Enabled": True,
        "Recipients": ["fixture@example.invalid"],
        "Actions": [{"S3Action": {"BucketName": "fixture-mail"}}],
    }
    disabled_rule = {**rule, "Enabled": False}
    policy = {
        "Version": "2012-10-17",
        "Statement": [{"Sid": "FixtureDeny", "Effect": "Deny"}],
    }
    allowed = frozenset(
        {"fixture-group/fixture-schedule", "fixture-set/fixture-receipt", arn}
    )
    with aws_adapter(
        {"scheduler", "ses", "bedrock-agentcore-control"}, allowed=allowed
    ) as (adapter, stubs):
        scheduler, ses, core = (
            stubs["scheduler"],
            stubs["ses"],
            stubs["bedrock-agentcore-control"],
        )
        lookup = {"Name": "fixture-schedule", "GroupName": "fixture-group"}
        scheduler.add_response("get_schedule", schedule_get, lookup)
        assert adapter.read(schedule) == schedule_snapshot
        scheduler.add_response("get_schedule", schedule_get, lookup)
        scheduler.add_response(
            "update_schedule",
            {"ScheduleArn": f"arn:aws:scheduler:{SOURCE_REGION}:{DESTINATION}:schedule/fixture-group/fixture-schedule"},
            schedule_after,
        )
        adapter.write(schedule, schedule_snapshot, schedule_after)
        ses.add_response(
            "describe_active_receipt_rule_set",
            {"Metadata": {"Name": "fixture-set"}, "Rules": [rule]},
            {},
        )
        ses.add_response(
            "describe_receipt_rule",
            {"Rule": rule},
            {"RuleSetName": "fixture-set", "RuleName": "fixture-receipt"},
        )
        assert adapter.read(receipt) == rule
        ses.add_response(
            "describe_active_receipt_rule_set",
            {"Metadata": {"Name": "fixture-set"}, "Rules": [rule]},
            {},
        )
        ses.add_response(
            "describe_receipt_rule",
            {"Rule": rule},
            {"RuleSetName": "fixture-set", "RuleName": "fixture-receipt"},
        )
        ses.add_response(
            "update_receipt_rule",
            {},
            {"RuleSetName": "fixture-set", "Rule": disabled_rule},
        )
        adapter.write(receipt, rule, disabled_rule)
        core.add_response("get_resource_policy", {}, {"resourceArn": arn})
        assert adapter.read(runtime) is None
        core.add_response("get_resource_policy", {}, {"resourceArn": arn})
        core.add_response(
            "put_resource_policy",
            {"policy": json.dumps(policy)},
            {"resourceArn": arn, "policy": json.dumps(policy, sort_keys=True)},
        )
        adapter.write(runtime, None, policy)


def memory_response(arn: str, *, status: str = "ACTIVE", memory_id: str | None = None) -> dict:
    return {
        "memory": {
            "arn": arn,
            "id": memory_id or arn.rsplit("/", 1)[-1],
            "name": "fixture",
            "eventExpiryDuration": 3,
            "status": status,
            "createdAt": datetime(2026, 9, 29, tzinfo=UTC),
            "updatedAt": datetime(2026, 9, 29, tzinfo=UTC),
        }
    }


def test_memory_empty_policy_requires_exact_active_memory() -> None:
    arn = f"arn:aws:bedrock-agentcore:{SOURCE_REGION}:{DESTINATION}:memory/{FIXTURE_MEMORY_ID}"
    memory = ref("memory", "agentcore_policy", arn=arn, role="memory")
    with aws_adapter({"bedrock-agentcore-control"}) as (adapter, stubs):
        core = stubs["bedrock-agentcore-control"]
        core.add_response("get_resource_policy", {}, {"resourceArn": arn})
        core.add_response(
            "get_memory",
            memory_response(arn),
            {"memoryId": FIXTURE_MEMORY_ID, "view": "full"},
        )
        assert adapter.read(memory) is None


@pytest.mark.parametrize(
    ("described_arn", "status", "memory_id"),
    [
        (
            f"arn:aws:bedrock-agentcore:{SOURCE_REGION}:{DESTINATION}:memory/{OTHER_MEMORY_ID}",
            "ACTIVE",
            FIXTURE_MEMORY_ID,
        ),
        (None, "CREATING", None),
        (None, "ACTIVE", OTHER_MEMORY_ID),
    ],
)
def test_memory_empty_policy_fails_closed_without_exact_active_identity(
    described_arn: str | None, status: str, memory_id: str | None
) -> None:
    arn = f"arn:aws:bedrock-agentcore:{SOURCE_REGION}:{DESTINATION}:memory/{FIXTURE_MEMORY_ID}"
    memory = ref("memory", "agentcore_policy", arn=arn, role="memory")
    with aws_adapter({"bedrock-agentcore-control"}) as (adapter, stubs):
        core = stubs["bedrock-agentcore-control"]
        core.add_response("get_resource_policy", {}, {"resourceArn": arn})
        core.add_response(
            "get_memory",
            memory_response(described_arn or arn, status=status, memory_id=memory_id),
            {"memoryId": FIXTURE_MEMORY_ID, "view": "full"},
        )
        with pytest.raises(FreezePlanError, match="exact ACTIVE target"):
            adapter.read(memory)


def test_memory_empty_policy_get_memory_404_is_fatal() -> None:
    arn = f"arn:aws:bedrock-agentcore:{SOURCE_REGION}:{DESTINATION}:memory/{FIXTURE_MEMORY_ID}"
    memory = ref("memory", "agentcore_policy", arn=arn, role="memory")
    with aws_adapter({"bedrock-agentcore-control"}) as (adapter, stubs):
        core = stubs["bedrock-agentcore-control"]
        core.add_response("get_resource_policy", {}, {"resourceArn": arn})
        core.add_client_error(
            "get_memory",
            "ResourceNotFoundException",
            http_status_code=404,
            expected_params={"memoryId": FIXTURE_MEMORY_ID, "view": "full"},
        )
        with pytest.raises(FreezePlanError, match="target missing"):
            adapter.read(memory)


def test_agentcore_404_is_not_assumed_to_mean_no_policy() -> None:
    arn = f"arn:aws:bedrock-agentcore:{SOURCE_REGION}:{DESTINATION}:runtime/missing"
    runtime = ref("runtime", "agentcore_policy", arn=arn, role="runtime")
    with aws_adapter({"bedrock-agentcore-control"}) as (adapter, stubs):
        stubs["bedrock-agentcore-control"].add_client_error(
            "get_resource_policy",
            "ResourceNotFoundException",
            http_status_code=404,
            expected_params={"resourceArn": arn},
        )
        with pytest.raises(FreezePlanError, match="target missing"):
            adapter.read(runtime)
