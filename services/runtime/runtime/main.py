from __future__ import annotations

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands.agent.agent_result import AgentResult
from strands_harness import create_harness

from heytim_runtime.action_approval import approval_configuration, pending_approval
from heytim_runtime.configuration import bot_configuration
from heytim_runtime.home_assistant_fast_path import (
    maybe_route_home_assistant,
    read_state_candidate,
)
from heytim_runtime.memory import (
    latest_assistant_text,
    memory_context_from_payload,
    memory_stores,
    message_text,
    record_completed_turn,
)
from heytim_runtime.request import messages_from_payload
from heytim_runtime.runtime_jobs import start_runtime_job
from heytim_runtime.streaming import (
    AGENT_IDLE_TIMEOUT_SECONDS,
    AGENT_RUN_TIMEOUT_SECONDS,
    AgentIncompleteTurnError,
    AgentRunStalledError,
    AgentRunTimeoutError,
    stream_with_token_recovery,
)
from heytim_runtime.telemetry import install_private_tracer
from model.load import load_model
from model.usage import ProviderCallLimitExceeded, UsageAccumulator

install_private_tracer()
app = BedrockAgentCoreApp()
log = app.logger
TURN_TIMEOUT_MESSAGE = (
    f"This run reached its {AGENT_RUN_TIMEOUT_SECONDS // 60}-minute safety limit "
    "before finishing. Send “continue” to resume from the last verified step; "
    "completed external actions will be checked before anything is repeated."
)
TURN_STALLED_MESSAGE = (
    f"I stopped this run because it produced no activity for "
    f"{AGENT_IDLE_TIMEOUT_SECONDS // 60} minutes. No completion was recorded; "
    "send “continue” to resume from the last verified step."
)
INCOMPLETE_TURN_MESSAGE = (
    "I did not mark this request complete because the agent repeatedly ended while "
    "still promising unfinished work. Send “continue” to resume from the last "
    "verified step."
)
PROVIDER_CALL_LIMIT_MESSAGE = (
    "I stopped this run before it could exceed HeyTim's provider-call safety "
    "limit. Start a new, narrower request to continue."
)


