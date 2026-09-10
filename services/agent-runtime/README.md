# FroggyBot AgentCore runtime

The runtime uses Strands through the vendored Stan harness declared in `pyproject.toml`. A caller sends validated
conversation history plus one bot configuration. Each request creates a Strands agent with only that
bot's selected tools and skills.

Only `runtime/` is copied into the AgentCore CodeZip. Dependency resolution deliberately walks up to the
parent `pyproject.toml`; the packaged distribution manifest is then checked against `uv.lock`. Tests,
evaluation outputs, scripts, caches, and the vendored wheel cannot enter the deployment archive.

Conversation history is persisted by the application backend in DynamoDB. AgentCore Memory recalls
private user-scoped preferences and facts plus per-bot summaries in direct chats. Group invocations instead
receive an isolated group actor and shared group session, so they recall only group preferences, facts, and summaries.
The worker supplies stable, non-PII identifiers, and completed turns are written with an idempotency token.
FrogBot passes a balanced, recall-only AgentCore store to Stan. Stan owns the Strands `MemoryManager`, injects
the store on each model turn, exposes semantic search, and gives delegated agents a read-only view of the same
scope. Durable writes remain explicit AgentCore events after completed top-level turns.

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

Every Strands invocation uses DeepSeek V4.1 Flash on OpenRouter with high reasoning. If DeepSeek fails before returning
any response, the runtime uses GLM 5.3 on OpenRouter, then Bedrock Claude as an independent final fallback. Both
OpenRouter models retry bounded transient, provider, or empty responses before falling through. Tool-heavy histories
are summarized once they reach 20% of the model context window. The API key is stored in
AgentCore Identity as `FrogBot_OpenRouter`; it is never placed in runtime environment variables. Model selection stays
deploy-time configurable through these non-secret values in `agentcore/agentcore.json`:

- `FROGBOT_PRIMARY_MODEL_ID` — default for every task; defaults to `deepseek/deepseek-v4.1-flash`
- `FROGBOT_REASONING_EFFORT` — default-model reasoning; defaults to `high`
- `FROGBOT_FALLBACK_MODEL_ID` — used only after a pre-response primary failure; defaults to `z-ai/glm-5.3`
- `FROGBOT_FALLBACK_REASONING_EFFORT` — fallback reasoning; defaults to `high`
- `FROGBOT_BEDROCK_FALLBACK_MODEL_ID` — independent final fallback; defaults to Bedrock Claude Sonnet 4.5
- `FROGBOT_OPENROUTER_BASE_URL` — the OpenRouter OpenAI-compatible endpoint
- `FROGBOT_OPENROUTER_CREDENTIAL_PROVIDER` — the AgentCore Identity credential name
- `FROGBOT_OPENROUTER_MAX_ATTEMPTS` — total attempts before a pre-response OpenRouter failure is returned
- `FROGBOT_CONTEXT_COMPRESSION_THRESHOLD` — ratio that triggers tool-pair-safe history summarization

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
direct and group turns, trusted `memory` and `artifacts` envelopes. The runtime validates every field, permits
attachments only on the latest user message, binds file paths to that user's identity, and strips any
trailing tool-use block before invoking Strands. Direct payloads contain at most 100 recent messages. Strands
automatically compacts at 85% of the model context window by summarizing the oldest 30% and preserving at least the
newest 10 messages. Direct AgentCore scopes retrieve preferences, facts, and per-bot topic summaries. Group scopes
retrieve group preferences, facts, and group-wide topic summaries without reading any member's private actor namespace. Balanced
retrieval prevents one category from consuming the full injection limit before the other categories are considered.

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
