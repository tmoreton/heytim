from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

from api_test_case import ApiTestCase
from shared.device_tools import available_device_tools, select_device


class DeviceCallTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.device_calls = self.handler.authenticated_routes
        self.device_id = "11111111-1111-4111-8111-111111111111"
        self.bot_id = "22222222-2222-4222-8222-222222222222"
        self.data_table.query = MagicMock(return_value={"Items": []})

    def _registration(self) -> dict:
        return {
            "schemaVersion": 1,
            "platform": "ios",
            "appVersion": "1.0 (1)",
            "tools": [
                {
                    "id": "apple_health",
                    "operations": ["apple_health_steps"],
                }
            ],
            "botGrants": [
                {"botId": self.bot_id, "toolIds": ["apple_health"]}
            ],
        }

    def test_capability_lease_is_platform_scoped_and_rejects_non_json_shapes(
        self,
    ) -> None:
        receipt = self.device_calls.register_device_capabilities(
            "user-1", self.device_id, self._registration()
        )
        self.assertTrue(receipt["registered"])
        item = self.data_table.items[("USER#user-1", f"DEVICE#{self.device_id}")]
        self.assertEqual(item["platform"], "ios")
        self.assertEqual(item["tools"][0]["operations"], ["apple_health_steps"])
        self.assertGreater(item["leaseExpiresAt"], int(datetime.now(UTC).timestamp()))

        invalid = self._registration()
        invalid["tools"][0]["operations"] = [{"not": "a string"}]
        with self.assertRaises(self.support.ApiError) as error:
            self.device_calls.register_device_capabilities(
                "user-1", self.device_id, invalid
            )
        self.assertEqual(error.exception.status_code, 400)

    def test_mac_v2_capability_accepts_only_known_platform_operations(self) -> None:
        registration = {
            "schemaVersion": 1,
            "platform": "macos",
            "appVersion": "1.0 (1)",
            "tools": [
                {
                    "id": "mac_computer",
                    "operations": [
                        "mac_computer_observe",
                        "mac_computer_act_on_element",
                        "mac_computer_wait_for_state",
                        "mac_computer_scroll",
                    ],
                }
            ],
            "botGrants": [
                {"botId": self.bot_id, "toolIds": ["mac_computer"]}
            ],
        }
        self.device_calls.register_device_capabilities(
            "user-1", self.device_id, registration
        )
        item = self.data_table.items[
            ("USER#user-1", f"DEVICE#{self.device_id}")
        ]
        self.assertIn("mac_computer_scroll", item["tools"][0]["operations"])

        registration["tools"][0]["operations"] = ["apple_health_steps"]
        with self.assertRaises(self.support.ApiError) as error:
            self.device_calls.register_device_capabilities(
                "user-1", self.device_id, registration
            )
        self.assertEqual(error.exception.status_code, 400)

    def test_only_live_per_bot_grants_make_a_device_tool_available(self) -> None:
        live = {
            "entity": "DEVICE_CAPABILITIES",
            "deviceId": self.device_id,
            "platform": "ios",
            "leaseExpiresAt": int(datetime.now(UTC).timestamp()) + 60,
            "lastSeenAt": "2026-09-25T12:00:00+00:00",
            "tools": [
                {
                    "id": "apple_health",
                    "operations": ["apple_health_steps"],
                }
            ],
            "botGrants": [
                {"botId": self.bot_id, "toolIds": ["apple_health"]}
            ],
        }
        self.data_table.query.return_value = {"Items": [live]}
        resolved = [
            {
                "id": "apple_health",
                "runtime": {
                    "kind": "device",
                    "platform": "ios",
                    "operations": [
                        "apple_health_steps",
                        "apple_health_workouts",
                    ],
                    "interactiveOperations": [],
                },
            }
        ]
        filtered = available_device_tools(
            self.data_table, "user-1", self.bot_id, resolved
        )
        self.assertEqual(
            filtered[0]["runtime"]["operations"], ["apple_health_steps"]
        )
        self.assertEqual(
            select_device(
                self.data_table,
                "user-1",
                self.bot_id,
                tool_id="apple_health",
                operation="apple_health_steps",
                platform="ios",
            )["deviceId"],
            self.device_id,
        )
        self.assertEqual(
            available_device_tools(
                self.data_table, "user-1", "another-bot", resolved
            ),
            [],
        )

    def test_exact_result_resumes_only_the_assigned_waiting_turn(self) -> None:
        digest = "a" * 64
        call_id = "b" * 64
        proposal = {
            "id": "interrupt-1",
            "toolUseId": "tool-use-1",
            "toolName": "apple_health_steps",
            "input": {"days": 7},
            "platform": "ios",
            "toolId": "apple_health",
            "digest": digest,
            "expiresAt": "2099-09-25T12:05:00+00:00",
        }
        request = {**proposal, "callId": call_id, "deviceId": self.device_id}
        call = {
            "pk": "USER#user-1",
            "sk": f"DEVICE_CALL#{call_id}",
            "entity": "DEVICE_CALL",
            "id": call_id,
            "status": "PENDING",
            "userId": "user-1",
            "botId": self.bot_id,
            "turnId": "turn-1",
            "turnPk": f"CHAT#user-1#{self.bot_id}",
            "turnKey": "TURN#turn-1",
            "deviceId": self.device_id,
            "proposal": proposal,
            "request": request,
            "expiresAt": int(datetime(2099, 9, 25, tzinfo=UTC).timestamp()),
        }
        turn = {
            "pk": call["turnPk"],
            "sk": call["turnKey"],
            "status": "AWAITING_DEVICE",
            "deviceRequest": request,
        }
        self.data_table.put_item(Item=call)
        self.data_table.put_item(Item=turn)

        result = self.device_calls.submit_device_call_result(
            "user-1",
            self.device_id,
            call_id,
            {
                "requestDigest": digest,
                "status": "success",
                "result": {"days": [{"date": "2026-09-25", "steps": 8_000}]},
            },
        )
        self.assertTrue(result["accepted"])
        turn_update = self.data_table.updated[-2]
        self.assertEqual(
            turn_update["ExpressionAttributeValues"][":request"], request
        )
        self.assertEqual(
            turn_update["ExpressionAttributeValues"][":result"]["digest"], digest
        )
        self.assertIsInstance(
            turn_update["ExpressionAttributeValues"][":now"], str
        )
        queued = json.loads(self.sqs.send_message.call_args.kwargs["MessageBody"])
        expected = {
            "type": "AGENT_REPLY",
            "userId": "user-1",
            "botId": self.bot_id,
            "turnKey": "TURN#turn-1",
        }
        self.assertEqual({key: queued[key] for key in expected}, expected)
        self.assertEqual(queued["schemaVersion"], 1)

        with self.assertRaises(self.support.ApiError) as error:
            self.device_calls.submit_device_call_result(
                "user-1",
                self.device_id,
                call_id,
                {
                    "requestDigest": "0" * 64,
                    "status": "success",
                    "result": {},
                },
            )
        self.assertEqual(error.exception.status_code, 409)


if __name__ == "__main__":
    import unittest

    unittest.main()
