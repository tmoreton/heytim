from __future__ import annotations

import asyncio
import json

import pytest
from jsonschema import Draft202012Validator

from heytim_runtime.agentcore_adapters import PersistentAgentCoreBrowser
from heytim_runtime.browser_input import (
    MAX_ENCODED_BROWSER_INPUT_CHARS,
    CompatibleBrowserInput,
)


def _invoke(browser, value):
    async def run():
        return [
            event
            async for event in browser.browser.stream(
                {
                    "name": "browser",
                    "toolUseId": "regression",
                    "input": {"browser_input": value},
                },
                {},
            )
        ]

    return asyncio.run(run())[-1].tool_result


@pytest.fixture
def browser(monkeypatch):
    instance = PersistentAgentCoreBrowser(session_name="test", region="us-east-1")
    calls = []
    monkeypatch.setattr(instance, "_start", lambda: None)
    monkeypatch.setattr(
        instance,
        "init_session",
        lambda action: (
            calls.append(action)
            or {"status": "success", "content": [{"text": "opened"}]}
        ),
    )
    yield instance, calls
    instance._executor.submit(instance._dispose).result(timeout=5)
    instance._executor.shutdown(wait=True)


@pytest.mark.parametrize("encoded", [False, True])
def test_real_tool_dispatch_accepts_browser_object_and_encoded_object(browser, encoded):
    instance, calls = browser
    action = {
        "action": {
            "type": "init_session",
            "session_name": "submission",
            "description": "Inspect form",
        }
    }
    result = _invoke(instance, json.dumps(action) if encoded else action)
    assert result["status"] == "success"
    assert len(calls) == 1
    assert calls[0].session_name == "submission"


@pytest.mark.parametrize(
    "value",
    [
        "not JSON",
        "[]",
        "null",
        '"double encoded"',
        "{}",
        '{"action":{"type":"navigate","session_name":"test"}}',
        '{"action":{"type":"invented_action"}}',
        " " * (MAX_ENCODED_BROWSER_INPUT_CHARS + 1),
    ],
    ids=[
        "malformed",
        "array",
        "null",
        "double-encoded",
        "empty",
        "missing-url",
        "unknown-action",
        "too-large",
    ],
)
def test_invalid_browser_inputs_never_execute(browser, value):
    instance, calls = browser
    result = _invoke(instance, value)
    assert result["status"] == "error"
    assert not calls


def test_model_facing_schema_still_requires_typed_action_object():
    schema = PersistentAgentCoreBrowser.browser.tool_spec["inputSchema"]["json"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    value = {
        "action": {
            "type": "navigate",
            "session_name": "test",
            "url": "https://example.com",
        }
    }
    assert validator.is_valid({"browser_input": value})
    assert not validator.is_valid({"browser_input": json.dumps(value)})
    assert not validator.is_valid({"browser_input": {"action": {"type": "navigate"}}})
    assert (
        CompatibleBrowserInput.model_validate(json.dumps(value)).action.url
        == "https://example.com"
    )
