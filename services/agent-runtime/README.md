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
bucket. Image tools also receive a bounded list of the five most recent images from that same private bot
conversation, without adding old binary attachments to the model's message history. Both uploads and generated artifacts are bound to the invoking user's hashed identity. When
requested, the runtime can save downloadable text, Markdown, CSV, JSON, HTML, PDF, Word, Excel, and
PowerPoint artifacts. Meme Lord bots can search a private S3-backed catalog of popular Imgflip templates and
overlay captions locally in each template's native text regions; they can also caption a recent user image.
That path does not invoke an image model. A separately selected Image generator tool creates original images with
the configured OpenRouter image model. It can also send the complete composition, exact copy, and selected recent
images in one request, then normalize the resulting YouTube thumbnail to 1280x720. Binary files are rendered inside the runtime, so the language model never has to emit base64 file data. Browser
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
- `meme_lord` - private stored-template search and deterministic local caption rendering
- `image_generator` - OpenRouter image generation plus reference-aware exact 1280x720 thumbnails from recent user images

Skills and bot definitions are resolved from the current schema-version-3 public catalog. The runtime
does not keep a second hard-coded bot catalog.

## Models

Every Strands invocation uses DeepSeek V4.1 Flash on OpenRouter with high reasoning. If DeepSeek fails before returning
any response, the runtime uses GLM 5.3 on OpenRouter. Both models retry bounded transient, provider, or empty responses
before failing. Tool-heavy histories
are summarized once they reach 20% of the model context window. The API key is stored in
AgentCore Identity as `FrogBot_OpenRouter`; it is never placed in runtime environment variables. Model selection stays
deploy-time configurable through these non-secret values in `agentcore/agentcore.json`:

- `FROGBOT_PRIMARY_MODEL_ID` — default for every task; defaults to `deepseek/deepseek-v4.1-flash`
- `FROGBOT_REASONING_EFFORT` — default-model reasoning; defaults to `high`
- `FROGBOT_FALLBACK_MODEL_ID` — used only after a pre-response primary failure; defaults to `z-ai/glm-5.3`
- `FROGBOT_FALLBACK_REASONING_EFFORT` — fallback reasoning; defaults to `high`
- `FROGBOT_OPENROUTER_BASE_URL` — the OpenRouter OpenAI-compatible endpoint
- `FROGBOT_OPENROUTER_CREDENTIAL_PROVIDER` — the AgentCore Identity credential name
- `FROGBOT_OPENROUTER_MAX_ATTEMPTS` — total attempts before a pre-response OpenRouter failure is returned
- `FROGBOT_CONTEXT_COMPRESSION_THRESHOLD` — ratio that triggers tool-pair-safe history summarization
- `FROGBOT_MEME_TEMPLATE_PREFIX` — private S3 prefix containing `catalog.json` and normalized template PNGs
- `FROGBOT_IMAGE_MODEL_ID` — OpenRouter image model; defaults to `openai/gpt-image-2.5-sunburst`
- `FROGBOT_IMAGE_QUALITY` — requested image quality; defaults to `high`
- `FROGBOT_IMAGE_REQUEST_TIMEOUT_SECONDS` — maximum duration of one OpenRouter image request
- `FROGBOT_IMAGE_MAX_ATTEMPTS` — total attempts for retryable OpenRouter image failures

## Meme template catalog

The checked-in sync command copies up to the current top 100 static templates from Imgflip's official free API into
the configured private files bucket. It validates Imgflip hosts and image dimensions, normalizes each source to PNG,
and stores Imgflip's template-specific text regions, alignment, colors, capitalization, rotation, search aliases, and
source attribution. Templates without published placement metadata receive a safe positional fallback. The command
publishes `catalog.json` only after every selected image has uploaded and never deletes older objects.

```bash
uv run --frozen python scripts/sync_meme_templates.py \
  --bucket frogbot-user-files-188757775631-us-east-1 \
  --prefix meme-templates/v1
```

The full Imgflip database is user-generated, changes continuously, and is not mirrored by this project. Add any
other template only after confirming that FroggyBot has the right to store and use it.

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
model-visible attachments only on the latest user message, exposes at most five recent same-chat images only to
image tools, binds every file path to that user's identity, and strips any
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
a separate Bedrock evaluation model as an anonymized assertion-level judge:

```bash
uv run --frozen python -m evals.run_matrix
```

Use repeated `--scenario` or `--variant` flags for targeted regressions. Full JSON evidence and a compact Markdown
comparison are written under `evals/results/`, which is intentionally ignored by Git.

Before a catalog release is published, evaluate its proposed bot and skill definitions directly:

```bash
uv run --frozen python -m evals.run_matrix --catalog /path/to/frogbot-skills/catalog.json
```
