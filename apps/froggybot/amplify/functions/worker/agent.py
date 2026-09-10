from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from shared.agent_stream import AgentTerminalError, ProgressCallback, read_agent_stream
from shared.catalog import CatalogError
from shared.group_chat import (
    MAX_HISTORY_BLOCK_CHARS,
    group_history_from_items,
    group_runtime_context,
)
from shared.memory_identity import direct_session_id, memory_actor_id, scoped_session_id
from shared.time import utc_now_iso

from .artifacts import (
    _attachment_blocks,
    _generated_artifact_prefix,
    _group_attachment_blocks,
)
from .runtime_jobs import queue_runtime_poll, runtime_work
from .support import (
    AGENT_RUNTIME_ARN,
    AGENT_RUNTIME_QUALIFIER,
    _bot_key,
    _group_pk,
    _turn_pk,
    agentcore,
    catalog,
    table,
)
from .work import _pause_work, _restore_paused_work

logger = logging.getLogger(__name__)
RECENT_DIRECT_TURNS = 50
MAX_TEAM_BOTS = 24


def agent_failure_message(error: Exception) -> str:
    if "Runtime initialization time exceeded" in str(error):
        return (
            "FroggyBot could not start its worker after repeated attempts. No agent "
            "work began and no external actions were taken. Please try again."
        )
    return "I could not finish that request. Please try again."


@dataclass(frozen=True)
class AgentInvocationResult:
    text: str
    pending_work: list[dict] = field(default_factory=list)
    bot_mutations: list[dict] = field(default_factory=list)
    usage: dict | None = None
    terminal_error: str | None = None
    usage_event_id: str | None = None


def _continuation_payload(value: list[dict] | None) -> list[dict]:
    if not value:
        return []
    results = []
    for raw in value:
        result = dict(raw)
        exit_code = result.get("exitCode")
        if isinstance(exit_code, Decimal):
            if exit_code != exit_code.to_integral_value():
                raise ValueError("Background task exit code is invalid")
            result["exitCode"] = int(exit_code)
        results.append(result)
    return results


def _get_history(
    user_id: str, bot_id: str, current_event_id: str | None = None
) -> list[dict]:
    turns = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": _turn_pk(user_id, bot_id),
            ":prefix": "TURN#",
        },
        ScanIndexForward=False,
        Limit=RECENT_DIRECT_TURNS,
    ).get("Items", [])
    messages = []
    for turn in reversed(turns):
        if turn.get("userText"):
            content = [{"text": turn["userText"]}]
            if turn.get("id") == current_event_id:
                content.extend(_attachment_blocks(turn, user_id))
            messages.append({"role": "user", "content": content})
        if turn.get("assistantText") and turn.get("status") == "COMPLETE":
            messages.append(
                {"role": "assistant", "content": [
                    {"text": turn["assistantText"][index:index + MAX_HISTORY_BLOCK_CHARS]}
                    for index in range(0, len(turn["assistantText"]), MAX_HISTORY_BLOCK_CHARS)
                    if turn["assistantText"][index:index + MAX_HISTORY_BLOCK_CHARS].strip()
                ]}
            )
        elif turn.get("status") in {"CANCELLED", "ERROR"} and turn.get("activity"):
            progress = "\n".join(str(step)[:600] for step in turn["activity"][-12:])
            messages.append({"role": "assistant", "content": [{"text": (
                "The previous run was interrupted. These are observations, not proof of completion. "
                "Verify repository state and other external actions before repeating them.\n" + progress
            )}]})
    return messages


def _get_group_history(
    group_id: str, bot_id: str, current_message_id: str | None = None
) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={":pk": _group_pk(group_id), ":prefix": "MESSAGE#"},
        ScanIndexForward=False,
        Limit=40,
        ConsistentRead=True,
    ).get("Items", [])
    history = group_history_from_items(items, bot_id)
    if current_message_id:
        message = next(
            (item for item in items if item.get("id") == current_message_id), None
        )
        if message and history and history[-1].get("role") == "user":
            history[-1]["content"].extend(
                _group_attachment_blocks(message, group_id)
            )
    return history


def _get_group_context(
    group_id: str,
    bot_id: str,
    round_position: int,
    round_size: int,
    round_role: str,
    coordinator_bot_id: str | None,
) -> dict:
    meta = table.get_item(
        Key={"pk": _group_pk(group_id), "sk": "META"}, ConsistentRead=True
    ).get("Item")
    if not meta:
        raise ValueError("Group no longer exists")
    items = [meta]
    for prefix in ("BOT#", "USER#", "DECISION#"):
        items.extend(
            table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={
                    ":pk": _group_pk(group_id),
                    ":prefix": prefix,
                },
                ConsistentRead=True,
            ).get("Items", [])
        )
    return group_runtime_context(
        meta,
        items,
        bot_id,
        round_position,
        round_size,
        round_role,
        coordinator_bot_id,
    )


