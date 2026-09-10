# FroggyBot

FroggyBot is a small iOS-first AI team app. One Amazon Bedrock AgentCore runtime serves every bot;
each bot supplies its own prompt, enabled tools, enabled skills, and stable session ID. The Expo app
provides a Grokbot-style chat interface, while Amplify provisions passwordless email-code sign-in and the
serverless chat API.

## Repository layout

```text
apps/froggybot/          Expo iOS/web product and its Amplify backend
services/agent-runtime/  AgentCore runtime and runtime-only modules
agentcore/               Declarative AgentCore resources and gateway schemas
docs/                    Tutorial, architecture, and operations guides
```

`apps/froggybot` is an independent Expo project, so run Expo, EAS, Amplify, and npm commands from
that directory. `services/agent-runtime` is referenced by `agentcore.json`, which remains the source of truth
for deployed agent resources. The older internal name `FrogBot` remains in AWS resource identities because
renaming it would replace deployed infrastructure;
user-facing product copy uses `FroggyBot`. The maintained boundary and request-flow
guide is in [`docs/architecture.md`](docs/architecture.md), and the remaining product work is tracked
in [`docs/grokbot-parity-roadmap.md`](docs/grokbot-parity-roadmap.md).

## Architecture

```text
Expo app
  |-- Cognito email code sign-in
  |-- Apple on-device speech-to-text
  |-- authenticated HTTP API
        |-- DynamoDB: bot configs, chats, files, groups, tasks, tokens, and invites
        |-- Secrets Manager: per-user private MCP credentials
        |-- S3: private user uploads and generated artifacts
        |-- EventBridge Scheduler: daily, weekday, weekly, and monthly tasks
        |-- SQS: durable agent jobs
              |-- Lambda worker
                    |-- AgentCore Runtime -> Strands + Stan
                    |     |-- AgentCore Memory -> preferences, facts, summaries
                    |     |-- persistent browser and code-interpreter sessions
                    |-- AgentCore Gateway -> reviewed external tools
                    |-- Expo Push Service -> APNs
```

The request path is asynchronous so a long agent turn is not limited by an HTTP request timeout.
The app polls only while a response is pending. DynamoDB is the source of truth for chat history;
the worker derives stable, non-PII AgentCore actor and session IDs. Direct chats use a private user actor
and per-bot session. Groups use an isolated group actor and one shared memory session, so a bot never
imports its owner's private memory into a room. In a team round, bots reply
one at a time so every later bot sees the people, the full bot roster, and earlier bot contributions.
The first bot coordinates the round, specialists add distinct perspectives, and the coordinator returns
one final synthesized team answer.

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
- Per-bot name, description, prompt, color, tools, and version-pinned skills
- Shared groups with a pinned owner-editable notebook, reviewable learned group memory, one-link passwordless participation, single-bot replies, and ordered team collaboration rounds
- Inline reports, drafts, and next steps in chat, with downloadable documents when explicitly requested
- Owner-controlled chat, bot, and group deletion with pending-work protection and invite revocation
- A skill library for creating, editing, and sharing reusable ways of working
- Chief as the protected built-in, plus eight installable bot templates and eight focused public skills from the dynamically refreshed catalog
- Private HTTPS MCP connections with per-user bearer-token or API-key credentials
- Bot snapshots, conversation snapshots, and live group invitations with 30-day links
- Scoped AgentCore memory: private user preferences/facts, per-bot summaries, and isolated shared group preferences/facts/summaries, with in-app creation, review, editing, and forgetting
- Explicit clear-chat choices for preserving or forgetting conversation memory; bot and group deletion also enqueue matching memory cleanup
- Persistent two-hour browser and code-interpreter sessions; browser use requires one-time approval for each turn
- DynamoDB persistence, encrypted queues and topics, retries, work leases, cancellation, and a dead-letter queue
- CloudTrail audit logs, API access logs, X-Ray tracing, service alarms, and a CloudWatch dashboard
- Permanent in-app account deletion, including active share revocation and versioned user-file deletion
- Published service objectives, alarm response, and recovery procedures in [`docs/operations.md`](docs/operations.md)
- Expo over-the-air updates on the production channel, automatically published after changes land on `main`
- A local preview mode that works before AWS is connected

## Local preview

The preview uses sample data and does not call AWS.

```bash
cd apps/froggybot
npm install
npm run ios
```

Choose **Preview the app** on the welcome screen. `npm run web` is useful for quick layout checks.

## Deploy to AWS

Use an IAM Identity Center or least-privilege deployment role. Do not deploy with AWS account root
credentials.

### 1. Deploy the agent runtime

From the repository root:

```bash
agentcore validate
agentcore deploy --target development
agentcore status --target development --runtime FrogBot --json
agentcore status --target development --type memory --json
```

