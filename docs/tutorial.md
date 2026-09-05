# FroggyBot tutorial

This guide explains the repository in the order a new contributor should learn it. Start with the
local preview, follow one message through the system, and only then move into AWS infrastructure.

## 1. Learn the three boundaries

```text
apps/mobile/        The Expo product and its Amplify application backend
app/FrogBot/        The AI runtime that turns a bot configuration into an agent
agentcore/           The declarative AWS AgentCore configuration
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
cd apps/mobile
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
7. `src/lib/demo-skills.ts` contains only the longer skill fixtures.

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

The same pattern covers groups, schedules, uploads, sharing, and account deletion. Each domain has a
matching file under `amplify/functions/api` or `amplify/functions/worker`.

## 4. Understand the agent runtime

The deployed runtime starts in `app/FrogBot/main.py`. Read its supporting modules in this order:

1. `frogbot_runtime/request.py` validates the invocation and loads approved attachments.
2. `frogbot_runtime/configuration.py` builds direct or group instructions.
3. `frogbot_runtime/capabilities.py` resolves the bot's enabled tools and pinned skills.
4. `frogbot_runtime/memory.py` recalls and records long-term memory.
5. `frogbot_runtime/artifacts.py` exposes generated files to the agent.
6. The renderer modules turn text into PDF, Word, Excel, PowerPoint, or PNG files.
7. `frogbot_runtime/telemetry.py` removes sensitive model content from traces.

One runtime serves every bot. Bot name, prompt, tools, skill versions, user identity, and conversation
identity arrive in the request rather than being hard-coded into separate deployments.

## 5. Understand configuration and infrastructure

`agentcore/agentcore.json` is the source of truth for AgentCore resources. Read the matching types in
`agentcore/.llm-context/agentcore.ts` before changing it, then run `agentcore validate`. Never change
generated behavior under `agentcore/cdk`.

`apps/mobile/amplify/backend.ts` composes the application stack. It creates Cognito, DynamoDB, S3,
SQS, Lambda, Scheduler, and the HTTP API. `amplify/infrastructure/observability.ts` adds alarms, the
dashboard, and the monthly budget. Existing construct IDs and AgentCore resource names are stable;
renaming them can replace live resources.

The capability catalog is deliberately split into four files:

```text
catalog_defaults.py    Safe built-in tools and skills used before a remote refresh
catalog_rules.py       IDs, limits, and runtime-binding validation
catalog_sync.py        Trusted remote download and shared refresh lease
catalog.py             User libraries, version pinning, importing, and sharing
```

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
agentcore validate

cd app/FrogBot
uv run ruff check .
uv run pytest -q

cd ../../apps/mobile
npm run verify
npm run build:web
uvx bandit -q -r amplify/functions -x amplify/functions/tests
```

`npm run verify` includes the 600-line source-size guard, TypeScript checks, linting, backend tests, and
Expo project health.

## 8. Deploy and prove the flow

Follow the deployment order in the repository [README](../README.md): AgentCore first, then the
Amplify backend, then the client. After deployment, run the authenticated workflow test from
`apps/mobile` and confirm the dashboard and alarms described in [operations.md](operations.md).

Do not use AWS account-root credentials for development or deployment. Use an IAM Identity Center or
least-privilege deployment role, and keep credentials out of the repository.
