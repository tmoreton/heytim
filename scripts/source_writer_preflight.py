"""Read-only source-writer preflight runner for the HeyTim account cutover."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import boto3
from _source_writer_bucket_probe import inspect_runtime_bucket
from _source_writer_cli_transport import CliError, CliSession, GuardedSession
from _source_writer_preflight_core import (
    ABSENT,
    FUNCTION_HANDLERS,
    MEMORY_DENY,
    NO_POLICY_CODES,
    SOURCE_ACCOUNT,
    SOURCE_REGION,
    Report,
    _error_code,
    _one,
    discover_stack,
    fingerprint,
    has_freeze_deny,
    inspect_buckets,
    inspect_email_and_logs,
    inspect_queues,
    inspect_tables,
    note_unclassified_resources,
    pages,
    read,
)
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError


def _function_label(logical: str, handler: str) -> str | None:
    for label, expected in FUNCTION_HANDLERS.items():
        if handler == expected:
            return label
    lower = logical.lower()
    if "plaidwebhook" in lower:
        return "plaid_webhook"
    if "presignup" in lower or "invitechecklambda" in lower:
        return "pre_signup"
    if "publicavailability" in lower:
        return "availability_probe"
    if "amplifybranchlinkercustomresource" in lower:
        return "deployment_custom_resource"
    return None


def inspect_functions(
    report: Report,
    resources: list[dict],
    lambdas: Any,
    table_names: dict[str, str],
    bucket_names: dict[str, str],
    queue_arns: dict[str, str],
) -> None:
    seen: set[str] = set()
    mapping_counts: dict[str, int] = {"worker": 0, "email_sender": 0}
    for ref in (r for r in resources if r["ResourceType"] == "AWS::Lambda::Function"):
        name = ref.get("PhysicalResourceId", "")
        config = read(
            report,
            "lambda_configuration",
            lambda name=name: lambdas.get_function_configuration(FunctionName=name),
        )
        if config is None:
            continue
        handler = config.get("Handler", "")
        label = _function_label(ref["LogicalResourceId"], handler)
        if label is None or (label in seen and label != "deployment_custom_resource"):
            report.add(
                "unclassified_lambda",
                state="UNKNOWN",
                id_sha256_12=fingerprint(name),
                logical_id=ref["LogicalResourceId"],
                handler=handler,
            )
            report.block("unclassified_or_duplicate_lambda")
            continue
        seen.add(label)
        if label in {"availability_probe", "deployment_custom_resource"}:
            report.add(
                f"lambda_{label}",
                state="DEPLOYMENT_OR_PROBE_ONLY",
                id_sha256_12=fingerprint(name),
            )
            continue
        concurrency = read(
            report,
            f"lambda_{label}_concurrency",
            lambda name=name: lambdas.get_function_concurrency(FunctionName=name),
        )
        mappings = pages(
            report,
            f"lambda_{label}_mappings",
            lambdas,
            "list_event_source_mappings",
            "EventSourceMappings",
            FunctionName=name,
        )
        if concurrency is None or mappings is None:
            continue
        reserved = concurrency.get("ReservedConcurrentExecutions")
        env = config.get("Environment", {}).get("Variables", {})
        env_matches = {
            "TABLE_NAME": table_names.get("application"),
            "INVITE_TABLE_NAME": table_names.get("invite"),
            "FILES_BUCKET_NAME": bucket_names.get("files"),
        }
        mismatches = sum(
            env[key] != expected
            for key, expected in env_matches.items()
            if key in env and expected is not None
        )
        report.add(
            f"lambda_{label}",
            state=config.get("State", "UNKNOWN"),
            id_sha256_12=fingerprint(name),
            reserved_concurrency=reserved,
            mappings=len(mappings),
            environment_mismatches=mismatches,
        )
        if reserved != 0 or mismatches:
            report.block(f"lambda_{label}_not_frozen_or_mismatched")
        for mapping in mappings:
            source = mapping.get("EventSourceArn", "")
            source_label = next(
                (key for key, arn in queue_arns.items() if arn == source), None
            )
            state = mapping.get("State", "UNKNOWN")
            report.add(
                "queue_mapping",
                function=label,
                source=source_label or "UNKNOWN",
                state=state,
                id_sha256_12=fingerprint(mapping.get("UUID", "")),
            )
            expected_source = {"worker": "jobs", "email_sender": "outbound_mail"}.get(
                label
            )
            if source_label != expected_source or state != "Disabled":
                report.block("queue_mapping_unknown_or_enabled")
            if label in mapping_counts:
                mapping_counts[label] += 1
    for label in (*FUNCTION_HANDLERS, "plaid_webhook", "pre_signup"):
        if label not in seen:
            report.block(f"lambda_{label}_missing")
    for label, count in mapping_counts.items():
        if count != 1:
            report.block(f"lambda_{label}_mapping_count_unexpected")


def inspect_schedules(
    report: Report, resources: list[dict], events: Any, scheduler: Any
) -> None:
    for label, logical in (
        ("catalog_rule", "CatalogRefresh"),
        ("public_availability_rule", "PublicAvailabilitySchedule"),
    ):
        rule = _one(report, resources, "AWS::Events::Rule", label, logical)
        if not rule:
            continue
        name = rule["PhysicalResourceId"]
        result = read(
            report,
            f"{label}_describe",
            lambda name=name: events.describe_rule(Name=name),
        )
        targets = pages(
            report,
            f"{label}_targets",
            events,
            "list_targets_by_rule",
            "Targets",
            Rule=name,
        )
        if result is not None and targets is not None:
            state = result.get("State", "UNKNOWN")
            report.add(
                label,
                state=state,
                targets=len(targets),
                id_sha256_12=fingerprint(name),
            )
            if state != "DISABLED" or not targets:
                report.block(f"{label}_not_disabled_or_targetless")
    group = _one(
        report,
        resources,
        "AWS::Scheduler::ScheduleGroup",
        "task_schedule_group",
        "TaskSchedules",
    )
    if group:
        name = group["PhysicalResourceId"]
        schedules = pages(
            report,
            "task_schedules",
            scheduler,
            "list_schedules",
            "Schedules",
            GroupName=name,
        )
        if schedules is not None:
            active = sum(item.get("State") != "DISABLED" for item in schedules)
            report.add(
                "task_schedules",
                state="OBSERVED",
                count=len(schedules),
                enabled=active,
                group_sha256_12=fingerprint(name),
            )
            if active:
                report.block("task_schedules_enabled")


def inspect_agentcore(
    report: Report,
    session: Any,
    config: Config,
    expected_runtime_arn: str,
    expected_runtime_id: str,
    expected_memory_arn: str,
    expected_memory_id: str,
    bucket_names: dict[str, str],
) -> None:
    control = session.client("bedrock-agentcore-control", config=config)
    data = session.client("bedrock-agentcore", config=config)

    def policy_frozen(label: str, arn: str, actions: set[str]) -> bool | None:
        policy = read(
            report,
            f"{label}_policy",
            lambda: control.get_resource_policy(resourceArn=arn),
            NO_POLICY_CODES,
        )
        if policy is None:
            return None
        return policy is not ABSENT and has_freeze_deny(
            policy.get("policy"), arn, actions
        )

    runtimes = pages(
        report, "agentcore_runtimes", control, "list_agent_runtimes", "agentRuntimes"
    )
    if runtimes is not None:
        matches = [
            r for r in runtimes if r.get("agentRuntimeId") == expected_runtime_id
        ]
        report.add(
            "agentcore_runtime_listing",
            state="OBSERVED",
            count=len(runtimes),
            matching_source=len(matches),
        )
        if len(matches) != 1:
            report.block("agentcore_runtime_listing_mismatch")
            matches = [
                {
                    "agentRuntimeArn": expected_runtime_arn,
                    "agentRuntimeId": expected_runtime_id,
                    "status": "UNLISTED",
                }
            ]
        if len(matches) == 1:
            runtime = matches[0]
            arn, runtime_id = runtime["agentRuntimeArn"], runtime["agentRuntimeId"]
            if (
                arn != expected_runtime_arn
                or f":{SOURCE_REGION}:{SOURCE_ACCOUNT}:" not in arn
            ):
                report.block("agentcore_runtime_account_or_region_mismatch")
            detail = read(
                report,
                "agentcore_runtime_detail",
                lambda: control.get_agent_runtime(agentRuntimeId=runtime_id),
            )
            if detail is not None and (
                detail.get("agentRuntimeArn") != expected_runtime_arn
                or detail.get("agentRuntimeId") != expected_runtime_id
            ):
                report.block("agentcore_runtime_detail_identity_mismatch")
            frozen = policy_frozen(
                "agentcore_runtime", arn, {"bedrock-agentcore:InvokeAgentRuntime*"}
            )
            if detail is not None:
                env = detail.get("environmentVariables", {})
                bucket_match = env.get("HEYTIM_FILES_BUCKET") == bucket_names.get(
                    "files"
                )
                inspect_runtime_bucket(
                    report,
                    session.client("s3", config=config),
                    env.get("HEYTIM_FILES_BUCKET"),
                    bucket_names,
                )
                report.add(
                    "agentcore_runtime",
                    state=runtime.get("status", "UNKNOWN"),
                    id_sha256_12=fingerprint(arn),
                    freeze_deny=frozen,
                    files_bucket_matches=bucket_match,
                )
                if not frozen or not bucket_match:
                    report.block("agentcore_runtime_not_frozen_or_mismatched")
            endpoints = pages(
                report,
                "agentcore_endpoints",
                control,
                "list_agent_runtime_endpoints",
                "runtimeEndpoints",
                agentRuntimeId=runtime_id,
            )
            if endpoints is not None:
                if not endpoints:
                    report.block("agentcore_endpoint_missing")
                for endpoint in endpoints:
                    endpoint_arn = endpoint["agentRuntimeEndpointArn"]
                    frozen = policy_frozen(
                        "agentcore_endpoint",
                        endpoint_arn,
                        {"bedrock-agentcore:InvokeAgentRuntime*"},
                    )
                    report.add(
                        "agentcore_endpoint",
                        state=endpoint.get("status", "UNKNOWN"),
                        id_sha256_12=fingerprint(endpoint_arn),
                        freeze_deny=frozen,
                    )
                    if not frozen:
                        report.block("agentcore_endpoint_not_frozen")

    memories = pages(report, "agentcore_memories", control, "list_memories", "memories")
    if memories is not None:
        matches = [m for m in memories if m.get("id") == expected_memory_id]
        report.add(
            "agentcore_memory_listing",
            state="OBSERVED",
            count=len(memories),
            matching_source=len(matches),
        )
        if len(matches) != 1:
            report.block("agentcore_memory_listing_mismatch")
        if len(matches) == 1:
            detail = read(
                report,
                "agentcore_source_memory_detail",
                lambda: control.get_memory(memoryId=expected_memory_id, view="full"),
            )
            if detail is None:
                report.block("agentcore_active_runtime_sessions_unverified")
                report.block("agentcore_managed_extraction_and_expiry_unpausable")
                report.block("agentcore_ingest_data_policy_coverage_unverified")
                return
            memory = detail.get("memory", {})
            arn, memory_id = memory["arn"], memory["id"]
            if (
                arn != expected_memory_arn
                or memory_id != expected_memory_id
                or f":{SOURCE_REGION}:{SOURCE_ACCOUNT}:" not in arn
            ):
                report.block("agentcore_memory_account_or_region_mismatch")
            frozen = policy_frozen("agentcore_memory", arn, MEMORY_DENY)
            strategies = memory.get("strategies", [])
            jobs = pages(
                report,
                "memory_extraction_jobs",
                data,
                "list_memory_extraction_jobs",
                "jobs",
                memoryId=memory_id,
            )
            job_count = len(jobs) if jobs is not None else None
            active_jobs = (
                sum(
                    job.get("status", "UNKNOWN").upper()
                    not in {"COMPLETED", "FAILED", "CANCELLED", "SUCCEEDED"}
                    for job in jobs
                )
                if jobs is not None
                else None
            )
            report.add(
                "agentcore_memory",
                state=memory.get("status", "UNKNOWN"),
                id_sha256_12=fingerprint(arn),
                freeze_deny=frozen,
                event_expiry_days=memory.get("eventExpiryDuration"),
                strategies=len(strategies),
                extraction_jobs=job_count,
                extraction_jobs_active=active_jobs,
            )
            if not frozen or jobs is None or active_jobs:
                report.block("agentcore_memory_not_settled_or_frozen")
    report.block("agentcore_active_runtime_sessions_unverified")
    report.block("agentcore_managed_extraction_and_expiry_unpausable")
    report.block("agentcore_ingest_data_policy_coverage_unverified")


def inventory(session: Any, stack_name: str) -> Report:
    report = Report()
    config = Config(
        retries={"total_max_attempts": 2, "mode": "standard"},
        connect_timeout=5,
        read_timeout=15,
    )
    identity = read(
        report,
        "identity",
        lambda: session.client("sts", config=config).get_caller_identity(),
    )
    if identity is None:
        return report
    account = identity.get("Account")
    report.add("identity", state="MATCH" if account == SOURCE_ACCOUNT else "MISMATCH")
    if account != SOURCE_ACCOUNT or session.region_name != SOURCE_REGION:
        report.block("source_account_or_region_mismatch")
        return report
    cfn = session.client("cloudformation", config=config)
    resources = discover_stack(report, cfn, stack_name)
    if resources is None:
        return report
    note_unclassified_resources(report, resources)
    dynamodb = session.client("dynamodb", config=config)
    s3 = session.client("s3", config=config)
    sqs = session.client("sqs", config=config)
    lambdas = session.client("lambda", config=config)
    table_names = inspect_tables(report, resources, dynamodb)
    bucket_names = inspect_buckets(report, resources, s3)
    queue_arns = inspect_queues(report, resources, sqs)
    inspect_functions(report, resources, lambdas, table_names, bucket_names, queue_arns)
    inspect_schedules(
        report,
        resources,
        session.client("events", config=config),
        session.client("scheduler", config=config),
    )
    dispatcher = next(
        (
            r
            for r in resources
            if r["ResourceType"] == "AWS::Lambda::Function"
            and r["LogicalResourceId"].startswith("AutofixDispatcher")
        ),
        None,
    )
    dispatcher_env = None
    if dispatcher:
        detail = read(
            report,
            "autofix_dispatcher_config",
            lambda: lambdas.get_function_configuration(
                FunctionName=dispatcher["PhysicalResourceId"]
            ),
        )
        if detail is not None:
            dispatcher_env = detail.get("Environment", {}).get("Variables", {})
    inspect_email_and_logs(
        report,
        resources,
        session.client("ses", config=config),
        session.client("logs", config=config),
        dispatcher_env,
    )
    s3control = session.client("s3control", config=config)
    jobs = read(
        report,
        "s3_batch_jobs",
        lambda: s3control.list_jobs(AccountId=SOURCE_ACCOUNT, MaxResults=100),
    )
    if jobs is not None:
        active = sum(
            job.get("Status") not in {"Complete", "Failed", "Cancelled"}
            for job in jobs.get("Jobs", [])
        )
        report.add(
            "s3_batch_jobs",
            state="OBSERVED",
            active=active,
            truncated=bool(jobs.get("NextToken")),
        )
        if active or jobs.get("NextToken"):
            report.block("s3_batch_jobs_active_or_incomplete_inventory")
    deployed = json.loads(
        (
            Path(__file__).resolve().parents[1] / "agentcore/.cli/deployed-state.json"
        ).read_text()
    )["targets"]["development"]["resources"]
    if len(deployed["runtimes"]) != 1 or len(deployed["memories"]) != 1:
        report.block("source_agentcore_state_ambiguous")
        return report
    runtime_state = next(iter(deployed["runtimes"].values()))
    memory_state = next(iter(deployed["memories"].values()))
    inspect_agentcore(
        report,
        session,
        config,
        runtime_state["runtimeArn"],
        runtime_state["runtimeId"],
        memory_state["memoryArn"],
        memory_state["memoryId"],
        bucket_names,
    )
    report.block("provider_webhook_retry_and_traffic_inventory_external")
    report.block("presigned_upload_forms_cannot_be_enumerated")
    report.block("deployment_pipeline_updates_unfenced")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stack-name", required=True, help="Exact deployed source Amplify stack name"
    )
    parser.add_argument("--profile", help="AWS profile for the source account")
    parser.add_argument(
        "--transport",
        choices=("auto", "boto3", "cli"),
        default="auto",
        help="Read-only AWS transport; auto tries CLI after an SDK connection failure",
    )
    parser.add_argument(
        "--output", type=Path, help="New sanitized JSON evidence file (must not exist)"
    )
    args = parser.parse_args()
    try:
        session = (
            CliSession(args.profile, SOURCE_REGION)
            if args.transport == "cli"
            else GuardedSession(
                boto3.Session(profile_name=args.profile, region_name=SOURCE_REGION)
            )
        )
        report = inventory(session, args.stack_name)
        if (
            args.transport == "auto"
            and report.blockers == ["identity_unreadable"]
            and any(
                check.get("error_code") == "EndpointConnectionError"
                for check in report.checks
            )
        ):
            report = inventory(CliSession(args.profile, SOURCE_REGION), args.stack_name)
    except (
        BotoCoreError,
        ClientError,
        NoCredentialsError,
        CliError,
        OSError,
        KeyError,
        ValueError,
    ) as error:
        report = Report()
        report.add("preflight", state="UNKNOWN", error_code=_error_code(error))
        report.block("preflight_incomplete")
    encoded = json.dumps(report.data(), indent=2, sort_keys=True) + "\n"
    if args.output:
        try:
            descriptor = os.open(
                args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
                destination.write(encoded)
        except OSError:
            print("Could not create the requested evidence file", file=sys.stderr)
            return 1
    else:
        sys.stdout.write(encoded)
    return 2 if report.blockers else 0


if __name__ == "__main__":
    sys.exit(main())
