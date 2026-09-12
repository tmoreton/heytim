# FroggyBot tutorial

This guide explains the repository in the order a new contributor should learn it. Start with the
local preview, follow one message through the system, and only then move into AWS infrastructure.

## 1. Learn the three boundaries

```text
apps/froggybot/          The Expo product and its Amplify application backend
services/agent-runtime/  The AI runtime that turns a bot configuration into an agent
agentcore/               The declarative AWS AgentCore configuration
```

The mobile app owns what people see and the application data they create. The Amplify backend owns
authentication, storage, queues, schedules, and HTTP routes. The AgentCore runtime owns prompting,
tools, skills, memory, and generated artifacts.

Keeping these boundaries separate prevents the interface from knowing how an agent works and keeps
the runtime independent of any particular screen.

## 2. Run the local preview

The preview is the fastest way to understand the product because it exercises the real interface
without calling AWS.

```bash
cd apps/froggybot
nvm use
npm install
npm run ios
```

Choose **Preview the app** on the welcome screen. For a browser preview, run `npm run web`.

Read the preview path in this order:

1. `src/app/app.tsx` is the Expo route.
2. `src/features/app/app-entry.tsx` chooses authentication or the signed-in product.
3. `src/features/chat/chat-app.tsx` coordinates the selected conversation and modal screens.
4. `src/features/chat/conversation-panel.tsx` renders the active conversation.
5. `src/lib/api.ts` presents one API to the interface.
6. `src/lib/demo.ts` implements that API with in-memory preview data.
7. `src/lib/demo-catalog.ts` loads the same public capability catalog used in production.

The chat folder keeps each workflow separate: attachments, invitation links, and dictation are hooks;
editors and sheets are components; `chat-app.tsx` only joins them together.

## 3. Follow a live message

When preview mode is off, the same `src/lib/api.ts` adapter sends an authenticated HTTP request.
Follow a direct message through these files:

```text
src/lib/api.ts
  -> amplify/functions/api/handler.py
  -> amplify/functions/api/direct_chat.py
  -> SQS
  -> amplify/functions/worker/handler.py
  -> amplify/functions/worker/direct_job.py
  -> amplify/functions/worker/agent.py
  -> AgentCore Runtime
  -> DynamoDB reply
  -> Expo notification
```

The API handler routes requests. Domain modules validate ownership and update application state. The
worker handler routes queue jobs. Worker modules claim work, invoke AgentCore, save the result, and
queue the final notification.

Chief and the specialists are minimal templates from the public catalog. Setup requires Chief and marks its
installed copy with the protected coordinator role; onboarding lets each person choose any additional bots they want.
`amplify/functions/api/bot_roles.py` contains only that application role and reserved branding, not Chief's prompt
or capabilities.

The same pattern covers groups, schedules, uploads, sharing, and account deletion. Each domain has a
matching file under `amplify/functions/api` or `amplify/functions/worker`.

## 4. Understand the agent runtime

The deployed runtime starts in `services/agent-runtime/runtime/main.py`. The `runtime/` directory is the production-only
CodeZip boundary; tests, offline evaluations, and packaging checks remain outside it. Read its supporting modules in this order:

1. `runtime/frogbot_runtime/request.py` validates the invocation and loads approved attachments.
2. `runtime/frogbot_runtime/configuration.py` builds direct or group instructions.
3. `runtime/frogbot_runtime/capability_contract.py` validates enabled tools and pinned skills.
4. `runtime/frogbot_runtime/local_tools.py`, `agentcore_adapters.py`, and `gateway_tools.py` isolate capability implementations.
5. `runtime/frogbot_runtime/background_work.py` starts long commands without holding open a model request.
6. `runtime/frogbot_runtime/memory.py` recalls and records long-term memory.
7. `runtime/frogbot_runtime/artifacts.py` exposes generated files to the agent.
8. The renderer modules turn text into PDF, Word, Excel, PowerPoint, or PNG files. Direct outputs stay private to the
   person; group outputs are downloadable by current group members.
9. `runtime/frogbot_runtime/telemetry.py` removes sensitive model content from traces.

One runtime serves every bot. Bot name, prompt, tools, skill versions, user identity, and conversation
identity arrive in the request rather than being hard-coded into separate deployments.

The app worker follows the same rule. `worker/background_work.py` implements the shared pause, poll, and resume
contract for every bot. Code Interpreter is the first provider: it can run for up to eight hours, while inexpensive
queue checks wait for completion. Adding a provider means adding an adapter to this contract, not branching on bot
names or IDs.

