from __future__ import annotations

import importlib
import os
import sys
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch


class ConditionalCheckFailedException(Exception):
    pass


class FakeAttr:
    def __init__(self, _name: str):
        pass

    def not_exists(self):
        return self


class FakeConfig:
    def __init__(self, **_kwargs):
        pass


class FakeTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}
        self.meta = SimpleNamespace(
            client=SimpleNamespace(
                exceptions=SimpleNamespace(
                    ConditionalCheckFailedException=ConditionalCheckFailedException
                )
            )
        )

    def put_item(self, *, Item: dict, **kwargs) -> None:
        key = (Item["pk"], Item["sk"])
        if kwargs.get("ConditionExpression") is not None and key in self.items:
            raise ConditionalCheckFailedException
        self.items[key] = dict(Item)


class UsageTests(unittest.TestCase):
    def test_durable_usage_keeps_integer_decimal_token_counts(self):
        self.assertEqual(self.usage._count(Decimal(1234)), 1234)
        self.assertEqual(self.usage._count(Decimal("1.2")), 0)

    @classmethod
    def setUpClass(cls) -> None:
        cls.table = FakeTable()
        boto3 = ModuleType("boto3")
        boto3.resource = lambda _service: SimpleNamespace(  # type: ignore[attr-defined]
            Table=lambda _name: cls.table
        )
        boto3.client = MagicMock()  # type: ignore[attr-defined]
        dynamodb = ModuleType("boto3.dynamodb")
        conditions = ModuleType("boto3.dynamodb.conditions")
        conditions.Attr = FakeAttr  # type: ignore[attr-defined]
        botocore = ModuleType("botocore")
        botocore_config = ModuleType("botocore.config")
        botocore_config.Config = FakeConfig  # type: ignore[attr-defined]
        support = ModuleType("worker.support")
        support.table = cls.table  # type: ignore[attr-defined]
        environment = {
            "TABLE_NAME": "data",
            "AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-east-1:123:runtime/test",
            "QUEUE_URL": "https://sqs.example/jobs",
            "FILES_BUCKET_NAME": "frogbot-user-files-123-us-east-1",
        }
        for module in ("worker.usage", "worker.support"):
            sys.modules.pop(module, None)
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
                    "worker.support": support,
                },
            ),
        ):
            cls.usage = importlib.import_module("worker.usage")

    @classmethod
    def tearDownClass(cls) -> None:
        for module in ("worker.usage", "worker.support"):
            sys.modules.pop(module, None)

    def setUp(self) -> None:
        self.table.items.clear()

    def test_combines_provider_cost_with_fallback_estimate(self) -> None:
        item = self.usage._usage_item(
            "user-1",
            "queue-message-1",
            {
                "models": [
                    {
                        "provider": "openrouter",
                        "modelId": "z-ai/glm-5.3-flash",
                        "callCount": 2,
                        "inputTokens": 1_000,
                        "outputTokens": 200,
                        "totalTokens": 1_200,
                        "providerCostUsd": "0.00123",
                    },
                    {
                        "provider": "bedrock",
                        "modelId": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
                        "callCount": 1,
                        "inputTokens": 1_000,
                        "outputTokens": 100,
                        "totalTokens": 1_100,
                    },
                ]
            },
            work_type="direct",
            bot_id="bot-1",
            now=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        )

        self.assertIsNotNone(item)
        self.assertEqual(item["pk"], "USER#user-1")
        self.assertEqual(item["sk"], "USAGE#queue-message-1")
        self.assertEqual(item["usageMonth"], "2026-09")
        self.assertEqual(item["callCount"], 3)
        self.assertEqual(item["totalTokens"], 2_300)
        self.assertEqual(item["providerReportedCostUsd"], Decimal("0.001230000000"))
        self.assertEqual(item["costUsd"], Decimal("0.005730000000"))
        self.assertEqual(item["costBasis"], "mixed")

    def test_event_is_idempotent_for_a_queue_message(self) -> None:
        report = {
            "models": [
                {
                    "provider": "openrouter",
                    "modelId": "z-ai/glm-5.3-flash",
                    "callCount": 1,
                    "inputTokens": 100,
                    "outputTokens": 20,
                    "totalTokens": 120,
                    "providerCostUsd": "0.0001",
                }
            ]
        }

        first = self.usage.record_invocation_usage(
            "user-1",
            "queue-message-1",
            report,
            work_type="direct",
            bot_id="bot-1",
        )
        second = self.usage.record_invocation_usage(
            "user-1",
            "queue-message-1",
            report,
            work_type="direct",
            bot_id="bot-1",
        )

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(self.table.items), 1)

    def test_records_provider_tool_call_counts(self) -> None:
        item = self.usage._usage_item(
            "user-1",
            "queue-message-1",
            {
                "models": [],
                "tools": [
                    {
                        "provider": "agentcore-gateway",
                        "operation": "youtube_search",
                        "callCount": 2,
                    }
                ],
            },
            work_type="direct",
            bot_id="bot-1",
            now=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(item["toolCallCount"], 2)
        self.assertEqual(item["tools"][0]["operation"], "youtube_search")
        self.assertEqual(item["costBasis"], "not_applicable")

    def test_image_dispatch_marks_cost_partial_even_with_exact_text_model_cost(self) -> None:
        item = self.usage._usage_item(
            "user-1", "event-1",
            {
                "models": [{
                    "provider": "openrouter", "modelId": "deepseek/deepseek-v4.1-flash",
                    "callCount": 1, "inputTokens": 100, "outputTokens": 10,
                    "providerCostUsd": "0.0001",
                }],
                "tools": [{
                    "provider": "openrouter", "operation": "generate_image",
                    "callCount": 1,
                }],
            },
            work_type="direct", bot_id="bot-1",
        )

        self.assertEqual(item["costUsd"], Decimal("0.000100000000"))
        self.assertTrue(item["costIncomplete"])
        self.assertTrue(item["imageCostIncomplete"])
        self.assertEqual(item["costBasis"], "partial")

    def test_image_cost_flag_survives_bounded_tool_diagnostics(self) -> None:
        tools = [
            {"provider": "other", "operation": f"operation_{index}", "callCount": 1}
            for index in range(32)
        ]
        tools.append({"provider": "openrouter", "operation": "generate_image", "callCount": 1})
        item = self.usage._usage_item(
            "user-1", "event-1", {"models": [], "tools": tools},
            work_type="direct", bot_id="bot-1",
        )

        self.assertEqual(len(item["tools"]), 32)
        self.assertTrue(item["imageCostIncomplete"])
        self.assertTrue(item["costIncomplete"])

    def test_reported_image_usage_adds_exact_cost_and_tokens(self) -> None:
        item = self.usage._usage_item(
            "user-1", "event-1", {
                "models": [{
                    "provider": "openrouter_image", "modelId": "openai/gpt-image-2.5-sunburst",
                    "callCount": 1, "inputTokens": 120, "outputTokens": 80,
                    "tokenReportAvailable": True, "providerCostUsd": "0.0123",
                }],
                "tools": [{
                    "provider": "openrouter", "operation": "generate_image", "callCount": 1,
                }],
            }, work_type="direct", bot_id="bot-1",
        )

        self.assertEqual(item["costUsd"], Decimal("0.012300000000"))
        self.assertEqual(item["inputTokens"], 120)
        self.assertEqual(item["outputTokens"], 80)
        self.assertFalse(item["costIncomplete"])
        self.assertFalse(item["imageCostIncomplete"])
        self.assertFalse(item["tokenIncomplete"])

    def test_unreported_image_response_marks_cost_and_tokens_partial(self) -> None:
        item = self.usage._usage_item(
            "user-1", "event-1", {
                "models": [{
                    "provider": "openrouter_image", "modelId": "openai/gpt-image-2.5-sunburst",
                    "callCount": 1, "tokenReportAvailable": False,
                }],
                "tools": [{
                    "provider": "openrouter", "operation": "generate_image", "callCount": 1,
                }],
            }, work_type="direct", bot_id="bot-1",
        )

        self.assertTrue(item["imageCostIncomplete"])
        self.assertTrue(item["tokenIncomplete"])

    def test_default_deepseek_model_has_a_fallback_price(self) -> None:
        item = self.usage._usage_item(
            "user-1",
            "queue-message-1",
            {
                "models": [
                    {
                        "provider": "openrouter",
                        "modelId": "deepseek/deepseek-v4.1-flash",
                        "callCount": 1,
                        "inputTokens": 1_000_000,
                        "outputTokens": 1_000_000,
                        "totalTokens": 2_000_000,
                    }
                ]
            },
            work_type="direct",
            bot_id="bot-1",
            now=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
        )

        self.assertEqual(item["costUsd"], Decimal("0.750000000000"))
        self.assertFalse(item["costIncomplete"])

    def test_deepseek_cache_reads_replace_regular_input_in_estimate(self) -> None:
        item = self.usage._usage_item(
            "user-1",
            "queue-message-1",
            {
                "models": [
                    {
                        "provider": "openrouter",
                        "modelId": "deepseek/deepseek-v4.1-flash",
                        "callCount": 1,
                        "inputTokens": 1_000_000,
                        "cacheReadInputTokens": 800_000,
                        "outputTokens": 0,
                    }
                ]
            },
            work_type="direct",
            bot_id="bot-1",
        )

        self.assertEqual(item["costUsd"], Decimal("0.032400000000"))

    def test_message_summary_exposes_cost_and_reported_cache_share(self) -> None:
        summary = self.usage.message_usage_summary({
            "models": [{
                "provider": "openrouter",
                "modelId": "deepseek/deepseek-v4.1-flash",
                "callCount": 1,
                "inputTokens": 100,
                "cacheReadInputTokens": 75,
                "outputTokens": 20,
                "providerCostUsd": "0.00012",
            }],
            "calls": [{
                "provider": "openrouter",
                "modelId": "deepseek/deepseek-v4.1-flash",
                "headerFingerprint": "0123456789abcdef",
                "toolCount": 2,
                "messageCount": 3,
                "durationMs": 150,
                "status": "complete",
                "inputTokens": 100,
                "cacheReadInputTokens": 75,
                "cacheReportAvailable": True,
            }],
        })

        self.assertEqual(summary["costUsd"], "0.000120000000")
        self.assertTrue(summary["cacheReportAvailable"])
        self.assertEqual(summary["cacheReadInputTokens"], 75)
        self.assertNotIn("headerFingerprint", summary)

    def test_failed_unmetered_attempt_marks_cost_incomplete(self) -> None:
        item = self.usage._usage_item(
            "user-1", "event-1",
            {
                "models": [{
                    "provider": "openrouter",
                    "modelId": "deepseek/deepseek-v4.1-flash",
                    "callCount": 1, "inputTokens": 100, "outputTokens": 10,
                    "providerCostUsd": "0.0001",
                }],
                "calls": [{
                    "provider": "openrouter",
                    "modelId": "deepseek/deepseek-v4.1-flash",
                    "headerFingerprint": "0123456789abcdef",
                    "status": "failed", "inputTokens": 0,
                }],
            },
            work_type="direct", bot_id="bot-1",
        )

        self.assertTrue(item["costIncomplete"])
        self.assertEqual(item["costBasis"], "partial")

    def test_bedrock_cache_tokens_are_separate_from_regular_input(self) -> None:
        item = self.usage._usage_item(
            "user-1",
            "queue-message-1",
            {
                "models": [
                    {
                        "provider": "bedrock",
                        "modelId": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
                        "callCount": 1,
                        "inputTokens": 100,
                        "cacheReadInputTokens": 800,
                        "cacheWriteInputTokens": 100,
                        "outputTokens": 0,
                    }
                ]
            },
            work_type="direct",
            bot_id="bot-1",
        )

        self.assertEqual(item["costUsd"], Decimal("0.001140000000"))

    def test_idempotency_key_does_not_change_across_month_boundary(self) -> None:
        report = {
            "models": [
                {
                    "provider": "openrouter",
                    "modelId": "z-ai/glm-5.3-flash",
                    "callCount": 1,
                    "totalTokens": 1,
                }
            ]
        }
        before = self.usage._usage_item(
            "user-1",
            "queue-message-1",
            report,
            work_type="direct",
            bot_id="bot-1",
            now=datetime(2026, 9, 30, 23, 59, tzinfo=UTC),
        )
        after = self.usage._usage_item(
            "user-1",
            "queue-message-1",
            report,
            work_type="direct",
            bot_id="bot-1",
            now=datetime(2026, 10, 1, 0, 1, tzinfo=UTC),
        )

        self.assertEqual(before["sk"], after["sk"])
        self.assertNotEqual(before["usageMonth"], after["usageMonth"])


if __name__ == "__main__":
    unittest.main()
