from __future__ import annotations

import asyncio
import hashlib
import io
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.runtime.app import SESSION_HEADER
from botocore.exceptions import ClientError
from starlette.testclient import TestClient

from frogbot_runtime import runtime_jobs as jobs


class Store:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Key, Body, IfNoneMatch=None, **_kwargs):
        if IfNoneMatch and Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Key] = Body

    def get_object(self, *, Key, **_kwargs):
        return {"Body": io.BytesIO(self.objects[Key])}


def identity():
    actor = "a" * 64
    job_id = "b" * 64
    prefix = f"users/{actor}/bots/github/artifacts/12345678-1234-1234-1234-123456789012"
    payload = {
        "memory": {"actorId": actor, "sessionId": "s" * 64, "eventId": "event-1"},
        "artifacts": {"prefix": prefix},
        "runtimeJob": {"id": job_id},
    }
    key = f"{prefix.replace('/artifacts/', '/runs/')}/{job_id}/state.json"
    return (
        payload,
        SimpleNamespace(session_id=hashlib.sha256(key.encode()).hexdigest()),
        key,
    )


def test_job_cannot_write_to_another_actor_or_session():
    payload, context, key = identity()
    assert jobs._job_key(payload, context.session_id) == key
    with pytest.raises(ValueError, match="session"):
        jobs._job_key(payload, "wrong-session")
    payload["memory"]["actorId"] = "c" * 64
    with pytest.raises(ValueError, match="invoking user"):
        jobs._job_key(payload, context.session_id)


def test_duplicate_dispatch_claims_once_and_preserves_cancellation(monkeypatch):
    store = Store()
    payload, context, key = identity()
    store.objects[f"{key}.cancel"] = b'{"cancelled":true}'
    app = MagicMock()
    thread = MagicMock()
    monkeypatch.setattr(jobs.boto3, "client", lambda *_a, **_k: store)
    monkeypatch.setattr(jobs, "Thread", thread)
    for _ in range(2):
        result = asyncio.run(jobs.start_runtime_job(app, payload, context, MagicMock()))
        assert result["frogbotControl"]["runtimeJobAccepted"]
    assert app.add_async_task.call_count == 1
    assert thread.return_value.start.call_count == 1
    assert json.loads(store.objects[f"{key}.cancel"])["cancelled"]


def test_background_execution_saves_progress_and_terminal_output(monkeypatch):
    store = Store()
    store.objects["run.cancel"] = b'{"cancelled":false}'
    state = jobs.RunState(jobs._now())
    monkeypatch.setattr(jobs, "HEARTBEAT_SECONDS", 0.001)

    async def runner(*_args):
        yield {"event": {"messageStart": {}}}
        yield {
            "event": {"contentBlockStart": {"start": {"toolUse": {"name": "get_repo"}}}}
        }
        yield {"event": {"messageStop": {"stopReason": "tool_use"}}}
        await asyncio.sleep(0.01)
        yield {"event": {"messageStart": {}}}
        yield {"event": {"contentBlockDelta": {"delta": {"text": "Verified PR #12."}}}}
        yield {"event": {"messageStop": {"stopReason": "end_turn"}}}
        yield {"frogbotControl": {"usage": {"models": [{"modelId": "test"}]}}}

    asyncio.run(jobs._execute(store, "run", state, runner, {}, None))
    saved = json.loads(store.objects["run"])
    assert saved["status"] == "COMPLETE"
    assert saved["progress"] == ["Using get repo"]
    assert saved["text"] == "Verified PR #12."
    assert saved["usage"]["models"][0]["modelId"] == "test"


@pytest.mark.parametrize("failure", ["terminal", "exception", "empty"])
def test_background_failures_never_become_false_completion(failure):
    store = Store()
    store.objects["run.cancel"] = b'{"cancelled":false}'
    state = jobs.RunState(jobs._now())

    async def runner(*_args):
        if failure == "exception":
            raise RuntimeError("tool failed")
        if failure == "terminal":
            yield {
                "frogbotControl": {
                    "terminalError": {"code": "TURN_TIMEOUT", "message": "limit"}
                }
            }

    asyncio.run(jobs._execute(store, "run", state, runner, {}, None))
    assert json.loads(store.objects["run"])["status"] == "ERROR"


def test_openrouter_budget_failure_is_actionable():
    message = jobs._runtime_failure_message(
        RuntimeError("in_flight_budget_exhausted")
    )

    assert "OpenRouter" in message
    assert "wait a few minutes" in message


def test_wrapped_openrouter_auth_failure_is_actionable():
    class OpenRouterCredentialError(RuntimeError):
        pass

    wrapped = RuntimeError("event loop failed")
    wrapped.__cause__ = OpenRouterCredentialError("credential lookup failed")

    message = jobs._runtime_failure_message(wrapped)

    assert "OpenRouter authentication" in message


def test_cancellation_before_start_never_calls_agent():
    store = Store()
    store.objects["run.cancel"] = b'{"cancelled":true}'
    runner = MagicMock()
    asyncio.run(
        jobs._execute(store, "run", jobs.RunState(jobs._now()), runner, {}, None)
    )
    runner.assert_not_called()
    assert json.loads(store.objects["run"])["status"] == "ERROR"


def test_http_response_ends_while_sdk_keeps_background_agent_busy(monkeypatch):
    store = Store()
    payload, context, key = identity()
    app = BedrockAgentCoreApp()
    released, finished = Event(), Event()
    monkeypatch.setattr(jobs.boto3, "client", lambda *_a, **_k: store)
    monkeypatch.setattr(jobs, "HEARTBEAT_SECONDS", 0.01)
    complete = app.complete_async_task

    def mark_complete(task_id):
        complete(task_id)
        finished.set()

    monkeypatch.setattr(app, "complete_async_task", mark_complete)

    async def runner(*_args):
        await asyncio.to_thread(released.wait, 5)
        yield {"event": {"messageStart": {}}}
        yield {
            "event": {
                "contentBlockDelta": {"delta": {"text": "Complete after disconnect"}}
            }
        }
        yield {"event": {"messageStop": {"stopReason": "end_turn"}}}

    @app.entrypoint
    async def invoke(payload, context):
        yield await jobs.start_runtime_job(app, payload, context, runner)

    with TestClient(app) as client:
        try:
            response = client.post(
                "/invocations",
                json=payload,
                headers={SESSION_HEADER: context.session_id},
            )
            assert response.status_code == 200
            assert "runtimeJobAccepted" in response.text
            assert not released.is_set()
            assert client.get("/ping").json()["status"] == "HealthyBusy"
        finally:
            released.set()
        assert finished.wait(5)
        assert client.get("/ping").json()["status"] == "Healthy"
    assert json.loads(store.objects[key])["text"] == "Complete after disconnect"
