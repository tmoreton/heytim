from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from strands import tool

MAX_BACKGROUND_COMMAND_CHARS = 20_000
MAX_BACKGROUND_LABEL_CHARS = 120
MAX_BACKGROUND_TASKS = 3


def _structured_result(response: dict) -> dict:
    stream = response.get("stream")
    if stream is None:
        return response
    for event in stream:
        result = event.get("result") if isinstance(event, dict) else None
        if not isinstance(result, dict):
            continue
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content")
        if isinstance(content, dict):
            return content
    raise RuntimeError("AgentCore did not return a background task")


@dataclass
class BackgroundWorkTracker:
    pending: list[dict[str, str]] = field(default_factory=list)

    def add(
        self, *, resource_id: str, session_id: str, task_id: str, label: str
    ) -> None:
        if len(self.pending) >= MAX_BACKGROUND_TASKS:
            raise ValueError(
                "This turn already started the maximum number of background tasks"
            )
        self.pending.append(
            {
                "provider": "agentcore_code_interpreter",
                "resourceId": resource_id,
                "sessionId": session_id,
                "taskId": task_id,
                "label": label,
                "startedAt": datetime.now(UTC).isoformat(timespec="milliseconds"),
            }
        )


def start_background_command(
    interpreter: Any,
    tracker: BackgroundWorkTracker,
    command: str,
    label: str,
) -> dict[str, Any]:
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    if len(command) > MAX_BACKGROUND_COMMAND_CHARS:
        raise ValueError(
            f"command must be at most {MAX_BACKGROUND_COMMAND_CHARS} characters"
        )
    if not isinstance(label, str) or not label.strip():
        raise ValueError("label must be a non-empty string")
    clean_label = " ".join(label.split())[:MAX_BACKGROUND_LABEL_CHARS]

    session_name, error = interpreter._ensure_session(None)
    if error:
        return error
    session = interpreter._sessions[session_name]
    result = _structured_result(
        session.client.invoke("startCommandExecution", {"command": command.strip()})
    )
    task_id = result.get("taskId")
    task_status = result.get("taskStatus")
    resource_id = session.client.identifier
    if not all(
        isinstance(value, str) and value
        for value in (task_id, task_status, resource_id, session.session_id)
    ):
        raise RuntimeError("AgentCore returned an invalid background task")
    tracker.add(
        resource_id=resource_id,
        session_id=session.session_id,
        task_id=task_id,
        label=clean_label,
    )
    return {
        "status": "success",
        "content": [
            {
                "text": (
                    f"Started background work: {clean_label}. End this response "
                    "now; FroggyBot will resume automatically when it finishes."
                )
            }
        ],
    }


def background_command_tool(interpreter: Any, tracker: BackgroundWorkTracker):
    @tool
    def background_command(command: str, label: str) -> dict[str, Any]:
        """Run a long shell command asynchronously in the persistent secure sandbox.

        Use this instead of synchronous code execution when a build, test suite, or
        other command may take more than a couple of minutes. After it starts, call no
        more tools and end the response. The platform resumes this conversation when
        the command finishes.
        """
        return start_background_command(interpreter, tracker, command, label)

    return background_command
