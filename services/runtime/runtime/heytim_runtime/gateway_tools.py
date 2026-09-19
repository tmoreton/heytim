from __future__ import annotations

import os
import re
from typing import Any, Protocol

from strands.tools.mcp.mcp_client import MCPClient

GATEWAY_URL = os.environ.get("HEYTIM_GATEWAY_URL") or os.environ.get(
    "AGENTCORE_GATEWAY_HEYTIMTOOLS_URL", ""
)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


class ToolUsageRecorder(Protocol):
    def observe_tool(self, provider: str, operation: str) -> None: ...


class MeteredMCPClient(MCPClient):
    """Count gateway dispatches without recording tool arguments or results."""

    def __init__(
        self, *args: Any, usage: ToolUsageRecorder | None = None, **kwargs: Any
    ) -> None:
        self._heytim_usage = usage
        super().__init__(*args, **kwargs)

    def _observe(self, name: str) -> None:
        if self._heytim_usage is not None:
            self._heytim_usage.observe_tool(
                "agentcore-gateway", name.rsplit("___", 1)[-1]
            )

    def call_tool_sync(
        self,
        tool_use_id: str,
        name: str,
        arguments: dict[str, Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self._observe(name)
        return super().call_tool_sync(
            tool_use_id, name, arguments, *args, **kwargs
        )

    async def call_tool_async(
        self,
        tool_use_id: str,
        name: str,
        arguments: dict[str, Any] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self._observe(name)
        return await super().call_tool_async(
            tool_use_id, name, arguments, *args, **kwargs
        )


def gateway_operations(bindings: list[dict]) -> list[str]:
    return list(
        dict.fromkeys(
            operation
            for item in bindings
            if item["kind"] == "gateway"
            for operation in item["operations"]
        )
    )


def gateway_client(
    operations: list[str], usage: ToolUsageRecorder | None = None
) -> MCPClient | None:
    if not operations:
        return None
    if not GATEWAY_URL:
        raise ValueError("One or more selected tools are not configured")

    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

    allowed = [re.compile(rf".*___{re.escape(operation)}$") for operation in operations]
    return MeteredMCPClient(
        lambda: aws_iam_streamablehttp_client(
            endpoint=GATEWAY_URL,
            aws_region=AWS_REGION,
            aws_service="bedrock-agentcore",
        ),
        tool_filters={"allowed": allowed},
        continue_on_error=False,
        startup_timeout=15,
        application_name="HeyTim",
        usage=usage,
    )
