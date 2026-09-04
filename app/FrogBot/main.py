from __future__ import annotations

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands_stan import harness_agent

from frogbot_runtime.configuration import bot_configuration
from frogbot_runtime.request import messages_from_payload
from model.load import load_model

app = BedrockAgentCoreApp()
log = app.logger


@app.entrypoint
async def invoke(payload, context):
    messages = messages_from_payload(payload)
    session_id = getattr(context, "session_id", "unknown")
    config = bot_configuration(payload, session_id)
    log.info(
        "Invoking FrogBot session %s with %d history messages",
        session_id,
        len(messages),
    )

    agent = harness_agent(
        model=load_model(),
        web_fetch_model="global.anthropic.claude-haiku-4-5-20251001-v1:0",
        caching=False,
        instructions=config.instructions,
        tools=config.tools,
        builtin_tools=config.builtin_tools,
        plugins=config.plugins,
        builtin_plugins=config.builtin_plugins,
        builtin_subagents=config.builtin_subagents,
        skills_dir=config.skill_paths or None,
        memory=False,
        context_management="auto",
    )
    async for event in agent.stream_async(messages):
        if not isinstance(event, dict) or "event" not in event:
            continue
        block_start = event["event"].get("contentBlockStart")
        if block_start is not None and not block_start.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()
