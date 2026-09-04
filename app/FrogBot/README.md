# FrogBot AgentCore runtime

The runtime uses Strands through the pinned Stan harness in `pyproject.toml`. A caller sends validated
text history plus one bot configuration. Each request creates a plain Strands agent with only that
bot's selected tools and skills.

Conversation history is persisted by the application backend in DynamoDB, not in the runtime's local
filesystem. The runtime still receives a stable AgentCore session ID for isolation and observability.

## Supported capabilities

Tools:

- `web` - Stan's summarized web fetcher
- `calculator` - restricted arithmetic evaluation
- `current_time` - IANA timezone lookup

Skills:

- `researcher`
- `writer`
- `planner`

## Develop

```bash
uv sync --locked
cd ../..
agentcore dev
```

In another terminal:

```bash
agentcore invoke --dev 'What can you do?'
```

The production worker sends structured invocation payloads containing `messages` and `bot`. The
runtime validates both and strips any trailing tool-use block before invoking Strands.