async def run_agent(payload, context):
    memory_context = memory_context_from_payload(payload)
    actor_id = memory_context.actor_id if memory_context else None
    messages = messages_from_payload(payload, actor_id)
    resume = payload.get("actionApproval")
    fast_resume = (
        isinstance(resume, dict)
        and isinstance(resume.get("toolUseId"), str)
        and resume["toolUseId"].startswith("ha-fast-")
    )
    if fast_resume and payload.get("homeAssistantHint") is None:
        yield {
            "heytimControl": {
                "terminalError": {
                    "code": "HA_APPROVAL_UNAVAILABLE",
                    "message": "The approved Home Assistant route is missing. No command was sent.",
                }
            }
        }
        return
    request = message_text(messages[-1], "user")
    if (
        payload.get("homeAssistantHint") is not None
        or read_state_candidate(request)
    ) and (resume is None or fast_resume):
        fast_result = None
        if request and len(messages[-1]["content"]) == 1:
            try:
                fast_result = await maybe_route_home_assistant(payload, request)
            except Exception:
                log.exception("Home Assistant quick route unavailable")
        if fast_result is None and fast_resume:
            fast_result = {
                "terminalError": {
                    "code": "HA_APPROVAL_UNAVAILABLE",
                    "message": (
                        "The approved Home Assistant action could not be verified. "
                        "Check the device before trying again; its outcome may be uncertain."
                    ),
                }
            }
        if fast_result is not None:
            if text := fast_result.get("text"):
                yield {"event": {"messageStart": {"role": "assistant"}}}
                yield {"event": {"contentBlockDelta": {"delta": {"text": text}}}}
                yield {"event": {"messageStop": {"stopReason": "end_turn"}}}
                try:
                    await record_completed_turn(memory_context, request, text)
                except Exception:
                    log.exception("Could not persist quick Home Assistant turn")
            else:
                yield {"heytimControl": fast_result}
            return
    memories = memory_stores(memory_context)
    session_id = getattr(context, "session_id", "unknown")
    provider_quota = payload.get("providerQuota")
    if provider_quota is not None and not isinstance(provider_quota, dict):
        raise ValueError("providerQuota must be an object")
    usage = UsageAccumulator(
        youtube_search_quota=(provider_quota or {}).get("youtubeSearch")
    )
    config = bot_configuration(payload, session_id, actor_id, messages, usage)
    approval = approval_configuration(payload, actor_id)
    log.info(
        "Invoking HeyTim session %s with %d history messages",
        session_id,
        len(messages),
    )

    agent = None
    completed = False
    terminal_error = None
    approval_request = None
    try:
        model = await load_model(usage)
        agent = create_harness(
            model=model,
            # Reasoning is configured directly on the pre-built OpenRouter model.
            effort="auto",
            caching=False,
            instructions=config.instructions,
            tools=config.tools,
            builtin_tools=config.builtin_tools,
            plugins=config.plugins,
            builtin_plugins=config.builtin_plugins,
            # Skills come only from the validated per-bot plugin, never local files.
            skills=False,
            memory={"stores": memories} if memories else False,
            context_manager="auto",
            # Chat history is owned by the application backend. The approval
            # snapshot manager below is the only supported session override.
            session=False,
            **(
                {
                    "hooks": [approval[0]],
                    "session_manager": approval[1],
                    "agent_id": f"turn-{payload['memory']['eventId']}",
                }
                if approval
                else {}
            ),
        )
        try:
            # Leave time to save the outcome before AgentCore retires the session.
            budget = (
                max(30, AGENT_RUN_TIMEOUT_SECONDS - 60)
                if payload.get("runtimeJob")
                else min(AGENT_RUN_TIMEOUT_SECONDS, 720)
            )
            resume = payload.get("actionApproval")
            prompt = (
                [
                    {
                        "interruptResponse": {
                            "interruptId": resume["id"],
                            "response": {
                                "digest": resume["digest"],
                                "toolUseId": resume["toolUseId"],
                            },
                        }
                    }
                ]
                if resume
                else messages
            )
            async for event in stream_with_token_recovery(
                agent, prompt, logger=log, timeout_seconds=budget
            ):
                if isinstance(event, dict) and "stop" in event:
                    proposed = pending_approval(AgentResult(*event["stop"]))
                    if proposed:
                        if not approval:
                            raise ValueError("Approval hook is unavailable")
                        await approval[1].save_snapshot(agent, is_latest=True)
                        approval_request = proposed
                if not isinstance(event, dict) or "event" not in event:
                    continue
                block_start = event["event"].get("contentBlockStart")
                if block_start is not None and not block_start.get("start"):
                    continue
                yield event
                if "metadata" in event["event"]:
                    yield {"heytimControl": {"usage": usage.snapshot()}}
        except AgentRunTimeoutError:
            terminal_error = {
                "code": "TURN_TIMEOUT",
                "message": TURN_TIMEOUT_MESSAGE,
            }
        except AgentRunStalledError:
            terminal_error = {
                "code": "TURN_STALLED",
                "message": TURN_STALLED_MESSAGE,
            }
        except AgentIncompleteTurnError:
            terminal_error = {
                "code": "INCOMPLETE_TURN",
                "message": INCOMPLETE_TURN_MESSAGE,
            }
        except ProviderCallLimitExceeded:
            terminal_error = {
                "code": "PROVIDER_CALL_LIMIT",
                "message": PROVIDER_CALL_LIMIT_MESSAGE,
            }
        control = {}
        usage_report = usage.snapshot()
        if (
            usage_report["models"]
            or usage_report["tools"]
            or usage_report["totals"]["modelDispatchCount"]
        ):
            control["usage"] = usage_report
        if config.background_work.pending:
            if approval_request:
                raise ValueError(
                    "Background work cannot be combined with an interrupted tool call"
                )
            control["pendingWork"] = config.background_work.pending
        elif approval_request:
            control["pendingApproval"] = approval_request
        elif terminal_error:
            control["terminalError"] = terminal_error
        else:
            completed = True
        if config.capability_configuration.bot_mutations.pending:
            control["botMutations"] = (
                config.capability_configuration.bot_mutations.pending
            )
        if control:
            yield {"heytimControl": control}
    finally:
        try:
            await config.close()
        except Exception:
            log.exception(
                "Could not release turn capabilities for session %s", session_id
            )
        if completed and agent is not None:
            try:
                await record_completed_turn(
                    memory_context,
                    message_text(messages[-1], "user"),
                    latest_assistant_text(agent.messages),
                )
            except Exception:
                log.exception(
                    "Could not persist long-term memory for session %s", session_id
                )
        if agent is not None and agent.memory_manager:
            try:
                await agent.memory_manager.flush()
            except Exception:
                log.exception("Could not flush memory work for session %s", session_id)


@app.entrypoint
async def invoke(payload, context):
    if isinstance(payload, dict) and payload.get("runtimeJob") is not None:
        yield await start_runtime_job(app, payload, context, run_agent)
        return
    async for event in run_agent(payload, context):
        yield event


if __name__ == "__main__":
    app.run()
