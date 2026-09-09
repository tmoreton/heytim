from __future__ import annotations

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands.agent.conversation_manager import SummarizingConversationManager
from strands_stan import harness_agent

from frogbot_runtime.configuration import bot_configuration
from frogbot_runtime.memory import (
    latest_assistant_text,
    memory_context_from_payload,
    memory_stores,
    message_text,
    record_completed_turn,
)
from frogbot_runtime.request import messages_from_payload
from frogbot_runtime.streaming import AgentRunTimeoutError, stream_with_token_recovery
from frogbot_runtime.telemetry import install_private_tracer
from model.load import load_model
from model.usage import UsageAccumulator

install_private_tracer()
app = BedrockAgentCoreApp()
log = app.logger
TURN_TIMEOUT_MESSAGE = (
    "I stopped this response because it took longer than five minutes. "
    "Please try again with a smaller request; completed external actions should "
    "be verified before repeating them."
)


@app.entrypoint
async def invoke(payload, context):
    memory_context = memory_context_from_payload(payload)
    actor_id = memory_context.actor_id if memory_context else None
    messages = messages_from_payload(payload, actor_id)
    memories = memory_stores(memory_context)
    session_id = getattr(context, "session_id", "unknown")
    config = bot_configuration(payload, session_id, actor_id)
    log.info(
        "Invoking FroggyBot session %s with %d history messages",
        session_id,
        len(messages),
    )

    usage = UsageAccumulator()
    model = await load_model(usage)
    agent = harness_agent(
        model=model,
        web_fetch_model=model,
        caching=False,
        instructions=config.instructions,
        tools=config.tools,
        builtin_tools=config.builtin_tools,
        plugins=config.plugins,
        builtin_plugins=config.builtin_plugins,
        memory=bool(memories),
        memory_store=memories,
        context_management="auto",
        conversation_manager=SummarizingConversationManager(
            summary_ratio=0.3,
            preserve_recent_messages=10,
            proactive_compression={"compression_threshold": 0.85},
        ),
    )
    completed = False
    timed_out = False
    try:
        try:
            async for event in stream_with_token_recovery(agent, messages, logger=log):
                if not isinstance(event, dict) or "event" not in event:
                    continue
                block_start = event["event"].get("contentBlockStart")
                if block_start is not None and not block_start.get("start"):
                    continue
                yield event
        except AgentRunTimeoutError:
            timed_out = True
        control = {}
        usage_report = usage.snapshot()
        if usage_report["models"]:
            control["usage"] = usage_report
        if config.background_work.pending:
            control["pendingWork"] = config.background_work.pending
        elif timed_out:
            control["terminalError"] = {
                "code": "TURN_TIMEOUT",
                "message": TURN_TIMEOUT_MESSAGE,
            }
        else:
            completed = True
        if control:
            yield {"frogbotControl": control}
    finally:
        if completed:
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
        if agent.memory_manager:
            try:
                await agent.memory_manager.flush()
            except Exception:
                log.exception("Could not flush memory work for session %s", session_id)


if __name__ == "__main__":
    app.run()
