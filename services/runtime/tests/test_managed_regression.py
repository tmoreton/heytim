from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_managed_regression as managed_regression
from run_managed_regression import (
    EVALUATION_SERVICE_NAME,
    CuratedEvaluationSpanSink,
    agent_invoker,
    completed_assistant_text,
    evaluation_payload,
    runtime_observability,
)


class FakeStream:
    def __init__(self, lines: list[bytes]):
        self.lines = lines
        self.closed = False

    def iter_lines(self):
        return iter(self.lines)

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, stream: FakeStream):
        self.stream = stream
        self.request = None

    def invoke_agent_runtime(self, **kwargs):
        self.request = kwargs
        return {"response": self.stream}


class FakeSpanSink:
    def __init__(self):
        self.recorded = []

    def record(self, session_id: str, prompt: str, response: str):
        self.recorded.append((session_id, prompt, response))


class ResourceAlreadyExistsException(Exception):
    pass


class FakeLogsClient:
    class exceptions:
        ResourceAlreadyExistsException = ResourceAlreadyExistsException

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))

        return call


def _line(event: dict) -> bytes:
    return json.dumps({"data": json.dumps({"event": event})}).encode()


def test_evaluation_payload_resolves_empty_catalog_capabilities() -> None:
    payload = evaluation_payload("Be accurate.")
    assert payload == {
        "prompt": "Be accurate.",
        "bot": {
            "name": "HeyTim Evaluation",
            "prompt": "Be helpful, direct, and honest.",
            "tools": [],
            "skills": [],
        },
    }
    with pytest.raises(TypeError):
        evaluation_payload({"prompt": "unreviewed"})


def test_agent_invoker_sends_the_structured_contract_and_closes_the_stream() -> None:
    stream = FakeStream(
        [
            _line({"messageStart": {"role": "assistant"}}),
            _line({"contentBlockDelta": {"delta": {"text": "Complete."}}}),
            _line({"messageStop": {"stopReason": "end_turn"}}),
        ]
    )
    client = FakeClient(stream)
    sink = FakeSpanSink()
    invoke = agent_invoker(
        client,
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/HeyTim_Test-1234567890",
        sink,
    )

    result = invoke(type("Input", (), {"payload": "Verify this.", "session_id": "session-1"})())

    assert result.agent_output == {"text": "Complete."}
    assert stream.closed is True
    request_payload = json.loads(client.request["payload"])
    assert request_payload["bot"]["tools"] == []
    assert request_payload["bot"]["skills"] == []
    assert client.request["runtimeSessionId"] == "session-1"
    assert sink.recorded == [("session-1", "Verify this.", "Complete.")]


def test_curated_span_sink_emits_supported_content_fields() -> None:
    logs = FakeLogsClient()
    sink = CuratedEvaluationSpanSink(
        logs,
        "/aws/bedrock-agentcore/evaluations/heytim-release-fixtures",
        "HeyTimRelease_1_1",
        "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000",
    )
    sink.record("session-1", "Fixture prompt", "Fixture response")

    put = next(kwargs for name, kwargs in logs.calls if name == "put_log_events")
    span = json.loads(put["logEvents"][0]["message"])
    assert span["scope"]["name"].startswith("opentelemetry.instrumentation.")
    assert span["resource"]["attributes"]["service.name"] == EVALUATION_SERVICE_NAME
    assert span["attributes"]["gen_ai.operation.name"] == "invoke_agent"
    assert span["attributes"]["gen_ai.task.input"] == "Fixture prompt"
    assert span["attributes"]["gen_ai.task.output"] == "Fixture response"
    assert span["attributes"]["session.id"] == "session-1"
    assert any(name == "associate_kms_key" for name, _kwargs in logs.calls)


def test_evaluation_stream_rejects_terminal_or_incomplete_turns() -> None:
    with pytest.raises(RuntimeError):
        completed_assistant_text(
            [_line({"heytimControl": {"terminalError": {"code": "FAILED"}}})]
        )
    with pytest.raises(ValueError):
        completed_assistant_text([_line({"messageStart": {}})])


def test_runtime_observability_is_derived_from_the_exact_runtime_arn() -> None:
    assert runtime_observability(
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/HeyTim_Test-1234567890",
        "us-east-1",
    ) == (
        "HeyTim_Test-1234567890.DEFAULT",
        "/aws/bedrock-agentcore/runtimes/HeyTim_Test-1234567890-DEFAULT",
    )
    with pytest.raises(ValueError):
        runtime_observability(
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/HeyTim_Test-1234567890",
            "us-west-2",
        )


def test_main_redacts_failure_details(monkeypatch, capsys) -> None:
    monkeypatch.setattr(managed_regression, "parse_args", lambda _argv: object())

    def fail(_args):
        raise RuntimeError("https://example.invalid/dataset?X-Amz-Signature=secret")

    monkeypatch.setattr(managed_regression, "run", fail)

    assert managed_regression.main([]) == 1
    stderr = capsys.readouterr().err
    assert stderr == "Managed AgentCore regression failed: RuntimeError\n"
    assert "secret" not in stderr
