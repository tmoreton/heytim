from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from worker_test_case import WorkerTestCase


class DeviceWorkerContractTests(WorkerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.tool = {
            "id": "apple_health",
            "name": "Apple Health",
            "risk": "read",
            "runtime": {
                "kind": "device",
                "platform": "ios",
                "operations": ["apple_health_steps"],
                "interactiveOperations": [],
            },
        }
        self.bot = {
            "name": "Health Coach",
            "prompt": "Analyze activity.",
            "skillVersions": {},
            "toolIds": ["apple_health"],
        }
        self.agentcore.invoke_agent_runtime.return_value = {"response": MagicMock()}

    def _invoke(self, **kwargs) -> dict:
        with (
            patch.object(self.agent.catalog, "resolve_for_runtime", return_value=[]),
            patch.object(
                self.agent.catalog,
                "available_tool_ids",
                side_effect=lambda _user, values: values,
            ),
            patch.object(
                self.agent.catalog,
                "resolve_tools_for_runtime",
                side_effect=lambda _user, ids, *_: [self.tool] if self.tool["id"] in ids else [],
            ),
            patch.object(self.agent, "_team_roster", return_value=[]),
            patch.object(self.agent, "read_agent_stream", return_value="Done"),
        ):
            self.agent._invoke(
                "user-1",
                "bot-1",
                self.bot,
                history=[],
                event_id="turn-1",
                **kwargs,
            )
        return json.loads(
            self.agentcore.invoke_agent_runtime.call_args.kwargs["payload"]
        )

    def test_initial_invocation_exposes_only_live_locally_granted_tools(self) -> None:
        payload = self._invoke(allow_device_tools=True)
        self.assertEqual(payload["bot"]["tools"], [])

        self.table.items[("USER#user-1", "DEVICE#iphone")] = {
            "pk": "USER#user-1",
            "sk": "DEVICE#iphone",
            "entity": "DEVICE_CAPABILITIES",
            "deviceId": "iphone",
            "platform": "ios",
            "leaseExpiresAt": int(datetime.now(UTC).timestamp()) + 60,
            "lastSeenAt": datetime.now(UTC).isoformat(),
            "tools": [
                {
                    "id": "apple_health",
                    "operations": ["apple_health_steps"],
                }
            ],
            "botGrants": [{"botId": "bot-1", "toolIds": ["apple_health"]}],
        }
        payload = self._invoke(allow_device_tools=True)
        self.assertEqual(payload["bot"]["tools"], [])
        self.assertNotIn("apple_health", payload["bot"]["toolIds"])

    def test_resume_keeps_interrupted_tool_registered_and_normalizes_decimals(
        self,
    ) -> None:
        self.tool = {
            "id": "mac_computer", "name": "Mac Computer", "risk": "read",
            "runtime": {"kind": "device", "platform": "macos",
                        "operations": ["mac_computer_observe"],
                        "interactiveOperations": []},
        }
        self.bot["toolIds"] = ["mac_computer"]
        response = {
            "id": "interrupt-1",
            "digest": "a" * 64,
            "toolUseId": "tool-use-1",
            "status": "success",
            "result": {"days": Decimal(7), "distance": Decimal("12.5")},
        }
        payload = self._invoke(device_result=response, allow_device_tools=True)

        self.assertEqual(payload["bot"]["tools"][0]["id"], "mac_computer")
        self.assertEqual(payload["deviceResult"]["result"], {
            "days": 7,
            "distance": 12.5,
        })

    def test_schedules_and_email_runs_never_advertise_device_tools(self) -> None:
        payload = self._invoke(allow_device_tools=False)
        self.assertEqual(payload["bot"]["tools"], [])

    def test_terminal_is_exposed_only_when_assigned_live_and_locally_granted(self) -> None:
        self.tool = {
            "id": "mac_terminal", "name": "Mac terminal", "risk": "interactive",
            "runtime": {
                "kind": "device", "platform": "macos",
                "operations": ["mac_terminal_list_sessions", "mac_terminal_read_session", "mac_terminal_execute_command"],
                "interactiveOperations": ["mac_terminal_execute_command"],
            },
        }
        self.bot["toolIds"] = ["mac_terminal"]
        self.assertEqual(self._invoke(allow_device_tools=True)["bot"]["tools"], [])
        lease = {
            "pk": "USER#user-1", "sk": "DEVICE#mac", "entity": "DEVICE_CAPABILITIES",
            "deviceId": "mac", "platform": "macos",
            "leaseExpiresAt": int(datetime.now(UTC).timestamp()) + 60,
            "lastSeenAt": datetime.now(UTC).isoformat(),
            "tools": [{"id": "mac_terminal", "operations": self.tool["runtime"]["operations"]}],
            "botGrants": [{"botId": "bot-1", "toolIds": ["mac_terminal"]}],
        }
        self.table.items[(lease["pk"], lease["sk"])] = lease
        self.assertEqual(self._invoke(allow_device_tools=True)["bot"]["tools"], [self.tool])
        self.assertEqual(self._invoke(allow_device_tools=False)["bot"]["tools"], [])

        self.bot["toolIds"] = []
        self.assertEqual(self._invoke(allow_device_tools=True)["bot"]["tools"], [])
        self.bot["toolIds"] = ["mac_terminal"]
        lease["botGrants"] = [{"botId": "other-bot", "toolIds": ["mac_terminal"]}]
        self.assertEqual(self._invoke(allow_device_tools=True)["bot"]["tools"], [])
        lease["botGrants"] = [{"botId": "bot-1", "toolIds": ["mac_terminal"]}]
        lease["leaseExpiresAt"] = int(datetime.now(UTC).timestamp()) - 1
        self.assertEqual(self._invoke(allow_device_tools=True)["bot"]["tools"], [])
