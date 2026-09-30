"""Read-only AWS CLI transport for environments where boto3 cannot reach AWS."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

ERROR_CODE = re.compile(r"\(([A-Za-z][A-Za-z0-9]{0,79})\)")
READ_OPERATIONS = {
    "sts": {"get_caller_identity"},
    "cloudformation": {"describe_stacks", "list_stack_resources"},
    "dynamodb": {
        "describe_table",
        "describe_time_to_live",
        "get_resource_policy",
    },
    "s3": {
        "head_bucket",
        "get_bucket_location",
        "get_bucket_versioning",
        "get_bucket_encryption",
        "get_public_access_block",
        "get_bucket_lifecycle_configuration",
        "get_bucket_replication",
        "get_bucket_policy",
        "list_object_versions",
    },
    "sqs": {"get_queue_attributes"},
    "sns": {"get_subscription_attributes", "list_subscriptions_by_topic"},
    "iam": {"get_role"},
    "lambda": {
        "get_function_configuration",
        "get_function_concurrency",
        "list_event_source_mappings",
    },
    "events": {"describe_rule", "list_targets_by_rule"},
    "scheduler": {"list_schedules"},
    "ses": {"describe_active_receipt_rule_set"},
    "logs": {"describe_subscription_filters"},
    "s3control": {"list_jobs"},
    "bedrock-agentcore-control": {
        "list_agent_runtimes",
        "get_agent_runtime",
        "list_agent_runtime_endpoints",
        "get_resource_policy",
        "list_memories",
        "get_memory",
    },
    "bedrock-agentcore": {"list_memory_extraction_jobs"},
}


class CliError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class CliPaginator:
    def __init__(self, client: CliClient, operation: str):
        self.client = client
        self.operation = operation

    def paginate(self, **params: Any) -> list[dict[str, Any]]:
        # AWS CLI auto-paginates the list operations used by this preflight.
        return [self.client.invoke(self.operation, params)]


class CliClient:
    def __init__(self, service: str, profile: str | None, region: str):
        self.boto_service = service
        self.service = "s3api" if service == "s3" else service
        self.profile = profile
        self.region = region

    def can_paginate(self, operation: str) -> bool:
        return operation in READ_OPERATIONS.get(self.boto_service, set())

    def get_paginator(self, operation: str) -> CliPaginator:
        if not self.can_paginate(operation):
            raise CliError("OperationNotReadOnly")
        return CliPaginator(self, operation)

    def invoke(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if operation not in READ_OPERATIONS.get(self.boto_service, set()):
            raise CliError("OperationNotReadOnly")
        cmd = ["aws", "--region", self.region]
        if self.profile:
            cmd.extend(["--profile", self.profile])
        cmd.extend(
            [
                self.service,
                operation.replace("_", "-"),
                "--cli-input-json",
                json.dumps(params, separators=(",", ":")),
                "--output",
                "json",
                "--no-cli-pager",
            ]
        )
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=45, check=False
            )
        except FileNotFoundError as error:
            raise CliError("AwsCliUnavailable") from error
        except subprocess.TimeoutExpired as error:
            raise CliError("AwsCliTimeout") from error
        if result.returncode:
            match = ERROR_CODE.search(result.stderr)
            raise CliError(match.group(1) if match else "AwsCliError")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise CliError("InvalidAwsCliOutput") from error
        if not isinstance(data, dict):
            raise CliError("InvalidAwsCliOutput")
        return data

    def __getattr__(self, operation: str) -> Any:
        return lambda **params: self.invoke(operation, params)


class CliSession:
    def __init__(self, profile: str | None, region: str):
        self.profile = profile
        self.region_name = region

    def client(self, service: str, **_kwargs: Any) -> CliClient:
        return CliClient(service, self.profile, self.region_name)


class GuardedClient:
    def __init__(self, service: str, target: Any):
        self.service = service
        self.target = target

    def can_paginate(self, operation: str) -> bool:
        return operation in READ_OPERATIONS.get(
            self.service, set()
        ) and self.target.can_paginate(operation)

    def get_paginator(self, operation: str) -> Any:
        if operation not in READ_OPERATIONS.get(self.service, set()):
            raise CliError("OperationNotReadOnly")
        return self.target.get_paginator(operation)

    def __getattr__(self, operation: str) -> Any:
        if operation not in READ_OPERATIONS.get(self.service, set()):
            raise CliError("OperationNotReadOnly")
        return getattr(self.target, operation)


class GuardedSession:
    def __init__(self, session: Any):
        self.session = session
        self.region_name = session.region_name

    def client(self, service: str, **kwargs: Any) -> GuardedClient:
        return GuardedClient(service, self.session.client(service, **kwargs))