The development target is account `188757775631` in `us-east-1`. Confirm that both the runtime and
memory are ready, then copy the deployed runtime ARN from the status output. Model selection is defined only in
`agentcore/agentcore.json`: OpenRouter uses DeepSeek V4.1 Flash with GLM 5.3 as a bounded pre-response fallback.
CDK synthesis refuses uncommitted source so production releases
come from a reproducible Git snapshot. Required provider access must be available in the configured accounts and regions. The private file bucket has
the deterministic name `frogbot-user-files-188757775631-us-east-1`; when adding another deployment
target, update `FROGBOT_FILES_BUCKET` and the attachment policy in `agentcore/` for that target.

### 2. Optional future phone sign-in

Request and register a US toll-free origination number in AWS End User Messaging SMS in `us-east-1`. While the
account is in the SMS sandbox, messages can reach only verified test destinations and only after an origination
identity exists. Request SMS production access before inviting general TestFlight users. US carrier registration
also requires a documented opt-in flow, public privacy policy and terms, and accurate legal business details.

### 3. Deploy the app backend

```bash
cd apps/froggybot
nvm use
npm install
npm run backend:install
export FROGBOT_AGENT_RUNTIME_ARN='arn:aws:bedrock-agentcore:us-east-1:188757775631:runtime/REPLACE_ME'
export FROGBOT_MEMORY_ID='FrogBot_FrogBotMemory-REPLACE_ME'
export FROGBOT_GOOGLE_OAUTH_SECRET_ARN='arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:frogbot/oauth/google-REPLACE_ME'
npm run sandbox -- --once --identifier frogbot --profile YOUR_AWS_PROFILE
```

Amplify writes the real Cognito and API values to `apps/froggybot/amplify_outputs.json`. Keep the sandbox
running during active development by omitting `--once`, then start the app in another terminal with
`npm run ios`. Expo SDK 57 requires Node 22.13 or newer; the pinned Node 22 line also avoids the
Amplify CLI incompatibility seen under Node 25.

Set `FROGBOT_AGENT_RUNTIME_QUALIFIER` only if the runtime should use a qualifier other than
`DEFAULT`. Deploy with an IAM Identity Center or least-privilege role; the deployment runbook must
never use AWS account-root credentials.

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

Users can create instruction-only skills inside the app, attach only the tools that skill needs, and share a
30-day installation link. Shared skills are read-only for the recipient and require an explicit trust confirmation.
They can also connect a private HTTPS MCP server with no authentication, a bearer token, or an API-key header.
The credential is encrypted per user in Secrets Manager and fetched only when the runtime invokes that connection;
it never enters the app bundle, a skill document, a prompt, or a shared link. Managed FroggyBot tools still use
narrow AgentCore Gateway targets. The public repository includes validation automation, contribution templates,
and separate request forms for public skills and tool proposals.

Gmail uses Google's remote MCP server through a first-class OAuth connection. Each user grants their own account
read-email and create-draft access; refresh tokens stay in a per-user Secrets Manager secret. The runtime exposes only
search, read, list, and draft tools, so it cannot send, delete, relabel, archive, or mark email. Gmail access is treated
as interactive because email is untrusted input, which keeps it out of groups and unattended schedules.

The declarative AgentCore gateway currently exposes only the reviewed web-search connector. Add a provider credential
and gateway target to `agentcore/agentcore.json` together; do not describe a provider as available until the target is
deployed, ready, and visible in the reviewed catalog.

## Verification

```bash
scripts/verify.sh
```

See [the verification guide](docs/verification.md) for prerequisites, focused commands, CI coverage, and deployed checks.

## App releases and websites

The production EAS build profile listens to the `production` update channel. The GitHub Actions workflow at
`.github/workflows/eas-update.yml` publishes both an EAS Update and the Expo desktop web app after every push to
`main`; the Expo credential is stored as the repository secret `EXPO_TOKEN`. Expo's fingerprint runtime policy
prevents an update from reaching an incompatible native build. The web app at `https://app.froggybot.com` mirrors
the passwordless iOS experience and owns application and invite routes.

The separate [FroggyBot Skills](https://github.com/tmoreton/frogbot-skills) repository owns the public homepage,
library, contribution guide, and legal pages at `https://froggybot.com`. Its GitHub Pages workflow publishes on
every catalog or website change, independently of the app release cycle. Public `/invite` links preserve their
query string and hand off to the Expo app subdomain.

## Key locations

- `services/agent-runtime/runtime/main.py` - small AgentCore runtime entrypoint
- `services/agent-runtime/runtime/frogbot_runtime/` - production-only runtime source packaged for AgentCore
- `services/agent-runtime/runtime/frogbot_runtime/capability_contract.py` - reviewed execution allowlist and capability validation
- `agentcore/agentcore.json` - AgentCore source-of-truth configuration
- `apps/froggybot/src/features/` - authentication, invitations, chat UI, and editors
- `apps/froggybot/amplify/backend.ts` - Cognito, API, DynamoDB, SQS, and Lambda infrastructure
- `apps/froggybot/amplify/functions/api/bot_roles.py` - Chief's protected role and reserved branding, not its bot configuration
- `apps/froggybot/amplify/functions/` - authenticated API, shared domain logic, and AgentCore worker
- [FroggyBot Skills](https://github.com/tmoreton/frogbot-skills) - the only source for public bot templates, skill instructions, and external tool schemas
