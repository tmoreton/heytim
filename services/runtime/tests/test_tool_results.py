from __future__ import annotations

import asyncio
import csv
import io
import json
import re
from unittest.mock import Mock

import pytest
from strands import tool
from strands.models import Model
from strands_harness import create_harness

from heytim_runtime.tool_results import PAGE_CHARS, ResultStorage, ToolResultOffloader
from model.usage import UsageAccumulator, UsageTrackingModel

PREFIX = (
    "users/" + "a" * 64 + "/bots/finance/artifacts/12345678-1234-1234-1234-123456789012"
)


class Store:
    def __init__(self):
        self.objects = {}
        self.reads = []

    def put_object(self, *, Key, Body, ContentType, **_kwargs):
        self.objects[Key] = (Body, ContentType)

    def get_object(self, *, Key, **_kwargs):
        data, content_type = self.objects[Key]
        body = io.BytesIO(data)
        self.reads.append(body)
        return {"Body": body, "ContentType": content_type}


def records():
    return [
        {
            "transaction_id": f"txn_{i}",
            "date": "2026-09-25",
            "amount": i + 0.25,
            "name": f"Merchant {i}",
            "metadata": {"description": "x" * 1_300},
        }
        for i in range(21)
    ]


def test_single_line_json_is_fully_readable_with_explicit_cursor():
    async def run():
        storage = ResultStorage(None)
        source = {"transactions": records(), "hasMore": False}
        reference = await storage.store("call-1", json.dumps(source).encode())
        plugin = ToolResultOffloader(storage)
        offset, pieces = 0, []
        while True:
            page = json.loads(
                await plugin.retrieve_offloaded_content(reference, offset)
            )
            assert len(page["text"]) <= PAGE_CHARS
            assert page["offset"] == offset
            pieces.append(page["text"])
            if page["nextOffset"] is None:
                break
            assert page["nextOffset"] > offset
            offset = page["nextOffset"]
        assert json.loads("".join(pieces)) == source
        found = json.loads(
            await plugin.retrieve_offloaded_content(reference, pattern="hasMore")
        )
        assert '"hasMore": false' in found["text"]

    asyncio.run(run())


def test_long_individual_string_and_unicode_are_not_lost():
    async def run():
        storage = ResultStorage(None)
        source = "long line: " + 'café 漢字😀\\"\n' * 2_000
        reference = await storage.store("call", source.encode())
        plugin = ToolResultOffloader(storage)
        pages, offset = [], 0
        while offset is not None:
            encoded = await plugin.retrieve_offloaded_content(reference, offset)
            assert len(json.dumps(encoded)) <= 4_000
            page = json.loads(encoded)
            pages.append(page["text"])
            offset = page["nextOffset"]
        assert "".join(pages) == source

    asyncio.run(run())


def test_saved_results_survive_recreation_and_are_bound_to_authorized_turn():
    async def run():
        client = Store()
        first = ResultStorage(PREFIX, client=client)
        reference = await first.store("call", b'{"private":true}')
        resumed = ResultStorage(PREFIX, client=client)
        assert await resumed.retrieve(reference) == (b'{"private":true}', "text/plain")
        assert client.reads[-1].closed
        foreign = ResultStorage(PREFIX.replace("/finance/", "/other/"), client=client)
        with pytest.raises(ValueError, match="outside this turn"):
            await foreign.retrieve(reference)
        for invalid in ("../secret", f"s3://bucket/{reference}", "result_unknown"):
            with pytest.raises(ValueError, match="outside this turn"):
                await resumed.retrieve(invalid)
        assert len(client.reads) == 1

    asyncio.run(run())


