from __future__ import annotations

import importlib
import os
import sys
import unittest
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch


class ConditionalCheckFailedException(Exception):
    pass


class UserNotFoundException(Exception):
    pass


class FakeCondition:
    def __and__(self, _other):
        return self

    def __or__(self, _other):
        return self


class FakeAttr(FakeCondition):
    def __init__(self, _name: str):
        pass

    def eq(self, _value):
        return self

    def is_in(self, _value):
        return self

    def begins_with(self, _value):
        return self

    def exists(self):
        return self

    def not_exists(self):
        return self


class FakeConfig:
    def __init__(self, **_kwargs):
        pass


class FakeBatch:
    def __init__(self, table: FakeTable):
        self.table = table

    def put_item(self, Item: dict) -> None:
        self.table.put_item(Item=Item)

    def delete_item(self, Key: dict) -> None:
        self.table.deleted.append(dict(Key))
        self.table.items.pop(self.table._storage_key(Key), None)


class FakeTable:
    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}
        self.deleted: list[dict] = []
        self.put: list[dict] = []
        self.updated: list[dict] = []
        self.meta = SimpleNamespace(
            client=SimpleNamespace(
                exceptions=SimpleNamespace(
                    ConditionalCheckFailedException=ConditionalCheckFailedException
                )
            )
        )

    @staticmethod
    def _storage_key(value: dict) -> tuple[str, str]:
        if "pk" in value and "sk" in value:
            return value["pk"], value["sk"]
        return "tokenHash", value["tokenHash"]

    @contextmanager
    def batch_writer(self):
        yield FakeBatch(self)

    def put_item(self, *, Item: dict, **_kwargs) -> None:
        self.put.append(dict(Item))
        self.items[self._storage_key(Item)] = dict(Item)

    def delete_item(self, *, Key: dict, ReturnValues: str | None = None) -> dict:
        self.deleted.append(dict(Key))
        item = None
        item = self.items.pop(self._storage_key(Key), None)
        return {"Attributes": dict(item)} if ReturnValues == "ALL_OLD" and item else {}

    def update_item(self, **kwargs) -> None:
        self.updated.append(kwargs)

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get(self._storage_key(Key))
        return {"Item": dict(item)} if item else {}

    def scan(self, **_kwargs) -> dict:
        return {"Items": []}


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data_table = FakeTable()
        cls.invite_table = FakeTable()
        cls.sqs = MagicMock()
        cls.scheduler = MagicMock()
        cls.scheduler.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        cls.cognito = MagicMock()
        cls.cognito.exceptions.UserNotFoundException = UserNotFoundException
        cls.agentcore = MagicMock()
        cls.agentcore.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        cls.s3 = MagicMock()

        def resource(_service: str):
            return SimpleNamespace(
                Table=lambda name: (
                    cls.invite_table if name == "invites" else cls.data_table
                )
            )

        def client(service: str, **_kwargs):
            return {
                "sqs": cls.sqs,
                "scheduler": cls.scheduler,
                "cognito-idp": cls.cognito,
                "bedrock-agentcore": cls.agentcore,
                "s3": cls.s3,
            }[service]

        environment = {
            "TABLE_NAME": "data",
            "INVITE_TABLE_NAME": "invites",
            "QUEUE_URL": "https://sqs.example/jobs",
            "QUEUE_ARN": "arn:aws:sqs:us-east-1:123:jobs",
            "SCHEDULE_DLQ_ARN": "arn:aws:sqs:us-east-1:123:dlq",
            "SCHEDULE_GROUP_NAME": "schedules",
            "SCHEDULE_ROLE_ARN": "arn:aws:iam::123:role/scheduler",
            "USER_POOL_ID": "us-east-1_pool",
            "AGENT_RUNTIME_ARN": (
                "arn:aws:bedrock-agentcore:us-east-1:123:runtime/test"
            ),
            "AGENT_RUNTIME_QUALIFIER": "DEFAULT",
            "FILES_BUCKET_NAME": "frogbot-user-files-123-us-east-1",
            "GOOGLE_OAUTH_SECRET_ARN": (
                "arn:aws:secretsmanager:us-east-1:123:secret:"
                "frogbot/oauth/google-ABC123"
            ),
            "GOOGLE_OAUTH_REDIRECT_URI": (
                "https://api.example.com/public/oauth/google/callback"
            ),
        }
        boto3 = ModuleType("boto3")
        boto3.resource = resource
        boto3.client = client
        dynamodb = ModuleType("boto3.dynamodb")
        conditions = ModuleType("boto3.dynamodb.conditions")
        conditions.Attr = FakeAttr
        botocore = ModuleType("botocore")
        botocore_config = ModuleType("botocore.config")
        botocore_config.Config = FakeConfig

        sys.modules.pop("api.handler", None)
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
            cls.handler = importlib.import_module("api.handler")
            cls.support = importlib.import_module("api.support")
            cls.attachments = importlib.import_module("api.attachments")
            cls.bot_documents = importlib.import_module("api.bot_documents")
            cls.bots = importlib.import_module("api.bots")
            cls.direct_chat = importlib.import_module("api.direct_chat")
            cls.groups = importlib.import_module("api.groups")
            cls.google_oauth = importlib.import_module("api.google_oauth")
            cls.memories = importlib.import_module("api.memories")
            cls.schedules = importlib.import_module("api.schedules")
            cls.sharing = importlib.import_module("api.sharing")
            cls.account = importlib.import_module("api.account")

    def setUp(self) -> None:
        self.data_table.items.clear()
        self.data_table.deleted.clear()
        self.data_table.put.clear()
        self.data_table.updated.clear()
        self.invite_table.deleted.clear()
        self.cognito.reset_mock()
        self.agentcore.reset_mock()
        self.sqs.reset_mock()
        self.s3.reset_mock()
        self.s3.list_object_versions.return_value = {}
