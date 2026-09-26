"""Keep the API's reviewed MCP grants aligned with runtime enforcement."""

from __future__ import annotations

import ast
import importlib.util
import unittest
from pathlib import Path

from shared.client_contract import MAX_TOOLS_PER_BOT
from shared.provider_contract import (
    GMAIL_MCP_ENDPOINT,
    GMAIL_MCP_TOOLS,
    GOOGLE_WORKSPACE_MCP_SERVERS,
)


class ConnectionPolicySyncTests(unittest.TestCase):
    def test_tool_limit_matches_runtime_validator(self) -> None:
        path = (
            Path(__file__).resolve().parents[4]
            / "runtime/runtime/heytim_runtime/capability_contract.py"
        )
        module = ast.parse(path.read_text())
        limits = [
            assignment.value.value
            for assignment in module.body
            if isinstance(assignment, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "MAX_TOOLS" for target in assignment.targets)
            and isinstance(assignment.value, ast.Constant)
        ]
        self.assertEqual(limits, [MAX_TOOLS_PER_BOT])

    def test_reviewed_google_mcp_tools_match_runtime(self) -> None:
        path = (
            Path(__file__).resolve().parents[4]
            / "runtime/runtime/heytim_runtime/provider_contract.py"
        )
        spec = importlib.util.spec_from_file_location("runtime_mcp_tool_catalog", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(GMAIL_MCP_ENDPOINT, module.GMAIL_MCP_ENDPOINT)
        self.assertEqual(set(GMAIL_MCP_TOOLS), module.GMAIL_MCP_TOOLS)
        self.assertEqual(
            {
                endpoint: set(allowed_tools)
                for endpoint, allowed_tools in GOOGLE_WORKSPACE_MCP_SERVERS.items()
            },
            module.GOOGLE_WORKSPACE_MCP_SERVERS,
        )
