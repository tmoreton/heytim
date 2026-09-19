# HeyTim tutorial

This guide explains the repository in the order a new contributor should learn it. Start with the
local Apple app, follow one message through the system, and only then move into AWS infrastructure.

## 1. Learn the deployment boundaries

```text
apps/iOS/    The primary SwiftUI client for iPhone and Mac
apps/website/          The Vite marketing site and skills library
catalog/               Public bot, skill, and tool definitions
services/API/  The Amplify application backend
services/runtime/  The AI runtime that turns a bot configuration into an agent
agentcore/               The declarative AWS AgentCore configuration
```

The SwiftUI app owns conversations; the public Vite website owns marketing and the skills directory.
The Amplify backend owns authentication, storage, queues, schedules, and HTTP routes. The AgentCore runtime owns prompting,
tools, skills, memory, and generated artifacts.

Keeping these boundaries separate prevents the interface from knowing how an agent works and keeps
the runtime independent of any particular screen.

## 2. Run the Apple app locally

The supported local entry point builds the same shared SwiftUI target used for TestFlight:

```bash
./scripts/apple-app.sh run ios
./scripts/apple-app.sh run macos
```

For the public website, run `npm ci && npm run dev` from `apps/website`. No AWS
credentials are needed. Browser chat is deliberately not part of this site.

Read the primary Apple path in this order:

1. `apps/iOS/App/HeyTimAppleApp.swift` is the application entry.
2. `Sources/HeyTimUI/MainView.swift` chooses authentication or the signed-in product and owns adaptive navigation.
3. `Sources/HeyTimCore/AppModel.swift` coordinates application state and actions.
4. `Sources/HeyTimCore/APIClient.swift` sends authenticated requests through generated routes.
5. `Sources/HeyTimUI/MarkdownMessageView.swift` and the feature sheets render the product surface.
6. `Sources/HeyTimPlatform/` isolates Keychain, APNs, dictation, and platform lifecycle behavior.

The retired Expo source is preserved outside the repository; see [migration notes](monorepo-migration.md).

## 3. Follow a live message

When signed in, `APIClient.swift` sends an authenticated HTTP request.
Follow a direct message through these files:

```text
apps/iOS/Sources/HeyTimCore/APIClient.swift
  -> services/API/amplify/functions/api/handler.py
  -> services/API/amplify/functions/api/direct_chat.py
  -> SQS
  -> services/API/amplify/functions/worker/handler.py
  -> services/API/amplify/functions/worker/direct_job.py
  -> services/API/amplify/functions/worker/agent.py
  -> AgentCore Runtime
  -> DynamoDB reply
  -> SNS/APNs notification
```

The API handler routes requests. Domain modules validate ownership and update application state. The
worker handler routes queue jobs. Worker modules claim work, invoke AgentCore, save the result, and
queue the final notification.

Chief and the specialists are minimal templates from the public catalog. Setup requires Chief and marks its
installed copy with the protected coordinator role; onboarding lets each person choose any additional bots they want.
`services/API/amplify/functions/api/bot_roles.py` contains only that application role and reserved branding, not Chief's prompt
or capabilities.

The same pattern covers groups, schedules, uploads, sharing, and account deletion. Each domain has a
matching file under `services/API/amplify/functions/api` or
`services/API/amplify/functions/worker`.

## 4. Understand the agent runtime

The deployed runtime starts in `services/runtime/runtime/main.py`. The `runtime/` directory is the production-only
CodeZip boundary; tests, offline evaluations, and packaging checks remain outside it. Read its supporting modules in this order:

