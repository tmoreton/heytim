"""Persist a proposed tool call and require one matching human decision."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.session import SnapshotSessionManager
from strands.storage import S3Storage

from .artifacts import artifact_prefix_from_payload
from .memory import memory_context_from_payload

MAX_APPROVAL_INPUT_BYTES = 8_000
APPROVAL_LIFETIME_MINUTES = 15
_ID = re.compile(r"[a-f0-9-]{32,64}\Z")


def _proposal(tool_use: dict) -> dict:
    name = tool_use.get("name")
    arguments = tool_use.get("input")
    tool_use_id = tool_use.get("toolUseId")
    if not isinstance(name, str) or not name or not isinstance(tool_use_id, str):
        raise ValueError("Tool approval identity is invalid")
    encoded = json.dumps(arguments, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_APPROVAL_INPUT_BYTES:
        raise ValueError("Tool input is too large to review for approval")
    digest = hashlib.sha256(
        json.dumps([tool_use_id, name, arguments], sort_keys=True,
                   ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"toolUseId": tool_use_id, "toolName": name, "input": arguments,
            "digest": digest}


class ActionApproval(HookProvider):
    def __init__(self, resume: dict | None = None):
        self.resume = resume
        self.proposal: dict | None = None

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        proposal = _proposal(event.tool_use)
        decision = event.interrupt("frogbot_exact_action", reason=proposal)
        if (
            not isinstance(decision, dict)
            or decision.get("digest") != proposal["digest"]
            or decision.get("toolUseId") != proposal["toolUseId"]
            or not self.resume
            or self.resume.get("digest") != proposal["digest"]
            or self.resume.get("toolUseId") != proposal["toolUseId"]
        ):
            event.cancel_tool = "This tool call was not approved."
            return
        self.resume = None


def approval_configuration(payload: dict, actor_id: str | None) -> tuple[ActionApproval, SnapshotSessionManager] | None:
    selected = payload.get("bot", {}).get("tools", [])
    if not any(isinstance(item, dict) and item.get("risk") == "interactive" for item in selected):
        return None
    if any(isinstance(item, dict) and item.get("runtime", {}).get("kind") == "stan_subagent"
           for item in selected):
        raise ValueError("Interactive tools cannot be delegated to a subagent")
    memory = memory_context_from_payload(payload)
    prefix = artifact_prefix_from_payload(payload, actor_id)
    if not memory or not prefix or not (
        prefix.startswith(f"users/{actor_id}/bots/")
        or (payload.get("group") is not None and prefix.startswith("groups/")
            and memory.scope == "group")
    ):
        raise ValueError("Approval requires an authorized turn")
    event_id = memory.event_id
    if not isinstance(event_id, str) or not _ID.fullmatch(event_id):
        raise ValueError("Approval turn identity is invalid")
    resume = payload.get("actionApproval")
    if resume is not None and (
        not isinstance(resume, dict)
        or set(resume) != {"id", "digest", "toolUseId"}
        or not all(isinstance(value, str) and value for value in resume.values())
    ):
        raise ValueError("Approval response is invalid")
    bucket = os.environ.get("FROGBOT_FILES_BUCKET")
    if not bucket:
        raise ValueError("Approval storage is unavailable")
    storage = S3Storage(bucket, prefix=f"{prefix.replace('/artifacts/', '/approval-state/')}")
    return ActionApproval(resume), SnapshotSessionManager(
        event_id, storage=storage, save_latest_on="trigger"
    )


def pending_approval(result: Any) -> dict | None:
    if getattr(result, "stop_reason", None) != "interrupt":
        return None
    interrupts = getattr(result, "interrupts", None) or []
    if len(interrupts) != 1 or interrupts[0].name != "frogbot_exact_action":
        raise ValueError("Unexpected runtime interrupt")
    proposal = interrupts[0].reason
    if not isinstance(proposal, dict) or proposal != _proposal({
        "toolUseId": proposal.get("toolUseId"),
        "name": proposal.get("toolName"), "input": proposal.get("input"),
    }):
        raise ValueError("Approval proposal is invalid")
    return {**proposal, "id": interrupts[0].id,
            "expiresAt": (datetime.now(UTC) + timedelta(minutes=APPROVAL_LIFETIME_MINUTES)).isoformat(timespec="seconds")}
