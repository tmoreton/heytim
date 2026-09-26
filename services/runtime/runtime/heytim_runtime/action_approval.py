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
from .mcp_tool_names import _bounded_tool_name
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
    def __init__(
        self, resume: dict | None = None,
        read_only_home_tools: set[str] | None = None,
        allow_after_resume: bool = False,
        interactive_names: set[str] | None = None,
        interactive_prefixes: set[str] | None = None,
    ):
        self.resume = resume
        self.proposal: dict | None = None
        self.read_only_home_tools = frozenset(read_only_home_tools or ())
        self.allow_after_resume = allow_after_resume
        self.interactive_names = frozenset(interactive_names or ())
        self.interactive_prefixes = frozenset(interactive_prefixes or ())

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        if self.allow_after_resume and self.resume is None:
            return
        name = event.tool_use.get("name")
        if self.resume is None and (
            self.interactive_names or self.interactive_prefixes
        ) and name not in self.interactive_names and not any(
            isinstance(name, str) and name.startswith(prefix)
            for prefix in self.interactive_prefixes
        ):
            return
        # A connection's interactive risk applies to device changes, not a
        # zero-argument Assist context read. Match the exact alias derived from
        # this bot's validated Home Assistant grant; never trust a suffix alone.
        if (
            event.tool_use.get("name") in self.read_only_home_tools
            and event.tool_use.get("input") in ({}, None)
        ):
            return
        proposal = _proposal(event.tool_use)
        decision = event.interrupt("heytim_exact_action", reason=proposal)
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
    interactive_ids = {
        item["id"] for item in selected
        if isinstance(item, dict) and item.get("risk") == "interactive"
        and isinstance(item.get("id"), str)
    }
    if not interactive_ids:
        return None
    if any(isinstance(item, dict) and item.get("runtime", {}).get("kind") == "stan_subagent"
           for item in selected):
        raise ValueError("Interactive tools cannot be delegated to a subagent")
    allowed = payload.get("bot", {}).get("alwaysAllowedToolIds", [])
    allowed_ids = set(allowed) if isinstance(allowed, list) and all(
        isinstance(item, str) for item in allowed
    ) else set()
    unapproved_ids = interactive_ids - allowed_ids
    resume = payload.get("actionApproval")
    if not unapproved_ids and resume is None:
        return None
    if resume is not None and (
        not isinstance(resume, dict)
        or set(resume) != {"id", "digest", "toolUseId"}
        or not all(isinstance(value, str) and value for value in resume.values())
    ):
        raise ValueError("Approval response is invalid")
    read_only_home_tools = {
        _bounded_tool_name(item["id"], "homeassistant__GetLiveContext")
        for item in selected
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item.get("risk") == "interactive"
        and isinstance(item.get("runtime"), dict)
        and item["runtime"].get("kind") == "mcp"
        and item["runtime"].get("authType") == "home_assistant_token"
    }
    interactive_names: set[str] = set()
    interactive_prefixes: set[str] = set()
    for item in selected:
        if not isinstance(item, dict) or item.get("id") not in unapproved_ids:
            continue
        runtime = item.get("runtime", {})
        kind = runtime.get("kind") if isinstance(runtime, dict) else None
        if kind in {"mcp", "mcp_bundle", "provider_api"}:
            interactive_prefixes.add(
                f"c{hashlib.sha256(item['id'].encode()).hexdigest()[:10]}_"
            )
        elif kind == "agentcore" and runtime.get("name") == "browser":
            interactive_names.update({"browser", "capture_points_screenshot"})
        elif kind == "local" and runtime.get("name") == "image_generator":
            interactive_names.update({"generate_image", "create_youtube_thumbnail"})
        elif kind == "device":
            interactive_names.update(runtime.get("interactiveOperations", []))
        else:
            # Unknown interactive bindings keep the conservative original hook.
            interactive_names.clear()
            interactive_prefixes.clear()
            break
    return ActionApproval(
        resume, read_only_home_tools,
        allow_after_resume=not unapproved_ids,
        interactive_names=interactive_names,
        interactive_prefixes=interactive_prefixes,
    ), interrupt_session_manager(payload, actor_id)


def interrupt_session_manager(
    payload: dict, actor_id: str | None
) -> SnapshotSessionManager:
    """Return the authorized snapshot store shared by approval and device interrupts."""
    memory = memory_context_from_payload(payload)
    prefix = artifact_prefix_from_payload(payload, actor_id)
    if not memory or not prefix or not (
        prefix.startswith(f"users/{actor_id}/bots/")
        or (
            payload.get("group") is not None
            and prefix.startswith("groups/")
            and memory.scope == "group"
        )
    ):
        raise ValueError("Interrupts require an authorized turn")
    event_id = memory.event_id
    if not isinstance(event_id, str) or not _ID.fullmatch(event_id):
        raise ValueError("Interrupt turn identity is invalid")
    bucket = os.environ.get("HEYTIM_FILES_BUCKET")
    if not bucket:
        raise ValueError("Interrupt storage is unavailable")
    storage = S3Storage(
        bucket,
        prefix=f"{prefix.replace('/artifacts/', '/approval-state/')}",
    )
    return SnapshotSessionManager(event_id, storage=storage, save_latest_on="trigger")


def pending_approval(result: Any) -> dict | None:
    if getattr(result, "stop_reason", None) != "interrupt":
        return None
    interrupts = getattr(result, "interrupts", None) or []
    if len(interrupts) == 1 and interrupts[0].name != "heytim_exact_action":
        return None
    if len(interrupts) != 1:
        raise ValueError("Unexpected runtime interrupt")
    proposal = interrupts[0].reason
    if not isinstance(proposal, dict) or proposal != _proposal({
        "toolUseId": proposal.get("toolUseId"),
        "name": proposal.get("toolName"), "input": proposal.get("input"),
    }):
        raise ValueError("Approval proposal is invalid")
    return {**proposal, "id": interrupts[0].id,
            "expiresAt": (datetime.now(UTC) + timedelta(minutes=APPROVAL_LIFETIME_MINUTES)).isoformat(timespec="seconds")}
