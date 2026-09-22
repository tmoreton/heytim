from __future__ import annotations

import os
import re
import sys
from typing import Any

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient


def _assert_success(result: dict[str, Any], label: str) -> None:
    if result.get("status") != "success" or result.get("isError") is True:
        detail = str(result.get("content", []))[:800]
        detail = re.sub(r"(?i)(bearer\s+)[^\s'\"]+", r"\1[redacted]", detail)
        detail = re.sub(r"(?i)([?&]key=)[^&\s'\"]+", r"\1[redacted]", detail)
        raise RuntimeError(
            f"{label} gateway smoke request failed "
            f"(status={result.get('status')}, detail={detail})"
        )


def main() -> int:
    endpoint = os.environ.get("HEYTIM_AGENT_GATEWAY_URL", "")
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", ""))
    if not endpoint or not region:
        raise RuntimeError("HEYTIM_AGENT_GATEWAY_URL and AWS_REGION are required")

    client = MCPClient(
        lambda: aws_iam_streamablehttp_client(
            endpoint=endpoint,
            aws_region=region,
            aws_service="bedrock-agentcore",
        ),
        prefix=None,
        continue_on_error=False,
        startup_timeout=30,
        application_name="HeyTimReleaseSmoke",
    )
    with client:
        tools = client.list_tools_sync(prefix="")
        names = {tool.tool_name for tool in tools}
        required_suffixes = {
            "x_search_recent",
            "youtube_search",
            "youtube_video_details",
            "youtube_comments",
        }
        resolved = {
            suffix: next((name for name in names if name.endswith(f"___{suffix}")), "")
            for suffix in required_suffixes
        }
        missing = sorted(suffix for suffix, name in resolved.items() if not name)
        if missing:
            raise RuntimeError(
                f"Gateway is missing expected tools: {', '.join(missing)}"
            )

        failures: list[str] = []
        x_result = client.call_tool_sync(
            "release-smoke-x",
            resolved["x_search_recent"],
            {"query": "from:XDevelopers -is:retweet", "max_results": 10},
        )
        try:
            _assert_success(x_result, "X")
        except RuntimeError as error:
            failures.append(str(error))
        youtube_result = client.call_tool_sync(
            "release-smoke-youtube",
            resolved["youtube_video_details"],
            {"part": "snippet,contentDetails,statistics", "id": "dQw4w9WgXcQ"},
        )
        try:
            _assert_success(youtube_result, "YouTube")
        except RuntimeError as error:
            failures.append(str(error))
        if failures:
            raise RuntimeError("; ".join(failures))

    print("X and YouTube gateway smoke requests succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
