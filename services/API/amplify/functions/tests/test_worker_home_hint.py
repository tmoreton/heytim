from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import patch

from worker_test_case import WorkerTestCase


class WorkerHomeHintTests(WorkerTestCase):
    def test_direct_home_hint_is_json_safe_and_remains_advisory(self) -> None:
        bot = {
            "name": "Home Bot", "prompt": "Help.", "skillVersions": {},
            "toolIds": [], "skillIds": [],
        }
        hint = {
            "selectedLabel": "turn_on", "confidence": Decimal("0.96"),
            "actionProbability": Decimal("0.98"), "truncated": False,
        }
        with (
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[]),
            patch.object(self.agent.catalog, "available_tool_ids", return_value=[]),
            patch.object(self.agent.catalog, "resolve_tools_for_runtime", return_value=[]),
            patch.object(self.agent, "_team_roster", return_value=[]),
            patch.object(self.agent, "read_agent_stream", return_value="Done"),
        ):
            self.agent._invoke(
                "user-1", "home", bot, history=[], event_id="turn-1",
                home_assistant_hint=hint,
            )
        payload = json.loads(
            self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"]
        )
        self.assertEqual(payload["homeAssistantHint"]["selectedLabel"], "turn_on")
        self.assertEqual(payload["homeAssistantHint"]["confidence"], 0.96)
        self.assertEqual(payload["homeAssistantHint"]["actionProbability"], 0.98)
