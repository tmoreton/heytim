from __future__ import annotations

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands.agent.agent_result import AgentResult
from strands.types.exceptions import MaxTokensReachedException
from strands_harness import create_harness

from heytim_runtime.action_approval import (
    approval_configuration,
    interrupt_session_manager,
    pending_approval,
)
from heytim_runtime.ai_consent import check_ai_consent
from heytim_runtime.configuration import bot_configuration
from heytim_runtime.device_tools import (
    has_device_tools,
    pending_device_call,
    validated_device_resume,
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
    AgentOutputLimitError,
    AgentRunStalledError,
    AgentRunTimeoutError,
    stream_with_token_recovery,
)
from heytim_runtime.telemetry import install_private_tracer
from model.load import load_model
from model.usage import (
    LONG_RUN_CALL_LIMITS,
    PROVIDER_CALL_LIMITS,
    ProviderCallLimitExceeded,
    UsageAccumulator,
)

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
    "I reached HeyTim's provider-call safety limit before I could finish. I kept "
    "the verified progress from this run; send “continue” to resume without "
    "repeating completed external actions."
)
OUTPUT_LIMIT_MESSAGE = (
    "I reached the model's response limit before I could finish. I kept the "
    "verified progress from this run; send “continue” to resume without repeating "
    "completed external actions."
)
OUTPUT_TOKEN_LIMIT_MESSAGE = (
    "I could not finish the response after recovering from repeated output limits. "
    "The task is incomplete; completed external actions should be checked before retrying."
)


def _provider_call_limit_in_chain(error: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(seen) < 8:
        if isinstance(current, ProviderCallLimitExceeded):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


async def run_agent(payload, context):
    await check_ai_consent(payload)
    consent_check = lambda: check_ai_consent(payload)
    memory_context = memory_context_from_payload(payload)
    actor_id = memory_context.actor_id if memory_context else None
    messages = messages_from_payload(payload, actor_id)
    memories = memory_stores(memory_context)
    session_id = getattr(context, "session_id", "unknown")
    provider_quota = payload.get("providerQuota")
    if provider_quota is not None and not isinstance(provider_quota, dict):
        raise ValueError("providerQuota must be an object")
    usage = UsageAccumulator(
        limits=LONG_RUN_CALL_LIMITS
        if payload.get("runtimeJob")
        else PROVIDER_CALL_LIMITS,
        youtube_search_quota=(provider_quota or {}).get("youtubeSearch"),
    )
    config = bot_configuration(
        payload, session_id, actor_id, messages, usage, consent_check=consent_check
    )
    approval = approval_configuration(payload, actor_id)
    device_resume = validated_device_resume(payload.get("deviceResult"))
    if device_resume is not None and payload.get("actionApproval") is not None:
        raise ValueError("Only one interrupted tool call can resume at a time")
    session_manager = (
        approval[1]
        if approval
        else interrupt_session_manager(payload, actor_id)
        if has_device_tools(payload) or payload.get("runtimeJob")
        else None
    )
    log.info(
        "Invoking HeyTim session %s with %d history messages",
        session_id,
        len(messages),
    )

    agent = None
    completed = False
    terminal_error = None
    approval_request = None
    device_request = None
    try:
        model = await load_model(
            usage,
            session_id=memory_context.session_id if memory_context else None,
            model_preference=payload.get("bot", {}).get("modelPreference", "deepseek"),
            reasoning_effort=payload.get("bot", {}).get("reasoningEffort"),
            before_dispatch=consent_check,
        )
        agent = create_harness(
            model=model,
            # Reasoning is configured directly on the pre-built OpenRouter model.
            effort="auto",
            caching=False,
            callback_handler=None,
            instructions=config.instructions,
            tools=config.tools,
            builtin_tools=config.builtin_tools,
            plugins=config.plugins,
            builtin_plugins=config.builtin_plugins,
            # Skills come only from the validated per-bot plugin, never local files.
            skills=False,
            memory={"stores": memories} if memories else False,
            context_manager="auto",
            # Chat history is owned by the application backend. Private turn
            # snapshots below support background slices and interrupted tools.
            session=False,
            **(
                {
                    **({"hooks": [approval[0]]} if approval else {}),
                    "session_manager": session_manager,
                    "agent_id": f"turn-{payload['memory']['eventId']}",
                }
                if session_manager
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
                            "interruptId": device_resume["id"],
                            "response": {
                                key: value
                                for key, value in device_resume.items()
                                if key != "id"
                            },
                        }
                    }
                ]
                if device_resume
                else [
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
                agent,
                prompt,
                logger=log,
                timeout_seconds=budget,
                turn_slice_size=8 if payload.get("runtimeJob") else None,
                checkpoint=(
                    lambda current: session_manager.save_snapshot(
                        current, is_latest=True
                    )
                )
                if session_manager and payload.get("runtimeJob")
                else None,
            ):
                stopped = None
                if isinstance(event, dict):
                    stopped = event.get("result")
                    if stopped is None and "stop" in event:
                        stopped = AgentResult(*event["stop"])
                if isinstance(stopped, AgentResult):
                    proposed = pending_approval(stopped)
                    proposed_device = pending_device_call(stopped)
                    if proposed and proposed_device:
                        raise ValueError("Multiple runtime interrupts are unsupported")
                    if proposed:
                        if not approval or not session_manager:
                            raise ValueError("Approval hook is unavailable")
                        await session_manager.save_snapshot(agent, is_latest=True)
                        approval_request = proposed
                    elif proposed_device:
                        if not session_manager:
                            raise ValueError("Device interrupt storage is unavailable")
                        await session_manager.save_snapshot(agent, is_latest=True)
                        device_request = proposed_device
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
        except AgentOutputLimitError:
            terminal_error = {
                "code": "OUTPUT_LIMIT",
                "message": OUTPUT_LIMIT_MESSAGE,
            }
        except MaxTokensReachedException:
            terminal_error = {
                "code": "OUTPUT_TOKEN_LIMIT",
                "message": OUTPUT_TOKEN_LIMIT_MESSAGE,
            }
        except ProviderCallLimitExceeded:
            terminal_error = {
                "code": "PROVIDER_CALL_LIMIT",
                "message": PROVIDER_CALL_LIMIT_MESSAGE,
            }
        except Exception as error:
            # Strands wraps model exceptions in EventLoopException. Preserve the
            # recoverable provider-limit outcome instead of surfacing a generic
            # background-job failure.
            if not _provider_call_limit_in_chain(error):
                raise
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
            if approval_request or device_request:
                raise ValueError(
                    "Background work cannot be combined with an interrupted tool call"
                )
            control["pendingWork"] = config.background_work.pending
        elif approval_request:
            control["pendingApproval"] = approval_request
        elif device_request:
            control["pendingDeviceCall"] = device_request
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
