# FroggyBot

FroggyBot is a small Apple-first AI team app. One Amazon Bedrock AgentCore runtime serves every bot;
each bot supplies its own prompt, enabled tools, enabled skills, and stable session ID. The primary client is one
native SwiftUI target shared by iPhone and Mac. The preserved Expo project now serves only the browser experience
and as a migration reference; it is not an Apple build or release source. Amplify provisions passwordless
email-code sign-in and the serverless chat API used by both clients.

## Repository layout

```text
apps/froggybot-apple/    Primary SwiftUI app for iPhone and Mac
apps/froggybot/          Preserved Expo browser client and legacy native reference
services/froggybot-api/  Amplify application backend
services/agent-runtime/  AgentCore runtime and runtime-only modules
agentcore/               Declarative AgentCore resources and gateway schemas
docs/                    Tutorial, architecture, and operations guides
```

Use `scripts/apple-app.sh` from the repository root for local Apple builds, verification, archives, and TestFlight.
Expo and EAS commands under `apps/froggybot` are browser-only unless their name explicitly begins with `legacy:`;
native EAS builds are intentionally blocked. `services/agent-runtime` is referenced by `agentcore.json`, which remains
the source of truth
for deployed agent resources. The older internal name `FrogBot` remains in AWS resource identities because
renaming it would replace deployed infrastructure;
user-facing product copy uses `FroggyBot`. The maintained boundary and request-flow
guide is in [`docs/architecture.md`](docs/architecture.md), provider setup is in
[`docs/integrations.md`](docs/integrations.md), and the remaining product work is tracked
in [`docs/grokbot-parity-roadmap.md`](docs/grokbot-parity-roadmap.md). Reusable,
account-owned specialist packs are documented in
[`docs/bot-workflows.md`](docs/bot-workflows.md).

## Architecture

```text
SwiftUI app (iPhone + Mac) --+
  |-- on-device speech       |
  |-- native APNs            +-- Cognito email-code sign-in
Expo browser client ---------+-- authenticated HTTP API
        |-- DynamoDB: bot configs, chats, files, groups, tasks, tokens, and invites
        |-- Secrets Manager: per-user OAuth and GitHub App installation grants
        |-- S3: private user uploads and generated artifacts
        |-- EventBridge Scheduler: daily, weekday, weekly, and monthly tasks
        |-- SQS: durable agent jobs
              |-- Lambda worker
                    |-- AgentCore Runtime -> Strands + Stan
                    |     |-- AgentCore Memory -> preferences, facts, summaries
                    |     |-- persistent browser and code-interpreter sessions
                    |-- AgentCore Gateway -> reviewed external tools
                    |-- Amazon SNS -> APNs
```

The request path is asynchronous so a long agent turn is not limited by an HTTP request timeout.
The app polls only while a response is pending. DynamoDB is the source of truth for chat history;
the worker derives stable, non-PII AgentCore actor and session IDs. Direct chats use a private user actor
and per-bot session. Groups use an isolated group actor and one shared memory session, so a bot never
imports its owner's private memory into a room. In a team round, bots reply
one at a time so every later bot sees the people, the full bot roster, and earlier bot contributions.
The first bot coordinates the round, specialists add distinct perspectives, and the coordinator returns
one final synthesized team answer.

The app API is composed from small domain contracts with matching cloud and in-memory preview adapters.
The backend, Python dispatcher, and client URL builder share one authored route contract, and expected failures
use stable error codes. Connection display metadata is likewise declared once in a public-safe backend manifest;
OAuth secrets and provider implementations remain reviewed server-side code.

New contributors should follow the [start-to-finish tutorial](docs/tutorial.md). It gives the reading
order for the preview app, live request path, AgentCore runtime, infrastructure, tests, and deployment.

## What is included

- Email-only Cognito sign-up and sign-in with one-time codes while the US SMS sender is registered
- Responsive chat UI with a collapsible bot list
- Push notification when an agent reply completes, with tap-to-open navigation
- Daily, weekday, weekly, and monthly per-bot tasks in the device's timezone, with pause and run-now controls
- Apple on-device speech-to-text in the message composer without saved audio
- Private image and document uploads, plus downloadable text, Markdown, CSV, JSON, HTML, PDF, Word, Excel,
  PowerPoint, and generated PNG artifacts in direct or shared group conversations