Direct chats have two context layers. The latest 50 turns are sent verbatim. If that material reaches 85% of the
model context window, Strands automatically summarizes the oldest 30% and protects the newest 10 messages. AgentCore
separately extracts durable preferences and facts for the person plus topic summaries for each stable bot session.
The app's Account → Memory screen lists those records, verifies ownership before every edit or deletion, and creates a
portable JSON download. Raw AgentCore events expire after 30 days, while extracted records stay until the user changes
or removes them.

## 5. Understand configuration and infrastructure

`agentcore/agentcore.json` is the source of truth for AgentCore resources. Read the matching types in
`agentcore/.llm-context/agentcore.ts` before changing it, then run `agentcore validate`. Never change
generated behavior under `agentcore/cdk`.

`apps/froggybot/amplify/backend.ts` composes the application stack. It creates Cognito, DynamoDB, S3,
SQS, Lambda, Scheduler, and the HTTP API. `amplify/infrastructure/api-routes.ts` lists the authenticated
API surface, while `observability.ts` adds alarms, the dashboard, and the monthly budget. Existing construct IDs and AgentCore resource names are stable;
renaming them can replace live resources.

The application backend keeps only the catalog trust and persistence layer:

```text
catalog_rules.py       IDs, limits, and runtime-binding validation
catalog_sync.py        Trusted remote download and shared refresh lease
catalog.py             User libraries, version pinning, importing, and sharing
connections.py         OAuth and legacy connection metadata and encrypted credential lifecycle
```

The external `frogbot-skills` repository owns the public website, bot templates, capability catalog, and contribution
review. Each entry includes display metadata for `froggybot.com/library/`; tool entries also list the human-readable
actions they expose. The
backend keeps the last successfully reviewed release if a refresh fails; it does not carry a second bundled catalog.
The unauthenticated `GET /public/catalog` route returns only sanitized, currently usable listings. A public directory link
carries a selected bot, skill, or tool to `app.froggybot.com/app`. Bot links open the installable library, while
skill and tool links open the bot editor and still require an explicit save. The public site deploys from its own
repository, independently of app releases.

The signed-in bootstrap returns the same sanitized official tools together with that user's private connections. The
client separates them by provenance: official entries populate Skills & tools, while OAuth and legacy entries populate
Connections. Even preview-mode sample bots derive their names, prompts, versions, skills, and tool requirements from
the current catalog, so publishing an approved metadata or composition update does not require an app build.

The runtime still contains reviewed implementations for local and managed tools plus a strict execution allowlist.
Those pieces run with server permissions, so they cannot be downloaded from a community repository. Public names,
descriptions, bindings, skill instructions, and external API schemas live only in `frogbot-skills`.

Connections are provider-specific. Shared services use FroggyBot-owned credentials, so users never paste developer
keys into the app. Private account data uses OAuth; the backend encrypts each user's token in Secrets Manager and the
runtime fetches it only for the selected connection. Connected accounts never appear in public catalog responses or
shared bot and skill snapshots. Existing custom MCP connections are legacy-only: users can review or remove them,
but cannot create or edit them.

## 6. Add a feature vertically

Use the narrowest path that fits the feature:

1. Add or update shared TypeScript types in `src/lib/types.ts`.
2. Add the client operation in `src/lib/api.ts` and its preview behavior in `src/lib/demo.ts`.
3. Put interface behavior in the relevant feature folder; keep route files as shells.
4. Add the authenticated route to `amplify/backend.ts`.
5. Route it in `amplify/functions/api/handler.py`.
6. Put persistence and authorization in the matching API domain module.
7. Add a worker job only when work can outlive an HTTP request.
8. Change the AgentCore runtime only when agent behavior, tools, memory, or artifacts must change.
9. Test the smallest module first, then run the full verification command.

Prefer names that describe product concepts. Comments should explain a non-obvious constraint or
reason, not restate the code. If a file approaches 600 lines, split it by responsibility before adding
more behavior.

## 7. Verify locally

```bash
scripts/verify.sh
```

Run this command from the repository root. The [verification guide](verification.md) lists focused checks for iteration
and explains what CI and deployed verification cover.

## 8. Deploy and prove the flow

Follow the deployment order in the repository [README](../README.md): AgentCore first, then the
Amplify backend, then the client. After deployment, run the authenticated workflow test from
`apps/froggybot` and confirm the dashboard and alarms described in [operations.md](operations.md).

Do not use AWS account-root credentials for development or deployment. Use an IAM Identity Center or
least-privilege deployment role, and keep credentials out of the repository.