1. `runtime/heytim_runtime/request.py` validates the invocation and loads approved attachments.
2. `runtime/heytim_runtime/configuration.py` builds direct or group instructions.
3. `runtime/heytim_runtime/capability_contract.py` validates enabled tools and pinned skills.
4. `runtime/heytim_runtime/local_tools.py`, `agentcore_adapters.py`, and `gateway_tools.py` isolate capability implementations.
5. `runtime/heytim_runtime/background_work.py` starts long commands without holding open a model request.
6. `runtime/heytim_runtime/memory.py` recalls and records long-term memory.
7. `runtime/heytim_runtime/artifacts.py` exposes generated files to the agent.
8. The renderer modules turn text into PDF, Word, Excel, PowerPoint, or PNG files. Direct outputs stay private to the
   person; group outputs are downloadable by current group members.
9. `runtime/heytim_runtime/telemetry.py` removes sensitive model content from traces.

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

`services/API/amplify/backend.ts` composes the application stack. It creates Cognito, DynamoDB, S3,
SQS, Lambda, Scheduler, and the HTTP API. `services/API/amplify/functions/api/api-contract.json` is the one authored
route list used by CDK, the Python dispatcher, and the generated client route map. Run
`npm run contract:generate` from `services/API` after changing it; its tests reject a stale generated map. `observability.ts`
adds alarms, the dashboard, and the monthly budget. Existing construct IDs and AgentCore resource names
are stable; renaming them can replace live resources.

The application backend keeps only the catalog trust and persistence layer:

```text
catalog_rules.py       IDs, limits, and runtime-binding validation
catalog_sync.py        Trusted remote download and shared refresh lease
catalog.py             User libraries, version pinning, importing, and sharing
connections.py         OAuth and GitHub App connection metadata and encrypted grant lifecycle
```

`catalog/` owns reviewed bot templates, skills and tools in this monorepo.
`apps/website` builds the public directory and publishes the catalog's existing
URLs. The backend keeps the last successfully reviewed release if refresh fails;
it does not carry a second bundled catalog. Public pages point visitors to the
Apple app; there is no browser chat. Website publishing is independent of TestFlight.

The signed-in bootstrap returns the same sanitized official tools together with that user's private connections. The
client separates them by provenance: official entries populate Skills & tools, while managed account entries populate
Connections. Publishing an approved catalog update does not require an app build.

The runtime still contains reviewed implementations for local and managed tools plus a strict execution allowlist.
Those pieces run with server permissions, so they cannot be downloaded from a community repository. Public names,
descriptions, bindings, skill instructions, and external API schemas live in `catalog/`.

Connections are declared in the backend's public-safe provider manifest, which drives the Connections screen and
generic authorization route. Secret-bearing OAuth adapters remain provider-specific and server-side. Shared services
use HeyTim-owned credentials, so users never paste developer keys into the app. Private account data uses
provider-specific OAuth or a GitHub App installation; the backend encrypts each user's grant in Secrets Manager and
the runtime fetches it only for the selected connection.
Connected accounts never appear in public catalog responses or shared bot and skill snapshots. Existing custom MCP
bearer/API-key records are legacy-only and deliberately ignored by both the catalog and runtime.

## 6. Add a feature vertically

Use the narrowest path that fits the feature:

1. Add or update shared TypeScript types in `packages/heytim-contract/src/types.ts`.
2. Add the operation to the contract interface and the Swift API client in `apps/iOS`.
3. Add native test fixtures and unit coverage in `apps/iOS/Tests`.
4. Keep native platform adapters separate from SwiftUI screens and app state.
5. Add an API route once in `services/API/amplify/functions/api/api-contract.json`, then run `npm run contract:generate` from the service directory.
6. Map its handler name in `authenticated_routes.py` and put persistence and authorization in the matching API domain module.
7. Return a stable machine-readable error code when clients need to distinguish a failure mode.
8. Add a worker job only when work can outlive an HTTP request.
9. Change the AgentCore runtime only when agent behavior, tools, memory, or artifacts must change.
10. Test the smallest module first, then run the full verification command.

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
`services/API` and confirm the dashboard and alarms described in [operations.md](operations.md).

Do not use AWS account-root credentials for development or deployment. Use an IAM Identity Center or
least-privilege deployment role, and keep credentials out of the repository.