- Meme Lord rendering from private S3 templates with template-aware caption placement, plus a separately selectable
  OpenRouter image tool for original images and draft YouTube thumbnails built from recent user images
- Per-bot name, description, prompt, color, tools, and version-pinned skills
- Shared groups with a pinned owner-editable notebook, reviewable learned group memory, one-link passwordless participation, single-bot replies, and ordered team collaboration rounds
- Inline reports, drafts, and next steps in chat, with downloadable documents when explicitly requested
- Owner-controlled chat, bot, and group deletion with pending-work protection and invite revocation
- A skill library for creating, editing, and sharing reusable ways of working
- Chief as the protected built-in, plus ten installable bot templates and eleven focused public skills from the dynamically refreshed catalog
- A dedicated Connections screen: shared services are included, while private account data uses provider OAuth
- Bot snapshots, conversation snapshots, and live group invitations with 30-day links
- Scoped AgentCore memory: private user preferences/facts, per-bot summaries, and isolated shared group preferences/facts/summaries, with in-app creation, review, editing, and forgetting
- Explicit clear-chat choices for preserving or forgetting conversation memory; bot and group deletion also enqueue matching memory cleanup
- Persistent two-hour browser and code-interpreter sessions; browser use requires one-time approval for each turn
- DynamoDB persistence, encrypted queues and topics, retries, work leases, cancellation, and a dead-letter queue
- CloudTrail audit logs, API access logs, X-Ray tracing, service alarms, and a CloudWatch dashboard
- Permanent in-app account deletion, including active share revocation and versioned user-file deletion
- Published service objectives, alarm response, and recovery procedures in [`docs/operations.md`](docs/operations.md)
- One native SwiftUI application shared across iPhone and Mac, with separate TestFlight builds from the same target
- A separately deployed browser client retained from the Expo implementation
- A browser preview mode that works before AWS is connected

## Local Apple builds

From the repository root, build and launch the primary SwiftUI app on an iPhone simulator or this Mac:

```bash
./scripts/apple-app.sh run ios
./scripts/apple-app.sh run macos
```

Open the shared Xcode project with `./scripts/apple-app.sh open`. For the preserved browser preview, use
`npm run web:preview` from `apps/froggybot`; it is not the source for an iPhone or Mac binary.

## Deploy to AWS

Use an IAM Identity Center or least-privilege deployment role. Do not deploy with AWS account root
credentials.

### 1. Deploy the agent runtime

From the repository root:

```bash
agentcore validate
agentcore deploy --target production
agentcore status --target production --runtime FrogBot --json
agentcore status --target production --type memory --json
```

Development and production use separate target stacks in account `188757775631`, `us-east-1`; never rename
either target because that changes resource identity. Confirm that both the runtime and
memory are ready, then copy the deployed runtime ARN from the status output. Model selection is defined only in
`agentcore/agentcore.json`: OpenRouter uses DeepSeek V4.1 Flash with GLM 5.3 as a bounded pre-response fallback, while
the separately selected image tool uses GPT Image 2.5 Sunburst through OpenRouter. Finished thumbnails send the full
composition and selected recent image references to OpenRouter, then normalize the result to 1280x720.
CDK synthesis and the release scripts refuse uncommitted source, and AWS releases also refuse account-root
credentials. Required provider access must be available in the configured accounts and regions. Development
owns the existing `frogbot-user-files-188757775631-us-east-1` bucket and its customer-managed encryption
key; production imports that bucket and key so attachments remain compatible with the runtime's fixed
`FROGBOT_FILES_BUCKET` configuration. Authentication, message tables, queues, functions, and stacks remain
separate between the two deployment targets.

### 2. Optional future phone sign-in

Request and register a US toll-free origination number in AWS End User Messaging SMS in `us-east-1`. While the
account is in the SMS sandbox, messages can reach only verified test destinations and only after an origination
identity exists. Request SMS production access before inviting general TestFlight users. US carrier registration
also requires a documented opt-in flow, public privacy policy and terms, and accurate legal business details.

### 3. Deploy the app backend