def _team_roster(user_id: str, current_bot_id: str) -> list[dict]:
    items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": _bot_key(user_id, current_bot_id)["pk"],
            ":prefix": "BOT#",
        },
        ConsistentRead=True,
    ).get("Items", [])
    roster = []
    for item in items:
        name = item.get("name")
        tagline = item.get("tagline", "")
        roster_bot_id = item.get("id")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(tagline, str)
            or not isinstance(roster_bot_id, str)
        ):
            continue
        roster.append(
            {
                "name": name.strip()[:60],
                "tagline": tagline.strip()[:120],
                "isCurrent": roster_bot_id == current_bot_id,
            }
        )
    return sorted(
        roster,
        key=lambda item: (not item["isCurrent"], item["name"].casefold()),
    )[:MAX_TEAM_BOTS]


def _bot_management_context(user_id: str) -> dict:
    bot_items = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"USER#{user_id}",
            ":prefix": "BOT#",
        },
        ConsistentRead=True,
    ).get("Items", [])
    bots = []
    for item in bot_items[:MAX_TEAM_BOTS]:
        if not isinstance(item.get("id"), str) or not isinstance(
            item.get("name"), str
        ):
            continue
        bots.append(
            {
                key: item[key]
                for key in (
                    "id",
                    "name",
                    "tagline",
                    "prompt",
                    "color",
                    "toolIds",
                    "skillIds",
                    "systemRole",
                )
                if key in item
            }
        )

    def concise(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
        return [
            {key: item[key] for key in keys if key in item}
            for item in items
            if isinstance(item, dict)
        ]

    return {
        "bots": bots,
        "templates": concise(
            catalog.list_bot_templates(user_id),
            ("id", "name", "tagline", "category", "color", "toolIds", "skillIds"),
        ),
        "tools": concise(
            catalog.list_tools(user_id),
            ("id", "name", "description", "category"),
        ),
        "skills": concise(
            catalog.list_skills(user_id),
            ("id", "name", "description", "category", "requiredToolIds"),
        ),
    }


def _invoke(
    user_id: str,
    bot_id: str,
    bot: dict,
    *,
    history: list[dict] | None = None,
    session_scope: str | None = None,
    event_id: str | None = None,
    artifact_prefix: str | None = None,
    attachment_prefix: str | None = None,
    group_context: dict | None = None,
    memory: dict | None = None,
    continuation: list[dict] | None = None,
    on_progress: ProgressCallback | None = None,
    runtime_result: dict | None = None,
    work_key: dict | None = None,
    lease_owner: str | None = None,
    resume_request: dict | None = None,
    allow_bot_management: bool = False,
) -> AgentInvocationResult:
    if runtime_result is not None:
        error = runtime_result.get("terminalError", {}).get("message")
        return AgentInvocationResult(
            text=runtime_result.get("text", ""),
            pending_work=runtime_result.get("pendingWork", []),
            bot_mutations=runtime_result.get("botMutations", []),
            usage=runtime_result.get("usage"), terminal_error=error,
            usage_event_id=runtime_result.get("usageEventId"),
        )
    session_id = (
        scoped_session_id(session_scope)
        if session_scope is not None
        else direct_session_id(user_id, bot_id)
    )
    skill_versions = bot.get("skillVersions")
    if not isinstance(skill_versions, dict):
        skill_versions = catalog.validate_and_pin(user_id, bot.get("skillIds", []))
        table.update_item(
            Key=_bot_key(user_id, bot_id),
            UpdateExpression="SET skillVersions = :versions",
            ExpressionAttributeValues={":versions": skill_versions},
        )
    resolved_skills = catalog.resolve_for_runtime(skill_versions)
    tool_ids = [
        tool_id
        for tool_id in dict.fromkeys(bot.get("toolIds", []))
        if tool_id != "bot_manager"
    ]
    for skill in resolved_skills:
        tool_ids.extend(
            tool_id
            for tool_id in skill.get("requiredToolIds", [])
            if tool_id not in tool_ids
        )
    bot_management = None
    if (
        allow_bot_management
        and group_context is None
        and event_id
        and bot.get("systemRole") == "chief"
    ):
        try:
            catalog.resolve_tools_for_runtime(user_id, ["bot_manager"])
        except CatalogError:
            pass
        else:
            tool_ids.append("bot_manager")
            bot_management = _bot_management_context(user_id)
    resolved_tools = catalog.resolve_tools_for_runtime(user_id, tool_ids)
    payload = {
        "messages": (
            history
            if history is not None
            else _get_history(user_id, bot_id, current_event_id=event_id)
        ),
        "bot": {
            "name": bot["name"],
            "prompt": bot["prompt"],
            **(
                {"systemRole": bot["systemRole"]}
                if isinstance(bot.get("systemRole"), str)
                else {}
            ),
            "toolIds": tool_ids,
            "tools": resolved_tools,
            "skillIds": bot.get("skillIds", []),
            "skills": resolved_skills,
        },
        "team": _team_roster(user_id, bot_id),
    }
    if bot_management is not None:
        payload["botManagement"] = bot_management
    if memory is not None:
        payload["memory"] = memory
    elif group_context is None and event_id:
        payload["memory"] = {
            "actorId": memory_actor_id(user_id),
            "sessionId": session_id,
            "eventId": event_id,
            "scope": "personal",
        }
    if artifact_prefix:
        payload["artifacts"] = {"prefix": artifact_prefix}
    elif group_context is None and event_id:
        payload["artifacts"] = {
            "prefix": _generated_artifact_prefix(user_id, bot_id, event_id)
        }
    if group_context is not None:
        payload["group"] = group_context
    if attachment_prefix is not None:
        payload["attachmentPrefix"] = attachment_prefix
    if group_context is None and event_id and any(
        tool.get("runtime", {}).get("kind") == "agentcore"
        and tool.get("runtime", {}).get("name") == "browser"
        for tool in resolved_tools
    ):
        from shared.browser_sessions import runtime_browser_session

        browser_session = runtime_browser_session(table, agentcore, user_id, bot_id)
        if browser_session:
            payload["browser"] = {
                **browser_session,
                "actorId": memory_actor_id(user_id),
                "botId": bot_id,
            }
    normalized_continuation = _continuation_payload(continuation)
    if normalized_continuation:
        payload["continuation"] = normalized_continuation
    if work_key is not None and lease_owner and resume_request is not None:
        work = runtime_work(payload, normalized_continuation)
        if not _pause_work(work_key, lease_owner, [work]):
            return AgentInvocationResult(text="", pending_work=[work])
        # Queue recovery before dispatch, including lost acknowledgements. The
        # runtime's conditional durable claim prevents replay of side effects.
        queue_runtime_poll(work_key, resume_request)
        try:
            response = agentcore.invoke_agent_runtime(
                agentRuntimeArn=AGENT_RUNTIME_ARN,
                qualifier=AGENT_RUNTIME_QUALIFIER,
                runtimeSessionId=work["sessionId"],
                contentType="application/json",
                accept="text/event-stream",
                payload=json.dumps(payload).encode("utf-8"),
            )
        except Exception:
            # A failed cold start happens after the turn was durably paused. Restore
            # this lease so the SQS attempt can retry instead of waiting for a
            # heartbeat from a runtime job that never started.
            _restore_paused_work(work_key, lease_owner, [work])
            raise
        try:
            # Drain the short acknowledgement so streaming disconnect cannot
            # cancel the handler before it registers its background task.
            response["response"].read(65_536)
        finally:
            response["response"].close()
        return AgentInvocationResult(text="", pending_work=[work])
    response = agentcore.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        qualifier=AGENT_RUNTIME_QUALIFIER,
        runtimeSessionId=session_id,
        contentType="application/json",
        accept="text/event-stream",
        payload=json.dumps(payload).encode("utf-8"),
    )
    pending_work: list[dict] = []
    bot_mutations: list[dict] = []
    usage: dict | None = None

    def capture_control(control: dict) -> None:
        nonlocal usage
        raw_work = control.get("pendingWork")
        if isinstance(raw_work, list):
            pending_work.extend(item for item in raw_work if isinstance(item, dict))
        raw_mutations = control.get("botMutations")
        if isinstance(raw_mutations, list):
            bot_mutations.extend(
                item for item in raw_mutations if isinstance(item, dict)
            )
        raw_usage = control.get("usage")
        if isinstance(raw_usage, dict):
            usage = raw_usage

    try:
        text = read_agent_stream(
            response["response"].iter_lines(),
            on_progress,
            capture_control,
        )
    except AgentTerminalError as exc:
        terminal_error = str(exc)
        return AgentInvocationResult(
            text=terminal_error,
            pending_work=pending_work,
            bot_mutations=bot_mutations,
            usage=usage,
            terminal_error=terminal_error,
        )
    return AgentInvocationResult(
        text=text,
        pending_work=pending_work,
        bot_mutations=bot_mutations,
        usage=usage,
    )


def _progress_updater(item_key: dict, lease_owner: str) -> ProgressCallback:
    def update(progress: list[str]) -> None:
        try:
            table.update_item(
                Key=item_key,
                UpdateExpression=(
                    "SET activity = :activity, activityUpdatedAt = :updated"
                ),
                ConditionExpression="#status = :running AND leaseOwner = :owner",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":activity": progress,
                    ":updated": utc_now_iso(),
                    ":running": "RUNNING",
                    ":owner": lease_owner,
                },
            )
        except Exception:
            logger.exception(
                "Could not publish agent activity for %s", item_key.get("sk", "unknown")
            )

    return update