def test_export_joins_pages_without_dropping_fields_or_reconstructing_values():
    async def run():
        source = records()
        source[1]["extra"] = "=SUM(1,2)"
        source[2]["name"] = 'Comma, quote " and\nnewline'
        source[3]["amount"] = -19.5
        storage = ResultStorage(None)
        references = [
            await storage.store(str(i), json.dumps({"transactions": rows}).encode())
            for i, rows in enumerate((source[:10], source[10:]))
        ]
        save = Mock(return_value="Saved export.csv")
        workspace = Mock(return_value="Staged finance/2026")
        plugin = ToolResultOffloader(
            storage, save_artifact=save, save_workspace=workspace
        )
        result = await plugin.export_tool_result(
            references, "2026.csv", "/transactions", "finance/2026"
        )
        assert "Exported 21 records" in result
        save.assert_not_called()
        key, name, content = workspace.call_args.args
        assert (key, name) == ("finance/2026", "2026.csv")
        exported = list(csv.DictReader(io.StringIO(content)))
        assert len(exported) == 21
        for original, row in zip(source, exported, strict=True):
            assert row["transaction_id"] == original["transaction_id"]
            assert float(row["amount"]) == original["amount"]
            assert json.loads(row["metadata"]) == original["metadata"]
            assert row["name"] == original["name"]
        assert exported[1]["extra"] == "'=SUM(1,2)"
        await plugin.export_tool_result(references, "2026.json", "/transactions")
        assert json.loads(save.call_args.args[1]) == source
        with pytest.raises(ValueError, match="exactly once"):
            await plugin.export_tool_result(
                [references[0]] * 2, "2026.csv", "/transactions"
            )
        with pytest.raises(ValueError, match="not found"):
            await plugin.export_tool_result(references, "2026.csv", "/missing")
        assert save.call_count == 1
        assert workspace.call_count == 1

    asyncio.run(run())


class ExportModel(Model):
    """Exercise the installed harness, including its automatic context manager."""

    def __init__(self):
        self.config = {"model_id": "test", "context_window_limit": 200_000}
        self.calls = 0

    def get_config(self):
        return self.config

    def update_config(self, **kwargs):
        self.config.update(kwargs)

    async def structured_output(self, *_args, **_kwargs):
        raise AssertionError("Unexpected compaction")
        yield

    async def stream(self, messages, *_args, **_kwargs):
        self.calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if self.calls == 1:
            name, arguments = "fetch_transactions", {}
        elif self.calls == 2:
            previous = messages[-1]["content"][0]["toolResult"]["content"][0]["text"]
            assert '"hasMore": false' in previous
            assert '"records": 21' in previous
            reference = re.search(r"result_[a-f0-9]{24}_[a-f0-9]{32}", previous).group()
            name, arguments = (
                "export_tool_result",
                {
                    "references": [reference],
                    "filename": "2026.csv",
                    "records_path": "/transactions",
                },
            )
        else:
            assert self.calls == 3
            assert "Exported 21 records" in json.dumps(messages[-1])
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"text": "Saved all 21 transactions."},
                }
            }
            yield {"messageStop": {"stopReason": "end_turn"}}
            return
        yield {
            "contentBlockStart": {
                "contentBlockIndex": 0,
                "start": {"toolUse": {"toolUseId": f"call-{self.calls}", "name": name}},
            }
        }
        yield {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"toolUse": {"input": json.dumps(arguments)}},
            }
        }
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "tool_use"}}


def test_21_record_export_completes_with_one_provider_call_in_live_harness():
    usage = UsageAccumulator()
    source = records()

    @tool
    def fetch_transactions() -> str:
        """Read a page of transactions."""
        usage.observe_tool("plaid", "plaid_transactions")
        return json.dumps(
            {"transactions": source, "totalTransactions": 21, "hasMore": False}
        )

    save = Mock(return_value="Saved 2026.csv")
    plugin = ToolResultOffloader(ResultStorage(None), save_artifact=save)
    delegate = ExportModel()
    model = UsageTrackingModel(delegate, usage, provider="test", model_id="test")
    agent = create_harness(
        model=model,
        tools=[fetch_transactions],
        plugins=[plugin],
        builtin_tools=[],
        builtin_plugins=[],
        skills=False,
        memory=False,
        context_manager="auto",
        session=False,
        caching=False,
        callback_handler=None,
    )
    asyncio.run(agent.invoke_async("Export all transactions as CSV."))
    rows = list(csv.DictReader(io.StringIO(save.call_args.args[1])))
    assert len(rows) == 21
    assert [row["transaction_id"] for row in rows] == [
        row["transaction_id"] for row in source
    ]
    assert usage.snapshot()["totals"]["toolCallCount"] == 1
    assert delegate.calls == 3
