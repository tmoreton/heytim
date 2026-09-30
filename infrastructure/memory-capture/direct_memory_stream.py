"""Guarded single-attempt direct attach/rollback of the legacy source Memory stream.

Preparing and inspecting are read-only AWS operations. Attach and rollback each make
one explicit UpdateMemory call and must be run only after an operator decision.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
from botocore.config import Config
from source_memory_attachment import (
    load_config,
    memory_contract,
    read_live,
    require,
    sha256,
)

POLL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 180
DRIFT_WARNING = (
    "Direct Memory attachment leaves the CloudFormation source template unchanged. "
    "Freeze AgentCore-HeyTim-production updates and recheck GetMemory until capture ends."
)


def api_stream(config: dict[str, Any]) -> dict[str, Any]:
    """The one permitted AgentCore API stream payload, derived from pinned JSON."""
    return {"resources": [{"kinesis": {
        "dataStreamArn": config["streamArn"],
        "contentConfigurations": [{"type": "MEMORY_RECORDS", "level": "FULL_CONTENT"}],
    }}]}


def update_arguments(config: dict[str, Any], token: str, *, rollback: bool) -> dict[str, Any]:
    require(isinstance(token, str) and len(token) == 36, "Invalid stable client token")
    return {"memoryId": config["memoryId"], "clientToken": token,
            "streamDeliveryResources": {"resources": []} if rollback else api_stream(config)}


def dependent_hashes(session: boto3.Session, config: dict[str, Any]) -> dict[str, str]:
    """Hash only the four exact dependent fields that CFN wanted to reevaluate."""
    deps = config["dependentResources"]
    control = session.client("bedrock-agentcore-control")
    runtime = control.get_agent_runtime(agentRuntimeId=deps["runtimeId"])
    require(runtime.get("agentRuntimeId") == deps["runtimeId"] and runtime.get("status") == "READY",
            "Source runtime identity or readiness changed")
    evaluation = control.get_online_evaluation_config(onlineEvaluationConfigId=deps["evaluationId"])
    require(evaluation.get("onlineEvaluationConfigId") == deps["evaluationId"] and
            evaluation.get("onlineEvaluationConfigArn") == deps["evaluationArn"] and
            evaluation.get("executionStatus") == "ENABLED", "Source online evaluation identity or status changed")
    iam = session.client("iam")
    runtime_policy = iam.get_role_policy(RoleName=deps["runtimeRoleName"],
                                         PolicyName=deps["runtimePolicyName"])
    evaluation_policy = iam.get_role_policy(RoleName=deps["evaluationRoleName"],
                                            PolicyName=deps["evaluationPolicyName"])
    require(runtime_policy.get("PolicyName") == deps["runtimePolicyName"] and
            evaluation_policy.get("PolicyName") == deps["evaluationPolicyName"], "Dependent policy identity changed")
    return {
        "runtimeEnvironment": sha256(runtime.get("environmentVariables")),
        "runtimePolicy": sha256(runtime_policy.get("PolicyDocument")),
        "evaluationDataSource": sha256(evaluation.get("dataSourceConfig")),
        "evaluationPolicy": sha256(evaluation_policy.get("PolicyDocument")),
    }


def fresh_plan(config: dict[str, Any], hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "version": 1,
        "state": "PREPARED",
        "sourceAccount": config["sourceAccount"],
        "sourceStackId": config["sourceStackId"],
        "memoryArn": config["memoryArn"],
        "configSha256": sha256(config),
        "memoryContractSha256": config["expectedMemoryContractSha256"],
        "dependentHashes": hashes,
        "attachToken": str(uuid4()),
        "rollbackToken": str(uuid4()),
        "preparedAt": datetime.now(timezone.utc).isoformat(),
        "cloudFormationDriftWarning": DRIFT_WARNING,
    }


def write_plan(path: Path, plan: dict[str, Any], *, replace: bool = False) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(path.parent.stat().st_mode & 0o777 == 0o700, "Journal directory must be mode 0700")
    if not replace:
        require(not path.exists(), "Journal already exists")
    fd, temporary = tempfile.mkstemp(prefix=".memory-stream-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(plan, file, sort_keys=True, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        if replace:
            require(path.is_file() and path.stat().st_mode & 0o777 == 0o600,
                    "Existing journal permissions changed")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_plan(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    require(path.is_file() and path.stat().st_mode & 0o777 == 0o600 and
            path.parent.stat().st_mode & 0o777 == 0o700, "Journal permissions are not private")
    plan = json.loads(path.read_text())
    require(plan.get("version") == 1 and plan.get("sourceAccount") == config["sourceAccount"] and
            plan.get("sourceStackId") == config["sourceStackId"] and plan.get("memoryArn") == config["memoryArn"] and
            plan.get("configSha256") == sha256(config) and
            plan.get("memoryContractSha256") == config["expectedMemoryContractSha256"] and
            plan.get("cloudFormationDriftWarning") == DRIFT_WARNING, "Journal does not match pinned source")
    require(plan.get("attachToken") != plan.get("rollbackToken"), "Attach and rollback tokens must differ")
    update_arguments(config, plan["attachToken"], rollback=False)
    update_arguments(config, plan["rollbackToken"], rollback=True)
    require(set(plan.get("dependentHashes", {})) == {
        "runtimeEnvironment", "runtimePolicy", "evaluationDataSource", "evaluationPolicy"},
        "Journal dependent baseline incomplete")
    return plan


@contextmanager
def exclusive_journal(path: Path):
    """Stop two operators from submitting the same journal concurrently."""
    lock_path = path.with_name(path.name + ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        require(os.fstat(fd).st_mode & 0o777 == 0o600, "Journal lock permissions changed")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as exc:
            raise ValueError("Journal is already being used by another operator") from exc
        yield
    finally:
        if locked:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def verify_dependents(session: boto3.Session, config: dict[str, Any], plan: dict[str, Any]) -> None:
    require(dependent_hashes(session, config) == plan["dependentHashes"],
            "Runtime or evaluation dependent configuration changed")


def poll_memory(control: Any, config: dict[str, Any], expected_stream: dict[str, Any] | None,
                previous_stream: dict[str, Any] | None,
                *, timeout_seconds: int = POLL_TIMEOUT_SECONDS, sleep: Any = time.sleep,
                monotonic: Any = time.monotonic) -> None:
    deadline = monotonic() + timeout_seconds
    while True:
        memory = control.get_memory(memoryId=config["memoryId"], view="full")["memory"]
        require(memory.get("id") == config["memoryId"] and memory.get("arn") == config["memoryArn"],
                "Memory physical identity changed during update")
        require(sha256(memory_contract(memory)) == config["expectedMemoryContractSha256"],
                "Memory configuration changed during update")
        status = memory.get("status")
        stream = memory.get("streamDeliveryResources")
        require(stream in (previous_stream, expected_stream), "Memory stream changed unexpectedly during update")
        if status == "ACTIVE" and stream == expected_stream:
            return
        require(status in ("ACTIVE", "UPDATING"), f"Memory entered unexpected status {status}")
        require(monotonic() < deadline, "Memory update did not settle within bounded wait")
        sleep(min(POLL_SECONDS, max(0, deadline - monotonic())))


def single_update(session: boto3.Session, config: dict[str, Any], plan: dict[str, Any],
                  path: Path, *, rollback: bool) -> None:
    expected_before = api_stream(config) if rollback else None
    expected_after = None if rollback else api_stream(config)
    read_live(session, config, expected_before)
    verify_dependents(session, config, plan)
    require(plan["state"] in (("ATTACHED", "ATTACH_REQUESTED") if rollback else ("PREPARED",)),
            "Journal state prevents this request; inspect it before any retry")
    plan["state"] = "ROLLBACK_REQUESTED" if rollback else "ATTACH_REQUESTED"
    plan["requestStartedAt"] = datetime.now(timezone.utc).isoformat()
    write_plan(path, plan, replace=True)
    # Disable botocore's automatic write retries. The persisted token is for a
    # separately reviewed manual retry if transport outcome is uncertain.
    writer = session.client("bedrock-agentcore-control", config=Config(
        retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=20))
    writer.update_memory(**update_arguments(config, plan["rollbackToken" if rollback else "attachToken"],
                                            rollback=rollback))
    # The read client can retry safe reads; never resubmit the mutation here.
    poll_memory(session.client("bedrock-agentcore-control"), config, expected_after, expected_before)
    read_live(session, config, expected_after)
    verify_dependents(session, config, plan)
    plan["state"] = "ROLLED_BACK" if rollback else "ATTACHED"
    plan["confirmedAt"] = datetime.now(timezone.utc).isoformat()
    write_plan(path, plan, replace=True)


def inspect(session: boto3.Session, config: dict[str, Any], plan: dict[str, Any]) -> str:
    require(session.client("sts").get_caller_identity()["Account"] == config["sourceAccount"],
            "AWS identity is not the source account")
    memory = session.client("bedrock-agentcore-control").get_memory(memoryId=config["memoryId"], view="full")["memory"]
    require(memory.get("id") == config["memoryId"] and memory.get("arn") == config["memoryArn"] and
            sha256(memory_contract(memory)) == config["expectedMemoryContractSha256"],
            "Source Memory identity or configuration changed")
    stream = memory.get("streamDeliveryResources")
    require(stream in (None, api_stream(config)), "Unexpected source Memory stream configuration")
    if memory.get("status") == "ACTIVE":
        read_live(session, config, stream)
        verify_dependents(session, config, plan)
    return f"journal={plan['state']} memory={memory.get('status')} stream={'attached' if stream else 'absent'}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Exact source AWS profile")
    sub = parser.add_subparsers(dest="action", required=True)
    prepare = sub.add_parser("prepare", help="Read-only AWS checks, then create a private local journal")
    prepare.add_argument("--output-dir", required=True, type=Path,
                         help="Existing private durable directory outside the Git checkout")
    for action in ("inspect", "attach", "rollback"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--plan", required=True, type=Path)
        if action == "attach":
            cmd.add_argument("--acknowledge-cloudformation-drift", action="store_true")
        if action == "rollback":
            cmd.add_argument("--acknowledge-capture-gap", action="store_true")
    args = parser.parse_args()
    try:
        config = load_config()
        session = boto3.Session(profile_name=args.profile, region_name=config["region"])
        if args.action == "prepare":
            read_live(session, config)
            hashes = dependent_hashes(session, config)
            output_dir = args.output_dir.resolve()
            repository = Path(__file__).resolve().parents[2]
            require(output_dir.is_dir() and output_dir.stat().st_mode & 0o777 == 0o700 and
                    not output_dir.is_relative_to(repository),
                    "Journal parent must be an existing private directory outside the repository")
            directory = Path(tempfile.mkdtemp(prefix="heytim-memory-direct-", dir=output_dir))
            plan_path = directory / "journal.json"
            write_plan(plan_path, fresh_plan(config, hashes))
            print(f"Private journal: {plan_path}")
            print(DRIFT_WARNING)
            print("No AWS resource was changed.")
            return 0
        path = args.plan
        if args.action == "inspect":
            plan = load_plan(path, config)
            print(inspect(session, config, plan))
            print(DRIFT_WARNING)
            return 0
        if args.action == "attach":
            require(args.acknowledge_cloudformation_drift, "Explicit drift acknowledgement is required")
        if args.action == "rollback":
            require(args.acknowledge_capture_gap, "Explicit capture-gap acknowledgement is required")
        with exclusive_journal(path):
            plan = load_plan(path, config)
            single_update(session, config, plan, path, rollback=args.action == "rollback")
            print(f"Confirmed {plan['state']} for exact source Memory; {DRIFT_WARNING}")
        return 0
    except (ValueError, KeyError, IndexError) as exc:
        print(f"NO-GO: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - any post-request failure must remain an uncertain write
        # A transport failure after a write attempt is ambiguous. The journal
        # remains REQUESTED; never automatically retry the UpdateMemory call.
        print(f"UNCERTAIN: {type(exc).__name__}; inspect the private journal and live Memory. "
              "Do not submit another update automatically.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