```bash
cd services/froggybot-api
nvm use
npm install
npm run contract:generate
npm run contract:check
export FROGBOT_AGENT_RUNTIME_ARN='arn:aws:bedrock-agentcore:us-east-1:188757775631:runtime/REPLACE_ME'
export FROGBOT_MEMORY_ID='FrogBot_FrogBotMemory-REPLACE_ME'
export FROGBOT_GOOGLE_OAUTH_SECRET_ARN='arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:frogbot/oauth/google-REPLACE_ME'
export FROGBOT_GITHUB_APP_SECRET_ARN='arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:frogbot/oauth/github-REPLACE_ME'
export FROGBOT_X_OAUTH_SECRET_ARN='arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:frogbot/oauth/x-REPLACE_ME'
export FROGBOT_SLACK_OAUTH_SECRET_ARN='arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:frogbot/oauth/slack-REPLACE_ME'
export FROGBOT_MICROSOFT_OAUTH_SECRET_ARN='arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:frogbot/oauth/microsoft-REPLACE_ME'
export FROGBOT_NOTION_OAUTH_SECRET_ARN='arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:frogbot/oauth/notion-REPLACE_ME'
export FROGBOT_ENVIRONMENT='production'
npm run sandbox -- --once --identifier frogbot --profile YOUR_AWS_PROFILE
```

Amplify writes the real Cognito and API values to `apps/froggybot/amplify_outputs.json`. Run
`npm run outputs:apple` from `services/froggybot-api` after those values change, then launch the app with
`./scripts/apple-app.sh run ios` or `./scripts/apple-app.sh run macos` from the repository root. Expo SDK 57 and the
Amplify tooling require Node 22.13 or newer; the pinned Node 22 line also avoids the Amplify CLI incompatibility
seen under Node 25.

Set `FROGBOT_AGENT_RUNTIME_QUALIFIER` only if the runtime should use a qualifier other than
`DEFAULT`. Deploy with an IAM Identity Center or least-privilege role; the deployment runbook must
never use AWS account-root credentials.

After deploying an AgentCore runtime, set `FROGBOT_LOGS_KMS_KEY_ARN` to the backend `logsKeyArn`
output and run `scripts/harden-agentcore-logs.sh`. The script applies 30-day retention and
customer-managed encryption to the runtime log group and enforces the same non-root preflight. Its post-deploy
mode permits only the CLI deployment state and Amplify outputs generated by the preceding release commands;
any source change still stops the release.

The manual `Deploy FroggyBot production infrastructure` GitHub workflow is the preferred production path.
Its `production` environment requires `AWS_DEPLOY_ROLE_ARN`, `AMPLIFY_APP_ID`, the three company-owned
OpenRouter, X, and YouTube credentials documented in `agentcore/README.md`, and the Google, GitHub App, and X OAuth
secret ARNs plus the Slack, Microsoft, and Notion OAuth secret ARNs documented in
[`docs/integrations.md`](docs/integrations.md).
Users never enter these platform credentials. The backend's development stack creates the narrowly trusted
GitHub OIDC role and exposes its ARN as `githubDeployRoleArn`; bootstrap that role once using IAM Identity
Center or another reviewed administrator role, never account-root credentials.

## Bots, skills, and tools

