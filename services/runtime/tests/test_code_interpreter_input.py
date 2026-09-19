from __future__ import annotations

import asyncio
import json

import pytest
from jsonschema import Draft202012Validator

from heytim_runtime.agentcore_adapters import PersistentAgentCoreCodeInterpreter
from heytim_runtime.code_interpreter_input import (
    MAX_ENCODED_CODE_INTERPRETER_INPUT_CHARS,
    CompatibleCodeInterpreterInput,
)


def _invoke(interpreter, value):
    async def run():
        return [
            event
            async for event in interpreter.code_interpreter.stream(
                {
                    "name": "code_interpreter",
                    "toolUseId": "regression",
                    "input": {"code_interpreter_input": value},
                },
                {},
            )
        ]

    return asyncio.run(run())[-1].tool_result


@pytest.fixture
def interpreter(monkeypatch):
    instance = PersistentAgentCoreCodeInterpreter(
        session_name="test",
        region="us-east-1",
    )
    calls = []
    monkeypatch.setattr(instance, "_start", lambda: None)
    monkeypatch.setattr(
        instance,
        "init_session",
        lambda action: calls.append(action)
        or {"status": "success", "content": [{"text": "opened"}]},
    )
    yield instance, calls


@pytest.mark.parametrize("encoded", [False, True])
def test_dispatch_accepts_object_and_one_encoded_object(interpreter, encoded):
    instance, calls = interpreter
    action = {
        "action": {
            "type": "initSession",
            "session_name": "analysis",
            "description": "Analyze data",
        }
    }

    result = _invoke(instance, json.dumps(action) if encoded else action)

    assert result["status"] == "success"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "value",
    [
        "not JSON",
        "[]",
        "null",
        '"double encoded"',
        "{}",
        '{"action":{"type":"executeCode"}}',
        '{"action":{"type":"inventedAction"}}',
        " " * (MAX_ENCODED_CODE_INTERPRETER_INPUT_CHARS + 1),
    ],
)
def test_invalid_inputs_never_execute(interpreter, value):
    instance, calls = interpreter

    result = _invoke(instance, value)

    assert result["status"] == "error"
    assert not calls


def test_model_schema_still_requires_typed_action_object():
    schema = PersistentAgentCoreCodeInterpreter.code_interpreter.tool_spec[
        "inputSchema"
    ]["json"]
    Draft202012Validator.check_schema(schema)
    value = {
        "action": {
            "type": "executeCode",
            "code": "print('ok')",
            "language": "python",
        }
    }
    validator = Draft202012Validator(schema)

    assert validator.is_valid({"code_interpreter_input": value})
    assert not validator.is_valid({"code_interpreter_input": json.dumps(value)})
    assert CompatibleCodeInterpreterInput.model_validate(value).action.code
