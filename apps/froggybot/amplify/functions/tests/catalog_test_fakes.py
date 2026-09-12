from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace


class FakeConditionalCheckFailed(Exception):
    def __init__(self) -> None:
        super().__init__("conditional check failed")
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTransactionCanceled(Exception):
    def __init__(self, failed_index: int = 0) -> None:
        super().__init__("transaction cancelled")
        reasons = [{"Code": "None"}, {"Code": "None"}]
        reasons[failed_index] = {"Code": "ConditionalCheckFailed"}
        self.response = {
            "Error": {"Code": "TransactionCanceledException"},
            "CancellationReasons": reasons,
        }


class FakeBatch:
    def __init__(self, table: FakeTable):
        self.table = table

    def put_item(self, Item: dict) -> None:
        self.table.put_item(Item=Item)

    def delete_item(self, Key: dict) -> None:
        self.table.items.pop((Key["pk"], Key["sk"]), None)


class FakeTable:
    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}
        self.name = "test-data"
        self.exceptions = SimpleNamespace(
            TransactionCanceledException=FakeTransactionCanceled
        )
        self.meta = SimpleNamespace(client=self)

    def put_item(self, *, Item: dict) -> None:
        self.items[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def delete_item(self, *, Key: dict) -> None:
        self.items.pop((Key["pk"], Key["sk"]), None)

    def update_item(
        self,
        *,
        Key: dict,
        UpdateExpression: str,
        ConditionExpression: str,
        ExpressionAttributeNames: dict,
        ExpressionAttributeValues: dict,
    ) -> None:
        item = self.items.setdefault((Key["pk"], Key["sk"]), dict(Key))
        lease_name = ExpressionAttributeNames["#lease_id"]
        if "attribute_not_exists" in ConditionExpression:
            lease_until_name = ExpressionAttributeNames["#lease_until"]
            if item.get(lease_until_name, 0) > ExpressionAttributeValues[":now"]:
                raise FakeConditionalCheckFailed
            item.update(
                {
                    ExpressionAttributeNames["#entity"]: ExpressionAttributeValues[
                        ":entity"
                    ],
                    lease_until_name: ExpressionAttributeValues[":lease_until"],
                    lease_name: ExpressionAttributeValues[":lease_id"],
                    ExpressionAttributeNames["#status"]: ExpressionAttributeValues[
                        ":syncing"
                    ],
                }
            )
            return
        if item.get(lease_name) != ExpressionAttributeValues[":lease_id"]:
            raise FakeConditionalCheckFailed
        item.update(
            {
                ExpressionAttributeNames["#next_sync"]: ExpressionAttributeValues[
                    ":next_sync"
                ],
                ExpressionAttributeNames["#last_sync"]: ExpressionAttributeValues[
                    ":last_sync"
                ],
                ExpressionAttributeNames["#status"]: ExpressionAttributeValues[
                    ":status"
                ],
            }
        )
        item.pop(ExpressionAttributeNames["#lease_until"], None)
        item.pop(lease_name, None)

    def transact_write_items(self, *, TransactItems: list[dict], **_kwargs) -> None:
        condition = TransactItems[0]["ConditionCheck"]
        state = self.items.get((condition["Key"]["pk"], condition["Key"]["sk"]))
        if state and "accountStatus" in state and (
            not isinstance(state.get("accountStatus"), str)
            or state.get("accountStatus") in {"DELETING", "DELETED"}
        ):
            raise FakeTransactionCanceled(0)
        put = TransactItems[1]["Put"]
        put_item = put["Item"]
        current = self.items.get((put_item["pk"], put_item["sk"]))
        if put.get("ConditionExpression") == "attribute_not_exists(pk)" and current:
            raise FakeTransactionCanceled(1)
        expected_secret = put.get("ExpressionAttributeValues", {}).get(
            ":expectedSecret"
        )
        if expected_secret is not None and (
            not current or current.get("secretArn") != expected_secret
        ):
            raise FakeTransactionCanceled(1)
        for operation in TransactItems:
            operation_put = operation.get("Put")
            if operation_put:
                self.put_item(Item=operation_put["Item"])

    def query(
        self, *, ExpressionAttributeValues: dict, Limit: int | None = None, **_kwargs
    ) -> dict:
        pk = ExpressionAttributeValues[":pk"]
        prefix = ExpressionAttributeValues.get(":prefix", "")
        items = [
            dict(item)
            for (item_pk, sk), item in self.items.items()
            if item_pk == pk and sk.startswith(prefix)
        ]
        return {"Items": items[:Limit] if Limit else items}

    @contextmanager
    def batch_writer(self):
        yield FakeBatch(self)


class FakeSecrets:
    class ResourceNotFoundException(Exception):
        pass

    def __init__(self):
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []
        self.exceptions = type(
            "Exceptions",
            (),
            {"ResourceNotFoundException": self.ResourceNotFoundException},
        )()

    def create_secret(self, *, Name: str, SecretString: str, **_kwargs) -> dict:
        arn = f"arn:aws:secretsmanager:us-east-1:123456789012:secret:{Name}-ABC123"
        self.values[arn] = SecretString
        return {"ARN": arn}

    def put_secret_value(self, *, SecretId: str, SecretString: str) -> None:
        self.values[SecretId] = SecretString

    def get_secret_value(self, *, SecretId: str) -> dict:
        if SecretId not in self.values:
            raise self.ResourceNotFoundException
        return {"SecretString": self.values[SecretId]}

    def delete_secret(self, *, SecretId: str, RecoveryWindowInDays: int) -> None:
        if SecretId not in self.values:
            raise self.ResourceNotFoundException
        assert RecoveryWindowInDays == 7
        self.deleted.append(SecretId)
        self.values.pop(SecretId)
