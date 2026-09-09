from __future__ import annotations

import importlib
import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch


class ConditionalCheckFailedException(Exception):
    pass


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
        self.meta = SimpleNamespace(
            client=SimpleNamespace(
                exceptions=SimpleNamespace(
                    ConditionalCheckFailedException=ConditionalCheckFailedException
                )
            )
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


class WorkerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.table = FakeTable()
        cls.agentcore = MagicMock()
        cls.sqs = MagicMock()
        cls.s3 = MagicMock()
        cls.cognito = MagicMock()
        cls.scheduler = MagicMock()
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
            }[service]

        environment = {
            "TABLE_NAME": "data",
            "AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-east-1:123:runtime/test",
            "QUEUE_URL": "https://sqs.example/jobs",
            "FILES_BUCKET_NAME": "frogbot-user-files-123-us-east-1",
            "SCHEDULE_GROUP_NAME": "schedules",
            "USER_POOL_ID": "us-east-1_pool",
            "FROGBOT_MEMORY_ID": "memory-1",
        }
        boto3 = ModuleType("boto3")
        boto3.resource = resource
        boto3.client = client
        dynamodb = ModuleType("boto3.dynamodb")
        conditions = ModuleType("boto3.dynamodb.conditions")
        conditions.Attr = FakeAttr
        conditions.Key = FakeAttr
        botocore = ModuleType("botocore")
        botocore_config = ModuleType("botocore.config")
        botocore_config.Config = FakeConfig

        sys.modules.pop("worker.handler", None)
        with (
            patch.dict(os.environ, environment),
            patch.dict(
                sys.modules,
                {
                    "boto3": boto3,
                    "boto3.dynamodb": dynamodb,
                    "boto3.dynamodb.conditions": conditions,
                    "botocore": botocore,
                    "botocore.config": botocore_config,
                },
            ),
        ):
            cls.handler = importlib.import_module("worker.handler")
            cls.agent = importlib.import_module("worker.agent")
            cls.work = importlib.import_module("worker.work")
            cls.artifacts = importlib.import_module("worker.artifacts")
            cls.direct_job = importlib.import_module("worker.direct_job")
            cls.group_job = importlib.import_module("worker.group_job")
            cls.job_lifecycle = importlib.import_module("worker.job_lifecycle")
            cls.background_work = importlib.import_module("worker.background_work")
            cls.runtime_jobs = importlib.import_module("worker.runtime_jobs")
            cls.account_cleanup = importlib.import_module("shared.account_cleanup")
            cls.notifications = importlib.import_module("worker.notifications")
            cls.scheduled_group_job = importlib.import_module("worker.scheduled_group_job")

    def setUp(self) -> None:
        self.table.fail_condition = False
        self.table.items.clear()
        self.table.updates.clear()
        self.s3.reset_mock()
        self.agentcore.reset_mock()
        self.sqs.reset_mock()
        self.cognito.reset_mock()
        self.scheduler.reset_mock()
        self.s3.list_objects_v2.return_value = {"Contents": []}
