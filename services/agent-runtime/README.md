# FroggyBot AgentCore runtime

The runtime uses Strands through the pinned Stan harness in `pyproject.toml`. A caller sends validated
conversation history plus one bot configuration. Each request creates a Strands agent with only that
bot's selected tools and skills.

Conversation history is persisted by the application backend in DynamoDB. AgentCore Memory recalls
user-scoped preferences and facts plus conversation-scoped summaries. The worker supplies stable,
non-PII actor and session identifiers, and completed turns are written with an idempotency token.

The latest user turn may contain reviewed image or document blocks stored in FroggyBot's private S3
bucket. Both uploads and generated artifacts are bound to the invoking user's hashed identity. When
requested, the runtime can save downloadable text, Markdown, CSV, JSON, HTML, PDF, Word, Excel, and
PowerPoint artifacts. It can also generate original PNG images with Stability AI Stable Image Core. Binary files
are rendered inside the runtime, so the language model never has to emit base64 file data. Browser
and code-interpreter sessions use stable conversation names and reconnect after a runtime restart.

## Supported capabilities

Tools:

- `web` - Stan's summarized web fetcher
- `web_search` - AgentCore Gateway web search
- `calculator` - restricted arithmetic evaluation
- `current_time` - IANA timezone lookup
- `x_search` and `youtube_search` - reviewed gateway targets when credentials are configured
- `task_list` - Stan todos
- `delegate` - Stan generalist subagent
- `code_interpreter` - persistent AgentCore sandbox
- `browser` - persistent AgentCore browser; the application requires per-turn user approval

Skills:

- `trip-planner`
- `event-planner`
- `group-decision`
- `shared-budget`
- `deep-research`
- `data-analyst`

## Models

The runtime uses OpenRouter first and Bedrock only when OpenRouter cannot begin a response. The API key is stored in
AgentCore Identity as `FrogBot_OpenRouter`; it is never placed in runtime environment variables. Model selection stays
deploy-time configurable through these non-secret values in `agentcore/agentcore.json`:

- `FROGBOT_PRIMARY_MODEL_ID` — defaults to `z-ai/glm-5.3-flash`
- `FROGBOT_FALLBACK_MODEL_ID` — the Bedrock model used if the primary provider is unavailable
- `FROGBOT_OPENROUTER_BASE_URL` — the OpenRouter OpenAI-compatible endpoint
- `FROGBOT_OPENROUTER_CREDENTIAL_PROVIDER` — the AgentCore Identity credential name

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

The production worker sends structured invocation payloads containing `messages`, `bot`, and, for
direct turns, trusted `memory` and `artifacts` envelopes. The runtime validates every field, permits
attachments only on the latest user message, binds file paths to that user's identity, and strips any
trailing tool-use block before invoking Strands.
