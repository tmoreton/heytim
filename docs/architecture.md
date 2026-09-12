# FroggyBot architecture

This repository deliberately separates deployment units from reusable client packages:

```text
apps/froggybot/                 Expo view layer and composition root
apps/froggybot-browser-viewer/  Disposable browser viewer application
packages/                       Contracts, clients, preview, and native transcription
services/froggybot-api/         Serverless application backend
services/agent-runtime/         AgentCore runtime shared by every FroggyBot personality
agentcore/                      Declarative AgentCore infrastructure and gateway schemas
```

## Mobile application

`apps/froggybot/src/app` contains Expo Router route shells. `src/features` and `src/components` contain
screens and visual primitives; `src/lib` is limited to composition, cloud configuration, theme values,
and the production-disabled preview switch. A boundary check rejects new non-view TypeScript modules in
the app. Web and iOS use the same view code.

`packages/froggybot-contract` owns shared types and generated routes. `packages/froggybot-client` owns the
headless transport, response validation, reconciliation, policy-derived presentation models, and API domains.
`packages/froggybot-expo-client` owns platform/controller hooks for auth, notifications, links, polling,
attachments, dictation, and mutations. `packages/froggybot-preview` owns one explicit in-memory development
state and API implementation. `packages/frogbot-transcription` owns the reusable Expo/Swift transcription module.
The separately built browser viewer keeps the AgentCore SDK and Cloudscape dependency tree out of Expo.

The backend returns `allowedActions` and input `constraints` in its public models. Views render those values
and fail closed when actions are absent; they do not infer authorization from ownership, roles, or status.

The public website uses `/` for positioning and `/library` for the searchable bot, skill, tool, and action directory.
The directory reads sanitized catalog metadata from `/public/catalog` and falls back to the same reviewed GitHub
source if the API is temporarily unavailable. `/invite` previews a share link before opening the app or sign-up
experience. `/app` hosts the authenticated product. Catalog links use `/app?bot=…` to open the bot library, or
`/app?skill=…` and `/app?tool=…` to preselect a capability in a review-before-save bot editor. Development builds may use
`/app?preview=1` to exercise the complete UI without calling AWS; production builds ignore that
flag.

The app contains no official tool-name or tool-description registry. Its Tools screen renders the sanitized tools in
the current backend catalog snapshot; preview mode parses the same public catalog. User OAuth and legacy connections
are separated by provenance and appear only on the Connections screen. That screen renders the backend's public-safe
connection-provider manifest rather than branching on provider IDs. Browser-specific controls may still test the stable
`browser` capability ID because they implement that capability rather than describe the catalog.

## Application backend

Amplify owns Cognito and the application-facing AWS resources. One HTTP API Lambda keeps deployment
and permissions simple, while focused modules under `services/froggybot-api/amplify/functions/api` own each application
domain. The API handler only routes requests. Shared rules live under `services/froggybot-api/amplify/functions/shared`.
The SQS worker uses the same pattern: its handler routes jobs, and focused worker modules claim work,
invoke AgentCore, persist results, and send final-response notifications.

`services/froggybot-api/amplify/functions/api/api-contract.json` is the single authored HTTP route contract. Amplify CDK and the
Python dispatcher load it directly; a checked-in generated TypeScript map in `packages/froggybot-contract` gives clients typed URL construction.
The contract check prevents those consumers from drifting. Expected API failures carry stable codes independently
of their human-readable messages, so clients can choose safe UI behavior without matching English text.

Daily, weekday, weekly, and monthly bot tasks are stored with the user's other application data. Each
task has one EventBridge Scheduler schedule that sends only stable identifiers to the existing SQS
queue. The worker reloads the current task and bot at execution time, creates an idempotent scheduled
chat turn, and then follows the same agent and notification path as a person-started message.
Scheduler retries use the existing dead-letter queue, and schedule names contain hashes rather than
user identifiers. Interactive browser work is intentionally limited to direct chat, where a person
must approve that turn before it is queued.

User uploads and generated artifacts live in a private, versioned S3 bucket. Uploads use short-lived,
size-constrained signed forms and are verified before they become usable. The API issues short-lived
download links only after an ownership check. Account deletion removes every object version and delete
marker under the user's hashed prefix.

The asynchronous request flow is:

```text
person sends message -> API persists pending turn -> SQS job -> worker invokes AgentCore
                     -> worker streams activity to DynamoDB -> worker persists final answer
                     -> final-only push notification -> app refreshes the conversation
```

```text
EventBridge Scheduler -> SQS scheduled job -> worker reloads task + bot -> scheduled chat turn
                      -> AgentCore -> final answer in chat -> final-only push notification
```

Group rounds use one SQS step per bot. Each later bot receives the group roster, owner-editable shared memory,
shared transcript, and completed replies from earlier bots. A group/bot/session tuple provides stable AgentCore
isolation while keeping the group's explicit memory separate from each person's private memory.

Generated group artifacts use a group-scoped S3 prefix and group-owned DynamoDB file records. Downloads require
current membership, so every participant can open the result without exposing it through a public link.

