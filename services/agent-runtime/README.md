# FroggyBot AgentCore runtime

The runtime uses Strands through the vendored Stan harness declared in `pyproject.toml`. A caller sends validated
conversation history plus one bot configuration. Each request creates a Strands agent with only that
bot's selected tools and skills.

Only `runtime/` is copied into the AgentCore CodeZip. Dependency resolution deliberately walks up to the
parent `pyproject.toml`; the packaged distribution manifest is then checked against `uv.lock`. Tests,
evaluation outputs, scripts, caches, and the vendored wheel cannot enter the deployment archive.

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
- `task_list` - Stan todos
- `delegate` - Stan generalist subagent
- `code_interpreter` - persistent AgentCore sandbox
- `browser` - persistent AgentCore browser; the application requires per-turn user approval

Skills and bot definitions are resolved from the current schema-version-3 public catalog. The runtime
does not keep a second hard-coded bot catalog.

## Models

The runtime routes each Strands invocation between two OpenRouter tiers without making a separate classifier call.
Routine requests use GLM 5.3 Flash with low reasoning; coding, technical, and unusually long requests use GLM 5.3 with
high reasoning. Each tier falls back to Bedrock only when OpenRouter cannot begin a response. The API key is stored in
AgentCore Identity as `FrogBot_OpenRouter`; it is never placed in runtime environment variables. Model selection stays
deploy-time configurable through these non-secret values in `agentcore/agentcore.json`:

- `FROGBOT_PRIMARY_MODEL_ID` — routine tier; defaults to `z-ai/glm-5.3-flash`
- `FROGBOT_REASONING_EFFORT` — routine-tier reasoning; defaults to `low`
- `FROGBOT_ADVANCED_MODEL_ID` — coding and complex tier; defaults to `z-ai/glm-5.3`
- `FROGBOT_ADVANCED_REASONING_EFFORT` — advanced-tier reasoning; defaults to `high`
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
trailing tool-use block before invoking Strands. Direct payloads contain at most 100 recent messages. Strands
automatically compacts at 85% of the model context window by summarizing the oldest 30% and preserving at least the
newest 10 messages. AgentCore independently extracts and retrieves preferences, facts, and per-session topic summaries
so older topics remain available after they leave the recent-message window.

Remote MCP connections accept HTTPS public endpoints only. The runtime resolves the hostname when it
validates the catalog binding and again before every request, and it disables HTTP redirects. OAuth
connections are limited to reviewed Gmail read/draft operations; secrets are fetched server-side.

## Verify the package

Run from `services/agent-runtime`:

```bash
uv lock --check
uv run --frozen python scripts/codezip.py source
cd ../..
agentcore package --runtime FrogBot
```

Then verify the produced archive:

```bash
cd services/agent-runtime
uv run --frozen python scripts/codezip.py archive ../../agentcore/FrogBot.zip
```

The archive check fails if required runtime packages are absent, development content is present, or
an installed distribution version is missing from `uv.lock`. To preview generated package cleanup, run
`uv run --frozen python scripts/codezip.py clean`; add `--apply` only when those generated outputs can be
discarded.

## Behavioral evaluations

The source-controlled corpus in `evals/scenarios.json` covers every bot in the current public catalog.
The default matrix runs every scenario against GLM 5.3 and GLM 5.3 Flash at both low and high reasoning, then uses the
Bedrock fallback model as an anonymized assertion-level judge:

```bash
uv run --frozen python -m evals.run_matrix
```

Use repeated `--scenario` or `--variant` flags for targeted regressions. Full JSON evidence and a compact Markdown
comparison are written under `evals/results/`, which is intentionally ignored by Git.
