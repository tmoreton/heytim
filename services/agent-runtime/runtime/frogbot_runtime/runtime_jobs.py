from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from threading import Thread
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .artifacts import FILES_BUCKET_NAME, artifact_prefix_from_payload
from .memory import memory_context_from_payload
from .streaming import AGENT_RUN_TIMEOUT_SECONDS

log = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 10
MAX_TEXT_CHARS = 60_000


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _runtime_failure_message(error: Exception) -> str:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(chain) < 8:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    detail = " ".join(str(item) for item in chain)
    type_names = {type(item).__name__ for item in chain}
    if "in_flight_budget_exhausted" in detail:
        return (
            "OpenRouter remained at its temporary in-flight budget after retrying. "
            "Saved progress is available; wait a few minutes, then continue."
        )
    if "IncompleteOpenRouterResponseError" in type_names:
        return (
            "OpenRouter returned no completed answer after retrying. Saved progress "
            "is available; continue to resume from the last verified step."
        )
    status_codes = {getattr(item, "status_code", None) for item in chain}
    if "OpenRouterCredentialError" in type_names or status_codes.intersection(
        {401, 403}
    ):
        return (
            "OpenRouter authentication is unavailable. No completion was recorded; "
            "please try again after the service connection is restored."
        )
    if "OpenRouter" in detail or any(name.startswith("API") for name in type_names):
        return (
            "OpenRouter could not complete the model response after retrying. Saved "
            "progress is available; continue to resume from the last verified step."
        )
    return (
        "The agent encountered an unexpected runtime error. Its saved progress is "
        "available; verify completed external actions before continuing."
    )


class RunState:
    """Bounded, public progress and final output; never persist tool arguments."""

    def __init__(self, started_at: str):
        self.value: dict[str, Any] = {
            "status": "RUNNING",
            "startedAt": started_at,
            "heartbeatAt": _now(),
            "progress": [],
            "text": "",
            "pendingWork": [],
        }
        self.chunks = ""
        self.tool = ""

    def observe(self, value: dict) -> None:
        event = value.get("event", value)
        control = event.get("frogbotControl")
        if isinstance(control, dict):
            for key in ("usage", "pendingWork", "terminalError", "botMutations"):
                if key in control:
                    self.value[key] = control[key]
            return
        if "messageStart" in event:
            self.chunks, self.tool = "", ""
        start = event.get("contentBlockStart", {}).get("start", {})
        if "toolUse" in start:
            self.tool = start["toolUse"].get("name", "")
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if isinstance(delta.get("text"), str):
            if len(self.chunks) + len(delta["text"]) > MAX_TEXT_CHARS:
                raise ValueError("Agent answer exceeded the inline response size limit")
            self.chunks = (self.chunks + delta["text"])[-MAX_TEXT_CHARS:]
        reason = event.get("messageStop", {}).get("stopReason")
        if reason == "tool_use":
            step = " ".join(self.chunks.split())[:600]
            if not step and self.tool:
                step = f"Using {self.tool.replace('_', ' ').replace('-', ' ')}"[:600]
            progress = self.value["progress"]
            if step and (not progress or progress[-1] != step):
                self.value["progress"] = (progress + [step])[-12:]
        elif reason == "end_turn":
            self.value["text"] = self.chunks.strip()

    def finish(self) -> None:
        if (
            not self.value.get("terminalError")
            and not self.value["text"]
            and not self.value["pendingWork"]
        ):
            self.fail(
                "The agent stopped without a completed answer. Verify completed external actions before continuing."
            )
        self.value["status"] = (
            "ERROR" if self.value.get("terminalError") else "COMPLETE"
        )

    def fail(self, message: str) -> None:
        self.value["status"] = "ERROR"
        self.value["terminalError"] = {"code": "RUNTIME_JOB_FAILED", "message": message}


def _job_key(payload: dict, session_id: str) -> str:
    memory = memory_context_from_payload(payload)
    prefix = artifact_prefix_from_payload(payload, memory.actor_id if memory else None)
    job = payload.get("runtimeJob")
    if not prefix or not isinstance(job, dict):
        raise ValueError("runtimeJob requires an authorized artifact scope")
    job_id = job.get("id")
    if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{64}", job_id):
        raise ValueError("runtimeJob.id is invalid")
    key = f"{prefix.replace('/artifacts/', '/runs/')}/{job_id}/state.json"
    if session_id != hashlib.sha256(key.encode()).hexdigest():
        raise ValueError("runtimeJob does not match the invoking session")
    return key


def _cancelled(client: Any, key: str) -> bool:
    with client.get_object(Bucket=FILES_BUCKET_NAME, Key=f"{key}.cancel")[
        "Body"
    ] as body:
        return json.loads(body.read(1024)).get("cancelled") is True


async def _execute(client, key, state, runner, payload, context) -> None:
    async def consume():
        # Include model/tool setup and memory flushing in the total budget.
        async with asyncio.timeout(max(30, AGENT_RUN_TIMEOUT_SECONDS - 60)):
            async for event in runner(payload, context):
                if isinstance(event, dict):
                    state.observe(event)

    def save():
        state.value["heartbeatAt"] = _now()
        client.put_object(
            Bucket=FILES_BUCKET_NAME,
            Key=key,
            Body=json.dumps(state.value).encode(),
            ContentType="application/json",
        )

    # The agent and heartbeat live off the HTTP server's event loop. Blocking tool
    # setup cannot freeze AgentCore's health endpoint.
    if await asyncio.to_thread(_cancelled, client, key):
        state.fail("Stopped by you.")
        await asyncio.to_thread(save)
        return
    task = asyncio.create_task(consume())
    try:
        while not task.done():
            if await asyncio.to_thread(_cancelled, client, key):
                task.cancel()
                state.fail("Stopped by you.")
                break
            await asyncio.to_thread(save)
            await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
        if not state.value.get("terminalError"):
            await task
    except Exception as error:
        log.exception("Background agent job failed")
        state.fail(_runtime_failure_message(error))
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        state.finish()
        await asyncio.to_thread(save)


async def start_runtime_job(app, payload, context, runner) -> dict:
    key = _job_key(payload, context.session_id)
    client = boto3.client(
        "s3",
        config=Config(
            connect_timeout=3,
            read_timeout=10,
            retries={"total_max_attempts": 3, "mode": "standard"},
        ),
    )
    state = RunState(_now())
    try:
        # Initialize without overwriting a Stop that raced with startup.
        await asyncio.to_thread(
            client.put_object,
            Bucket=FILES_BUCKET_NAME,
            Key=f"{key}.cancel",
            Body=b'{"cancelled":false}',
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"PreconditionFailed", "412"}:
            raise
    try:
        # A durable claim is never stolen or replayed, even after a process crash.
        await asyncio.to_thread(
            client.put_object,
            Bucket=FILES_BUCKET_NAME,
            Key=key,
            Body=json.dumps(state.value).encode(),
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"PreconditionFailed", "412"}:
            raise
        return {"frogbotControl": {"runtimeJobAccepted": True}}
    task_id = app.add_async_task("agent_run")

    def work():
        try:
            asyncio.run(_execute(client, key, state, runner, payload, context))
        except Exception:
            log.exception(
                "Could not save background agent outcome; worker will detect stale heartbeat"
            )
        finally:
            app.complete_async_task(task_id)

    copied_context = contextvars.copy_context()
    try:
        Thread(target=copied_context.run, args=(work,), daemon=True).start()
    except Exception:
        app.complete_async_task(task_id)
        raise
    return {"frogbotControl": {"runtimeJobAccepted": True}}
