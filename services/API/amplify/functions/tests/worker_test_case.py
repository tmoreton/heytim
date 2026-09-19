from __future__ import annotations

import importlib
import os
import sys
import unittest
from copy import deepcopy
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch


class ConditionalCheckFailedException(Exception):
    pass


class TransactionCanceledException(Exception):
    def __init__(self, reasons: list[dict]) -> None:
        super().__init__("Transaction cancelled")
        self.response = {"CancellationReasons": reasons}


class BotoCoreError(Exception):
    pass


class ClientError(Exception):
    pass


class FakeTypeSerializer:
    def serialize(self, value):
        return value


class FakeAttr:
    def __init__(self, name: str):
        self.name = name
        self.values = {}

    def eq(self, value):
        self.values[":pk"] = value
        return self

    def begins_with(self, value):
        self.values[":prefix"] = value
        return self

    def __and__(self, other):
        self.values.update(other.values)
        return self

    def exists(self):
        return self

    def not_exists(self):
        return self


class FakeConfig:
    def __init__(self, **_kwargs):
        pass


class FakeTable:
    def __init__(self) -> None:
        self.fail_condition = False
        self.items: dict[tuple[str, str], dict] = {}
        self.updates: list[dict] = []
        self.name = "data"
        self.client = FakeDynamoClient(self)
        self.meta = SimpleNamespace(
            client=self.client
        )

    def update_item(self, **kwargs) -> None:
        self.updates.append(kwargs)
        if self.fail_condition:
            raise ConditionalCheckFailedException

    def put_item(self, *, Item: dict, ConditionExpression=None, **_kwargs) -> None:
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.items:
            raise ConditionalCheckFailedException
        self.items[key] = dict(Item)

    def delete_item(self, *, Key: dict) -> None:
        self.items.pop((Key["pk"], Key["sk"]), None)

    def batch_writer(self):
        table = self

        class BatchWriter:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def delete_item(self, *, Key: dict) -> None:
                table.delete_item(Key=Key)

        return BatchWriter()

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, *, ExpressionAttributeValues: dict | None = None, KeyConditionExpression=None, **_kwargs) -> dict:
        ExpressionAttributeValues = ExpressionAttributeValues or KeyConditionExpression.values
        pk = ExpressionAttributeValues[":pk"]
        prefix = ExpressionAttributeValues.get(":prefix", "")
        return {
            "Items": [
                dict(item)
                for (item_pk, sk), item in self.items.items()
                if item_pk == pk and sk.startswith(prefix)
            ]
        }


class FakeDynamoClient:
    exceptions = SimpleNamespace(
        ConditionalCheckFailedException=ConditionalCheckFailedException,
        TransactionCanceledException=TransactionCanceledException,
    )

    def __init__(self, table: FakeTable) -> None:
        self.table = table
        self.transactions: list[dict] = []

    @staticmethod
    def _key(value: dict) -> tuple[str, str]:
        return value["pk"], value["sk"]

    def transact_write_items(self, **kwargs) -> None:
        self.transactions.append(deepcopy(kwargs))
        working = deepcopy(self.table.items)
        reasons = [{"Code": "None"} for _ in kwargs["TransactItems"]]
        failed = False
        for index, transaction in enumerate(kwargs["TransactItems"]):
            if "ConditionCheck" in transaction:
                operation = transaction["ConditionCheck"]
                item = working.get(self._key(operation["Key"]))
                is_account_check = operation["Key"].get("sk") == "STATE"
                account_status = item.get("accountStatus") if item else None
                account_invalid = (
                    is_account_check
                    and account_status is not None
                    and (
                        not isinstance(account_status, str)
                        or account_status in {"DELETING", "DELETED"}
                    )
                )
                circuit_invalid = (
                    not is_account_check
                    and item is not None
                    and (
                        item.get("entity") != "USAGE_CIRCUIT"
                        or item.get("open") is not False
                    )
                )
                if account_invalid or circuit_invalid:
                    reasons[index] = {"Code": "ConditionalCheckFailed"}
                    failed = True
                continue
            if "Put" in transaction:
                operation = transaction["Put"]
                key = self._key(operation["Item"])
                if key in working:
                    reasons[index] = {"Code": "ConditionalCheckFailed"}
                    failed = True
                else:
                    working[key] = deepcopy(operation["Item"])
                continue
            operation = transaction["Update"]
            key = self._key(operation["Key"])
            values = operation["ExpressionAttributeValues"]
            item = working.get(key, {**operation["Key"]})
            run_units = item.get("runUnits", 0)
            entity = item.get("entity")
            if (
                isinstance(run_units, bool)
                or not isinstance(run_units, int)
                or run_units < values[":zero"]
                or run_units > values[":maximumBefore"]
                or (entity is not None and entity != values[":entity"])
            ):
                reasons[index] = {"Code": "ConditionalCheckFailed"}
                failed = True
                continue
            item["entity"] = item.get("entity", values[":entity"])
            item["expiresAt"] = item.get("expiresAt", values[":expiry"])
            item["runUnits"] = item.get("runUnits", 0) + values[":units"]
            working[key] = item
        if failed:
            raise TransactionCanceledException(reasons)
        self.table.items = working


class WorkerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = FakeTable()
        cls.agentcore = MagicMock()
        cls.sqs = MagicMock()
        cls.s3 = MagicMock()
        cls.cognito = MagicMock()
        cls.scheduler = MagicMock()
        cls.sns = MagicMock()
        cls.cognito.exceptions.UserNotFoundException = type(
            "UserNotFoundException", (Exception,), {}
        )
        cls.scheduler.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )

        def resource(_service: str):
            return SimpleNamespace(Table=lambda _name: cls.table)

        def client(service: str, **_kwargs):
            return {
                "bedrock-agentcore": cls.agentcore,
                "sqs": cls.sqs,
                "s3": cls.s3,
                "cognito-idp": cls.cognito,
                "scheduler": cls.scheduler,
                "sns": cls.sns,
            }[service]

        environment = {
            "TABLE_NAME": "data",
            "AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-east-1:123:runtime/test",
            "QUEUE_URL": "https://sqs.example/jobs",
            "FILES_BUCKET_NAME": "frogbot-user-files-123-us-east-1",
            "SCHEDULE_GROUP_NAME": "schedules",
            "USER_POOL_ID": "us-east-1_pool",
            "HEYTIM_MEMORY_ID": "memory-1",
        }
        boto3 = ModuleType("boto3")
        boto3.resource = resource
        boto3.client = client
        dynamodb = ModuleType("boto3.dynamodb")
        conditions = ModuleType("boto3.dynamodb.conditions")
        dynamodb_types = ModuleType("boto3.dynamodb.types")
        conditions.Attr = FakeAttr
        conditions.Key = FakeAttr
        dynamodb_types.TypeSerializer = FakeTypeSerializer
        botocore = ModuleType("botocore")
        botocore_config = ModuleType("botocore.config")
        botocore_exceptions = ModuleType("botocore.exceptions")
        botocore_config.Config = FakeConfig
        botocore_exceptions.BotoCoreError = BotoCoreError
        botocore_exceptions.ClientError = ClientError

        sys.modules.pop("worker.handler", None)
        with (
            patch.dict(os.environ, environment),
            patch.dict(
                sys.modules,
                {
                    "boto3": boto3,
                    "boto3.dynamodb": dynamodb,
                    "boto3.dynamodb.conditions": conditions,
                    "boto3.dynamodb.types": dynamodb_types,
                    "botocore": botocore,
                    "botocore.config": botocore_config,
                    "botocore.exceptions": botocore_exceptions,
                },
            ),
        ):
            cls.handler = importlib.import_module("worker.handler")
            cls.agent = importlib.import_module("worker.agent")
            cls.work = importlib.import_module("worker.work")
            cls.artifacts = importlib.import_module("worker.artifacts")
            cls.direct_job = importlib.import_module("worker.direct_job")
            cls.group_job = importlib.import_module("worker.group_job")
            cls.usage_controls = importlib.import_module("worker.usage_controls")
            cls.youtube_quota = importlib.import_module("worker.youtube_quota")
            cls.job_lifecycle = importlib.import_module("worker.job_lifecycle")
            cls.background_work = importlib.import_module("worker.background_work")
            cls.runtime_jobs = importlib.import_module("worker.runtime_jobs")
            cls.account_cleanup = importlib.import_module("shared.account_cleanup")
            cls.notifications = importlib.import_module("worker.notifications")
            cls.scheduled_group_job = importlib.import_module("worker.scheduled_group_job")
            cls.event_routine_job = importlib.import_module("worker.event_routine_job")

    def setUp(self) -> None:
        self.table.fail_condition = False
        self.table.items.clear()
        self.table.updates.clear()
        self.table.client.transactions.clear()
        self.s3.reset_mock()
        self.agentcore.reset_mock()
        self.sqs.reset_mock()
        self.cognito.reset_mock()
        self.scheduler.reset_mock()
        self.s3.list_objects_v2.return_value = {"Contents": []}