The reviewed public catalog and marketing site live in [FroggyBot Skills](https://github.com/tmoreton/frogbot-skills).
Visitors can browse its ready-made bots without signing in at `https://froggybot.com/library/`; skills and tool
definitions remain composable catalog internals. Search, categories, trust labels, and deep links make the bot
directory useful as a storefront. A bot link opens the installable bot library.
Bot templates contain only identity, a prompt, skill references, and any directly required tool references.
Model selection, reasoning level, credentials, schedules, memory, and approvals remain app concerns.
Chief is one of those public templates. New-account setup requires it and applies the protected coordinator role
after installation; the app does not keep a fallback Chief prompt or capability list.
Skill releases use immutable Git tags, and every bot stores the exact skill version it selected. Updating a skill
therefore does not silently change an existing bot or a previously shared bot. Catalog refreshes add or remove
listings without deleting old versions that existing bots still need.
The app's Tools screen and preview-mode bot compositions are derived from that catalog response; there is no second
client-side list of official tool names, descriptions, or bot tool assignments to keep synchronized.
The Connections screen follows the same data-driven pattern using the backend provider manifest. A new provider can
reuse the generic UI and authorization route after its server adapter and permissions have been reviewed; no provider
API key is accepted from an end user or shipped in the client.

Users can create instruction-only skills inside the app, attach only the tools that skill needs, and share a
30-day installation link. Shared skills are read-only for the recipient and require an explicit trust confirmation.
Installing a public bot never requires a developer key. Shared tools use FroggyBot-owned credentials behind narrow
AgentCore Gateway targets. Private account data uses provider-specific OAuth or a GitHub App installation; per-user
grants are encrypted in Secrets Manager and fetched only when the runtime invokes that account. They never enter the app bundle, a skill document, a
prompt, or a shared link. Legacy generic MCP bearer/API-key records remain in storage but are intentionally unlisted
and unusable. The public repository includes validation automation,
contribution templates, and separate request forms for public skills and tool proposals.

Gmail uses Google's generally available REST API through a first-class OAuth connection. Each user grants their own
account read-email and create-draft access; refresh tokens stay in a per-user Secrets Manager secret. The runtime
exposes only search, read, list, and draft tools, so it cannot send, delete, relabel, archive, or mark email. This path
supports personal Gmail accounts without enrolling a Workspace project in Developer Preview. Gmail access is treated
as interactive because email is untrusted input, which keeps it out of groups and unattended schedules.

The reviewed catalog keeps public X and YouTube research available without sign-in. Optional private YouTube and X
data use per-user read-only OAuth; GitHub uses a repository-selected GitHub App whose installation tokens are minted
only when needed. Do not describe a provider as available until its adapter is deployed, ready, and visible in the
reviewed catalog.

## Verification

```bash
scripts/verify.sh
```

See [the verification guide](docs/verification.md) for prerequisites, focused commands, CI coverage, and deployed checks.

## App releases and websites

All new iPhone and Mac binaries come from `apps/froggybot-apple`. Create an archive for Organizer, or archive and
upload directly to App Store Connect for TestFlight, with:

```bash
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh archive ios
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh archive macos
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh testflight ios
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh testflight macos
```

The TestFlight command refuses a dirty source tree, checks the bundled backend configuration, runs the Apple test
suite, and preserves the selected build number. It uses the Apple Developer account signed into Xcode, or an App
Store Connect API key supplied through the documented environment variables. No signing material belongs in this
repository.

The GitHub Actions workflow at `.github/workflows/eas-update.yml` now builds and deploys only the browser client after
every push to `main`; it no longer publishes native Expo updates. The Expo credential remains the repository secret
`EXPO_TOKEN` for that web deployment. The browser app at `https://app.froggybot.com` owns application and invite routes.

The separate [FroggyBot Skills](https://github.com/tmoreton/frogbot-skills) repository owns the public homepage,
library, contribution guide, and legal pages at `https://froggybot.com`. Its GitHub Pages workflow publishes on
every catalog or website change, independently of the app release cycle. Public `/invite` links preserve their
query string and hand off to the browser app subdomain.

## Key locations

- `services/agent-runtime/runtime/main.py` - small AgentCore runtime entrypoint
- `services/agent-runtime/runtime/frogbot_runtime/` - production-only runtime source packaged for AgentCore
- `services/agent-runtime/runtime/frogbot_runtime/capability_contract.py` - reviewed execution allowlist and capability validation
- `agentcore/agentcore.json` - AgentCore source-of-truth configuration
- `apps/froggybot-apple/` - primary shared SwiftUI app, Apple tests, and release scripts
- `apps/froggybot/src/` - preserved Expo browser routes, screens, and legacy reference implementation
- `packages/froggybot-contract/` - shared types and generated HTTP route contract
- `packages/froggybot-client/` - headless API client, response validation, state reconciliation, and presentation models
- `packages/froggybot-expo-client/` - Expo platform adapters and controller hooks
- `packages/froggybot-preview/` - development-only in-memory API implementation, excluded from production bundles
- `packages/frogbot-transcription/` - reusable on-device transcription module and Swift core
- `apps/froggybot-browser-viewer/` - independently built disposable AgentCore Live View shell
- `services/froggybot-api/` - independently verified and deployed application backend package
- `services/froggybot-api/amplify/backend.ts` - Cognito, API, DynamoDB, SQS, and Lambda infrastructure
- `services/froggybot-api/amplify/functions/api/api-contract.json` - single authored application HTTP route contract
- `services/froggybot-api/amplify/functions/shared/connection_providers.py` - public-safe connection provider manifest
- `services/froggybot-api/amplify/functions/api/bot_roles.py` - Chief's protected role and reserved branding, not its bot configuration
- `services/froggybot-api/amplify/functions/` - authenticated API, shared domain logic, and AgentCore worker
- [FroggyBot Skills](https://github.com/tmoreton/frogbot-skills) - the only source for public bot templates, skill instructions, and external tool schemas