Each completed runtime invocation emits a compact accounting envelope containing model IDs, token counts, and any
provider-reported cost. The worker stores it as an idempotent `USAGE#<queue-message-id>` item under the requesting user's
DynamoDB partition, keyed by the SQS message ID. OpenRouter cost is preserved when supplied; versioned price estimates
cover supported fallback models. Usage records contain no prompt, response, tool payload, or attachment content and
expire after 400 days.

## Agent runtime

`services/agent-runtime/runtime/main.py` is only the AgentCore transport adapter. The production-only `runtime/`
directory is the CodeZip source boundary: `frogbot_runtime/request.py` normalizes untrusted invocation payloads,
`configuration.py` builds per-bot and per-group instructions, `capability_contract.py` validates the reviewed
allowlist, and the local, AgentCore, and gateway adapter modules assemble only the tools and skills enabled for that bot.
Stan and Strands stay behind this boundary so the mobile/API layers do not duplicate agent logic.
AgentCore OpenTelemetry remains enabled for errors, timings, token usage, and tool activity, while both the
AWS model instrumentation and Strands tracer redact prompt, response, tool payload, and attachment content.

Direct conversations use stable, hashed AgentCore actor and session identifiers. The worker supplies the latest
50 completed turns, and the runtime's automatic context manager starts summarizing at 85% of the model window. It
condenses the oldest 30% while preserving at least the newest 10 messages. Earlier conversation topics remain in
AgentCore session summaries and are retrieved by relevance, so falling outside the recent window does not make them
unavailable. AgentCore Memory also recalls user preferences and facts across bots. Browser
and code-interpreter sandboxes are named by the stable conversation ID and reconnect to READY sessions
after runtime process replacement. Generated files use a turn-scoped S3 prefix and are attached to the
completed reply only after the worker verifies and records them.

Long-running work is capability-driven, not bot-specific. Any bot with Code Interpreter can start an
asynchronous command in its eight-hour microVM. The runtime emits only the task identity, the worker stores it on
the pending turn, and short queue jobs poll without spending model tokens. When the command finishes, the same bot
and conversation resume with bounded command output and the persistent workspace. Cancellation stops both the task
and its sandbox. A GitHub connection plus Code Interpreter also exposes repository staging: the server uses the
owner's credential to download a private archive, but never puts that credential in the sandbox or prompt.

The authenticated Memory screen makes extracted preferences, facts, and per-bot summaries readable to their owner.
Each item can be corrected or forgotten, and the complete set can be downloaded as portable JSON through a short-lived
private URL. Raw conversation events expire after 30 days; extracted records remain under the user's hashed namespace
until the user changes them, forgets them, or deletes the account. Group memory stays explicit and owner-edited rather
than being mixed into a participant's private memory.

Public skills contain versioned instructions plus approved tool references, never executable code. Managed
FroggyBot integrations stay in narrow AgentCore Gateway targets and use company-owned service credentials. Users
never enter those developer keys. Private account data uses provider-specific OAuth; each user's token is encrypted
in Secrets Manager, resolved only during invocation, and omitted from prompts, telemetry, catalog responses, and
shares. Existing custom MCP connections remain runtime-compatible and removable, but no new or edited custom
developer-key connections are exposed by the API.
Provider display metadata is registered once in the backend's public-safe connection manifest. Adding that metadata
makes the generic UI and authorization endpoint aware of the provider; adding the secret-bearing OAuth adapter and
runtime permissions remains an explicit reviewed server change.
The separate `frogbot-skills` repository is the public website and capability publishing boundary. Pull requests are validated there;
the backend then validates and caches releases before exposing only public metadata to signed-out visitors. Chief is a required public
template: first-time setup installs it and applies the protected coordinator role without duplicating its prompt or capabilities in app code.

## Invariants

- `agentcore/agentcore.json` is the source of truth for AgentCore resources; generated CDK is not.
- `services/froggybot-api/amplify/functions/api/api-contract.json` is the source of truth for application HTTP routes; its generated client map must be current.
- Existing CDK construct IDs and resource names are stable because renaming them can replace data.
- Every authenticated read/write verifies ownership or group membership server-side.
- Invitation tokens are random, time-limited, and stored as hashes for sign-up validation.
- A bot can receive only enabled built-ins, that user's connected accounts or existing legacy connections, and version-pinned skills in its saved configuration.
- Agent jobs are retried through SQS and failed permanently only after the configured retry limit.
- One worker owns a turn at a time through a renewable lease; completion is conditional on that ownership.
- Scheduled executions are idempotent by schedule execution ID, use IANA timezones, and never embed bot prompts in EventBridge.
- Attachments and generated artifacts are bound to the current user's hashed storage prefix.
- Interactive tools cannot run in scheduled or group work, and direct browser turns require explicit approval.
- Account deletion revokes active shares, cancels pending work, deletes user data and all S3 versions, and disables the Cognito identity.
- A memory record can be read, changed, deleted, or exported only after its AgentCore namespace is verified against the authenticated user.
- User-visible notifications are queued only after the final answer, never for thinking updates.
- Model usage is charged to the requesting user, and retrying the same queue message cannot create a duplicate record.

## Verification

Run the complete local checks from the repository root before a deployment:

```bash
scripts/verify.sh
```

The [verification guide](verification.md) owns local and CI commands. Operational targets and recovery procedures are
maintained in [operations.md](operations.md), while dated deployed evidence belongs in
[verification-history.md](verification-history.md).
