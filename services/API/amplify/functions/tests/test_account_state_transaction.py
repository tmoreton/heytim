from __future__ import annotations

import json
import unittest
from unittest.mock import call, patch

import boto3
import shared.account_state as account_state_module
from botocore.exceptions import EndpointConnectionError
from shared.account_state import (
    account_accepts_writes,
    put_user_item_while_account_active,
)


class HaltBeforeNetwork(Exception):
    pass


class StateTable:
    def __init__(self, state: dict | None) -> None:
        self.state = state

    def get_item(self, **_kwargs) -> dict:
        return {"Item": self.state} if self.state is not None else {}


class AccountStateTransactionTests(unittest.TestCase):
    def test_read_fence_rejects_malformed_account_status(self) -> None:
        self.assertFalse(
            account_accepts_writes(
                StateTable(
                    {
                        "pk": "USER#owner",
                        "sk": "STATE",
                        "accountStatus": ["ACTIVE"],
                    }
                ),
                "owner",
            )
        )
        self.assertTrue(
            account_accepts_writes(
                StateTable({"pk": "USER#owner", "sk": "STATE"}),
                "owner",
            )
        )

    def test_resource_client_marshals_native_transaction_values_on_the_wire(
        self,
    ) -> None:
        dynamodb = boto3.resource(
            "dynamodb",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        table = dynamodb.Table("test-data")
        captured: list[dict] = []

        def capture_wire_request(*, model, params: dict, **_kwargs) -> None:
            del model
            captured.append(json.loads(params["body"]))
            raise HaltBeforeNetwork

        dynamodb.meta.client.meta.events.register(
            "before-call.dynamodb.TransactWriteItems", capture_wire_request
        )
        for _ in range(2):
            with self.assertRaises(HaltBeforeNetwork):
                put_user_item_while_account_active(
                    table,
                    "owner",
                    {"pk": "USER#owner", "sk": "BOT#1", "entity": "BOT"},
                )

        self.assertEqual(
            captured[0]["ClientRequestToken"], captured[1]["ClientRequestToken"]
        )
        transaction = captured[0]["TransactItems"]
        self.assertEqual(
            transaction[0]["ConditionCheck"]["Key"]["pk"],
            {"S": "USER#owner"},
        )
        self.assertEqual(
            transaction[0]["ConditionCheck"]["ExpressionAttributeValues"][
                ":deleting"
            ],
            {"S": "DELETING"},
        )
        self.assertEqual(
            transaction[0]["ConditionCheck"]["ExpressionAttributeValues"][
                ":stringType"
            ],
            {"S": "S"},
        )
        self.assertIn(
            "attribute_type(#status, :stringType)",
            transaction[0]["ConditionCheck"]["ConditionExpression"],
        )
        self.assertEqual(
            transaction[1]["Put"]["Item"]["entity"],
            {"S": "BOT"},
        )

    def test_retry_marshals_a_fresh_native_transaction_copy(self) -> None:
        dynamodb = boto3.resource(
            "dynamodb",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        table = dynamodb.Table("test-data")
        captured: list[dict] = []

        def capture_wire_request(*, model, params: dict, **_kwargs) -> None:
            del model
            captured.append(json.loads(params["body"]))
            if len(captured) == 1:
                raise EndpointConnectionError(endpoint_url="https://dynamodb.test")
            raise HaltBeforeNetwork

        dynamodb.meta.client.meta.events.register(
            "before-call.dynamodb.TransactWriteItems", capture_wire_request
        )
        with (
            patch.object(
                account_state_module,
                "_item_was_persisted",
                return_value=False,
            ),
            patch.object(account_state_module.time, "sleep") as sleep,
            self.assertRaises(HaltBeforeNetwork),
        ):
            put_user_item_while_account_active(
                table,
                "owner",
                {"pk": "USER#owner", "sk": "BOT#1", "entity": "BOT"},
            )

        self.assertEqual(len(captured), 2)
        self.assertEqual(
            captured[0]["ClientRequestToken"], captured[1]["ClientRequestToken"]
        )
        self.assertEqual(captured[0]["TransactItems"], captured[1]["TransactItems"])
        sleep.assert_has_calls([call(0.5)])


if __name__ == "__main__":
    unittest.main()
