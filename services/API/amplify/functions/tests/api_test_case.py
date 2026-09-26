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


class TransactionCanceledException(Exception):
    def __init__(self, failed_index: int = 0, item_count: int = 2) -> None:
        super().__init__("transaction cancelled")
        reasons = [{"Code": "None"} for _ in range(item_count)]
        reasons[failed_index] = {"Code": "ConditionalCheckFailed"}
        self.response = {
            "Error": {"Code": "TransactionCanceledException"},
            "CancellationReasons": reasons,
        }


class UserNotFoundException(Exception):
    pass


class BotoCoreError(Exception):
    pass


class ClientError(Exception):
    pass


class ParamValidationError(Exception):
    pass


class FakeTypeSerializer:
    def serialize(self, value):
        return value


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
        self.name = "data"
        self.deleted: list[dict] = []
        self.put: list[dict] = []
        self.updated: list[dict] = []
        self.exceptions = SimpleNamespace(
            ConditionalCheckFailedException=ConditionalCheckFailedException,
            TransactionCanceledException=TransactionCanceledException,
        )
        self.meta = SimpleNamespace(client=self)

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

    def transact_write_items(self, *, TransactItems: list[dict], **_kwargs) -> None:
        condition = TransactItems[0]["ConditionCheck"]
        state = self.items.get(self._storage_key(condition["Key"]))
        if state and "accountStatus" in state and (
            not isinstance(state.get("accountStatus"), str)
            or state.get("accountStatus") in {"DELETING", "DELETED"}
        ):
            raise TransactionCanceledException(0)
        if (
            len(TransactItems) > 2
            and "ConditionCheck" in TransactItems[1]
            and "emailToken" in TransactItems[1]["ConditionCheck"].get("ConditionExpression", "")
        ):
            guard = TransactItems[1]["ConditionCheck"]
            current = self.items.get(self._storage_key(guard["Key"]))
            expected = guard.get("ExpressionAttributeValues", {}).get(":expectedEmailToken")
            if not current or current.get("emailToken") != expected:
                raise TransactionCanceledException(1, len(TransactItems))
        put = TransactItems[-1]["Put"]
        put_item = put["Item"]
        current = self.items.get(self._storage_key(put_item))
        if put.get("ConditionExpression") == "attribute_not_exists(pk)" and current:
            raise TransactionCanceledException(len(TransactItems) - 1, len(TransactItems))
        for operation in TransactItems:
            put = operation.get("Put")
            if put:
                self.put_item(Item=put["Item"])

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
        cls.sns = MagicMock()

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
                "sns": cls.sns,
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
                "heytim/oauth/google-ABC123"
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
        conditions.Key = FakeAttr
        dynamodb_types = ModuleType("boto3.dynamodb.types")
        dynamodb_types.TypeSerializer = FakeTypeSerializer
        botocore = ModuleType("botocore")
        botocore_config = ModuleType("botocore.config")
        botocore_exceptions = ModuleType("botocore.exceptions")
        botocore_config.Config = FakeConfig
        botocore_exceptions.BotoCoreError = BotoCoreError
        botocore_exceptions.ClientError = ClientError
        botocore_exceptions.ParamValidationError = ParamValidationError

        sys.modules.pop("api.handler", None)
        sys.modules.pop("api.public_handler", None)
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
            cls.handler = importlib.import_module("api.handler")
            cls.public_handler = importlib.import_module("api.public_handler")
            cls.billing = importlib.import_module("api.billing")
            cls.support = importlib.import_module("api.support")
            cls.attachments = importlib.import_module("api.attachments")
            cls.bot_documents = importlib.import_module("api.bot_documents")
            cls.bots = importlib.import_module("api.bots")
            cls.bot_inbox = importlib.import_module("api.bot_inbox")
            cls.direct_chat = importlib.import_module("api.direct_chat")
            cls.groups = importlib.import_module("api.groups")
            cls.group_messages = importlib.import_module("api.group_messages")
            cls.group_runs = importlib.import_module("api.group_runs")
            cls.google_oauth = importlib.import_module("api.google_oauth")
            cls.finance = importlib.import_module("api.finance_connections")
            cls.github_webhook = importlib.import_module("api.github_webhook")
            cls.memories = importlib.import_module("api.memories")
            cls.schedules = importlib.import_module("api.schedules")
            cls.group_schedules = importlib.import_module("api.group_schedules")
            cls.group_routines = importlib.import_module("api.group_routines")
            cls.workspaces = importlib.import_module("api.workspaces")
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
        self.sns.reset_mock()
        self.s3.list_object_versions.return_value = {}
