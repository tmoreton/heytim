from __future__ import annotations

import os
import re

from strands.tools.mcp.mcp_client import MCPClient

GATEWAY_URL = os.environ.get("FROGBOT_GATEWAY_URL") or os.environ.get(
    "AGENTCORE_GATEWAY_FROGBOTTOOLS_URL", ""
)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def gateway_operations(bindings: list[dict]) -> list[str]:
    return list(
        dict.fromkeys(
            operation
            for item in bindings
            if item["kind"] == "gateway"
            for operation in item["operations"]
        )
    )


def gateway_client(operations: list[str]) -> MCPClient | None:
    if not operations:
        return None
    if not GATEWAY_URL:
        raise ValueError("One or more selected tools are not configured")

    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

    allowed = [re.compile(rf".*___{re.escape(operation)}$") for operation in operations]
    return MCPClient(
        lambda: aws_iam_streamablehttp_client(
            endpoint=GATEWAY_URL,
            aws_region=AWS_REGION,
            aws_service="bedrock-agentcore",
        ),
        tool_filters={"allowed": allowed},
        continue_on_error=False,
        startup_timeout=15,
        application_name="FroggyBot",
    )
