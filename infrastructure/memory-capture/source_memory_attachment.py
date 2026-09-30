"""Read-only plan and change-set guard for the legacy source Memory stream.

This deliberately cannot create or execute a CloudFormation change set.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import boto3

CONFIG_PATH = Path(__file__).with_name("source-memory-attachment.json")
MEMORY_TYPE = "AWS::BedrockAgentCore::Memory"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text())
    require(config["sourceAccount"] == "188757775631" and config["region"] == "us-east-1",
            "Unexpected source account or Region")
    require(config["sourceStackName"] == "AgentCore-HeyTim-production", "Unexpected legacy stack name")
    require(config["sourceStackId"].startswith(
        "arn:aws:cloudformation:us-east-1:188757775631:stack/AgentCore-HeyTim-production/"),
        "Unexpected legacy stack ARN")
    require(config["memoryLogicalId"] == "ApplicationMemoryHeyTimMemory78AB17BC",
            "Unexpected Memory logical ID")
    require(config["memoryArn"] ==
            f'arn:aws:bedrock-agentcore:us-east-1:188757775631:memory/{config["memoryId"]}',
            "Unexpected Memory ARN")
    require(config["streamArn"] ==
            "arn:aws:kinesis:us-east-1:188757775631:stream/heytim-memory-record-capture",
            "Unexpected stream ARN")
    require(config.get("dependentResources") == {
        "runtimeId": "HeyTimProduction_HeyTim-so5Mx1Cy33",
        "runtimeRoleName": "AgentCore-HeyTim-producti-ApplicationAgentHeyTimRun-chD7B6tbgMyp",
        "runtimePolicyName": "ApplicationAgentHeyTimRuntimeExecutionRoleDefaultPolicyE72CDDE0",
        "evaluationId": "HeyTimProduction_HeyTimContinuousQuality-j5dDtj9jfi",
        "evaluationArn": "arn:aws:bedrock-agentcore:us-east-1:188757775631:online-evaluation-config/HeyTimProduction_HeyTimContinuousQuality-j5dDtj9jfi",
        "evaluationRoleName": "AgentCore-HeyTim-producti-ApplicationOnlineEvalHeyT-kRGTAThIq7eL",
        "evaluationPolicyName": "ApplicationOnlineEvalHeyTimContinuousQualityExecutionRoleDefaultPolicy87DD51FE",
    }, "Dependent source resource identities changed")
    require(config["streamDeliveryResources"] == {
        "Resources": [{"Kinesis": {"DataStreamArn": config["streamArn"],
                                  "ContentConfigurations": [{"Type": "MEMORY_RECORDS", "Level": "FULL_CONTENT"}]}}]},
            "Source-only stream specification changed")
    for field in ("expectedTemplateSha256", "expectedMemoryContractSha256"):
        require(len(config[field]) == 64 and all(c in "0123456789abcdef" for c in config[field]),
                f"Missing reviewed {field}")
    return config


def memory_contract(memory: dict[str, Any]) -> dict[str, Any]:
    """Stable full configuration, excluding service timestamps and status."""
    fields = ("id", "arn", "name", "description", "eventExpiryDuration", "memoryExecutionRoleArn",
              "encryptionKeyArn", "managedByResourceArn", "indexedKeys", "namespaceKeys")
    strategies = []
    for strategy in memory.get("strategies", []):
        strategies.append({key: value for key, value in strategy.items()
                           if key not in ("createdAt", "updatedAt", "status")})
    return {**{field: memory.get(field) for field in fields},
            "strategies": sorted(strategies, key=lambda item: item["strategyId"])}


def template_body(response: dict[str, Any]) -> dict[str, Any]:
    body = response["TemplateBody"]
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Source template must be JSON; do not reinterpret YAML intrinsics") from exc
    require(isinstance(body, dict), "Source template is not a JSON object")
    return body


def build_candidate(template: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    require(sha256(template) == config["expectedTemplateSha256"], "Legacy source template drifted")
    resource = template.get("Resources", {}).get(config["memoryLogicalId"])
    require(isinstance(resource, dict) and resource.get("Type") == MEMORY_TYPE,
            "Live template does not own the expected Memory")
    properties = resource.get("Properties", {})
    require(properties.get("Name") == config["memoryName"], "Memory physical name changed in template")
    require(properties.get("EventExpiryDuration") == config["memoryEventExpiryDays"],
            "Memory expiry changed in template")
    require("StreamDeliveryResources" not in properties,
            "Live source template already has stream configuration")
    candidate = copy.deepcopy(template)
    candidate["Resources"][config["memoryLogicalId"]]["Properties"]["StreamDeliveryResources"] = copy.deepcopy(
        config["streamDeliveryResources"])
    reversed_candidate = copy.deepcopy(candidate)
    del reversed_candidate["Resources"][config["memoryLogicalId"]]["Properties"]["StreamDeliveryResources"]
    require(reversed_candidate == template, "Candidate modifies properties other than stream delivery")
    require(len(canonical(candidate)) < 51200, "Candidate exceeds CloudFormation inline template limit")
    return candidate


def validate_change_set(change_set: dict[str, Any], config: dict[str, Any], stack: dict[str, Any]) -> None:
    require(change_set.get("StackId") == config["sourceStackId"], "Change set targets another stack")
    require(change_set.get("ChangeSetType") == "UPDATE" and
            change_set.get("Status") == "CREATE_COMPLETE" and
            change_set.get("ExecutionStatus") == "AVAILABLE", "Change set is not an available update")
    require("NextToken" not in change_set, "Change set changes were truncated")
    require(change_set.get("RoleARN") == stack.get("RoleARN"), "Change set uses a different execution role")
    require(change_set.get("NotificationARNs", []) == stack.get("NotificationARNs", []),
            "Change set alters stack notifications")
    require(set(change_set.get("Capabilities", [])) == set(stack.get("Capabilities", [])),
            "Change set capabilities differ from source stack")
    def parameters(value: dict[str, Any]) -> dict[str, str | None]:
        return {entry["ParameterKey"]: entry.get("ParameterValue")
                for entry in value.get("Parameters", [])}
    require(parameters(change_set) == parameters(stack), "Change set alters stack parameters")
    changes = change_set.get("Changes", [])
    require(len(changes) == 1 and changes[0].get("Type") == "Resource", "Expected exactly one resource change")
    resource = changes[0]["ResourceChange"]
    require(resource.get("Action") == "Modify" and resource.get("LogicalResourceId") == config["memoryLogicalId"]
            and resource.get("PhysicalResourceId") == config["memoryArn"] and
            resource.get("ResourceType") == MEMORY_TYPE, "Change set touches a different resource")
    require(resource.get("Replacement") == "False" and resource.get("Scope") == ["Properties"],
            "Memory update may replace or alter more than properties")
    details = resource.get("Details", [])
    require(len(details) == 1 and details[0].get("Evaluation") == "Static" and
            details[0].get("ChangeSource") == "DirectModification",
            "Change set has dynamic or indirect changes")
    target = details[0].get("Target", {})
    require(target.get("Attribute") == "Properties" and target.get("Name") == "StreamDeliveryResources" and
            target.get("RequiresRecreation") == "Never" and
            target.get("Path") in (None, "/Properties/StreamDeliveryResources") and
            target.get("AttributeChangeType") in (None, "Add"),
            "Change set does not isolate an in-place StreamDeliveryResources addition")


def read_live(session: boto3.Session, config: dict[str, Any],
              expected_stream: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    require(session.client("sts").get_caller_identity()["Account"] == config["sourceAccount"],
            "AWS identity is not the source account")
    cfn = session.client("cloudformation")
    stacks = cfn.describe_stacks(StackName=config["sourceStackId"])["Stacks"]
    require(len(stacks) == 1, "Legacy source stack lookup is ambiguous")
    stack = stacks[0]
    require(stack["StackId"] == config["sourceStackId"] and stack["StackStatus"] == "UPDATE_COMPLETE",
            "Legacy source stack is not stable")
    resource = cfn.describe_stack_resource(StackName=config["sourceStackId"],
                                            LogicalResourceId=config["memoryLogicalId"])["StackResourceDetail"]
    require(resource["PhysicalResourceId"] == config["memoryArn"] and resource["ResourceType"] == MEMORY_TYPE,
            "Legacy stack Memory physical identity changed")
    template = template_body(cfn.get_template(StackName=config["sourceStackId"], TemplateStage="Original"))
    memory = session.client("bedrock-agentcore-control").get_memory(memoryId=config["memoryId"], view="full")["memory"]
    require(memory.get("id") == config["memoryId"] and memory.get("arn") == config["memoryArn"] and
            memory.get("name") == config["memoryName"] and memory.get("status") == "ACTIVE",
            "Live Memory identity or status changed")
    require(memory.get("streamDeliveryResources") == expected_stream, "Memory stream delivery differs from expected")
    require(memory.get("memoryExecutionRoleArn") == config["memoryRoleArn"] and
            memory.get("encryptionKeyArn") == config["memoryEncryptionKeyArn"] and
            memory.get("eventExpiryDuration") == config["memoryEventExpiryDays"],
            "Live Memory role, key, or expiry changed")
    strategies = memory.get("strategies", [])
    require(sorted(strategy["strategyId"] for strategy in strategies) == sorted(config["memoryStrategyIds"]) and
            all(strategy.get("status") == "ACTIVE" for strategy in strategies),
            "Live Memory strategies changed")
    require(sha256(memory_contract(memory)) == config["expectedMemoryContractSha256"],
            "Live Memory configuration drifted")
    capture_stacks = cfn.describe_stacks(StackName=config["captureStackName"])["Stacks"]
    require(len(capture_stacks) == 1 and capture_stacks[0]["StackStatus"] in ("CREATE_COMPLETE", "UPDATE_COMPLETE") and
            capture_stacks[0]["EnableTerminationProtection"] is True,
            "Capture stack is missing or unprotected")
    outputs = {item["OutputKey"]: item["OutputValue"] for item in capture_stacks[0].get("Outputs", [])}
    require(outputs.get("StreamArn") == config["streamArn"] and
            outputs.get("MemoryRoleArn") == config["memoryRoleArn"] and
            outputs.get("StreamKeyArn") == config["streamKeyArn"], "Capture stack outputs changed")
    stream = session.client("kinesis").describe_stream_summary(StreamARN=config["streamArn"])["StreamDescriptionSummary"]
    require(stream["StreamStatus"] == "ACTIVE" and stream["StreamARN"] == config["streamArn"] and
            stream.get("EncryptionType") == "KMS" and stream.get("KeyId") == config["streamKeyArn"] and
            stream.get("RetentionPeriodHours", 0) >= 168, "Capture stream is not ready")
    iam = session.client("iam")
    role_name = config["memoryRoleArn"].rsplit("/", 1)[-1]
    require(iam.get_role(RoleName=role_name)["Role"]["Arn"] == config["memoryRoleArn"],
            "Memory execution role changed")
    policy_names = iam.list_role_policies(RoleName=role_name)
    require(not policy_names.get("IsTruncated"), "Memory role policy list was truncated")
    stream_actions: set[str] = set()
    kms_actions: set[str] = set()
    for name in policy_names.get("PolicyNames", []):
        policy = iam.get_role_policy(RoleName=role_name, PolicyName=name)["PolicyDocument"]
        for statement in policy.get("Statement", []):
            if statement.get("Effect") != "Allow":
                continue
            resources = statement.get("Resource", [])
            actions = statement.get("Action", [])
            resources = [resources] if isinstance(resources, str) else resources
            actions = [actions] if isinstance(actions, str) else actions
            if config["streamArn"] in resources:
                stream_actions.update(actions)
            if config["streamKeyArn"] in resources:
                kms_actions.update(actions)
    require({"kinesis:PutRecords", "kinesis:DescribeStream"} <= stream_actions and
            "kms:GenerateDataKey" in kms_actions, "Memory role lacks exact stream or KMS write permissions")
    mappings = session.client("lambda").list_event_source_mappings(FunctionName=outputs["ConsumerFunctionArn"],
                                                                      EventSourceArn=config["streamArn"])
    require(len(mappings.get("EventSourceMappings", [])) == 1, "Expected one capture consumer mapping")
    mapping = mappings["EventSourceMappings"][0]
    require(mapping.get("State") == "Enabled" and mapping.get("StartingPosition") == "TRIM_HORIZON" and
            mapping.get("BatchSize") == 1 and mapping.get("MaximumRetryAttempts") == -1 and
            mapping.get("MaximumRecordAgeInSeconds") == -1,
            "Capture consumer is disabled or could discard records")
    return stack, template, memory


def create_private_plan(candidate: dict[str, Any], output_dir: Path) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="heytim-source-memory-attach-", dir=output_dir))
    path = directory / "candidate-template.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(canonical(candidate))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Exact source AWS profile")
    sub = parser.add_subparsers(dest="action", required=True)
    plan = sub.add_parser("plan", help="Read AWS and write a private candidate template locally")
    plan.add_argument("--output-dir", type=Path, default=Path(tempfile.gettempdir()))
    review = sub.add_parser("review", help="Read AWS and fail unless a change set is stream-only")
    review.add_argument("--change-set-name", required=True)
    args = parser.parse_args()
    try:
        config = load_config()
        session = boto3.Session(profile_name=args.profile, region_name=config["region"])
        stack, template, _ = read_live(session, config)
        candidate = build_candidate(template, config)
        if args.action == "plan":
            path = create_private_plan(candidate, args.output_dir)
            print(f"Candidate: {path}")
            print(f"Source template SHA-256: {sha256(template)}")
            print(f"Candidate SHA-256: {sha256(candidate)}")
            print("Only StreamDeliveryResources was added to the legacy source Memory template.")
        else:
            cfn = session.client("cloudformation")
            change_set = cfn.describe_change_set(ChangeSetName=args.change_set_name,
                                                  StackName=config["sourceStackId"])
            validate_change_set(change_set, config, stack)
            change_template = template_body(cfn.get_template(ChangeSetName=args.change_set_name,
                                                              StackName=config["sourceStackId"],
                                                              TemplateStage="Original"))
            require(sha256(change_template) == sha256(candidate),
                    "Change set template differs from reviewed stream-only candidate")
            print(f"Change set {args.change_set_name} is available and stream-only; no replacement.")
            print(f"Candidate SHA-256: {sha256(candidate)}")
        return 0
    except (ValueError, KeyError, IndexError) as exc:
        print(f"NO-GO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
