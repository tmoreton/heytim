# FrogBot

FrogBot is a small iOS-first AI team app. One Amazon Bedrock AgentCore runtime serves every bot;
each bot supplies its own prompt, enabled tools, enabled skills, and stable session ID. The Expo app
provides a Grokbot-style chat interface, while Amplify provisions passwordless email-code sign-in and the
serverless chat API.

## Repository layout

```text
apps/mobile/        Expo app and the Amplify backend it calls
app/FrogBot/        AgentCore runtime entrypoint and its runtime-only modules
agentcore/           Declarative AgentCore resources and reviewed gateway schemas
docs/                Operational forms and architecture notes
```

`apps/mobile` is an independent Expo project, so run Expo, EAS, Amplify, and npm commands from
that directory. `app/FrogBot` remains at AgentCore's conventional code location; `agentcore.json`
is still the source of truth for deployed agent resources. The maintained boundary and request-flow
guide is in [`docs/architecture.md`](docs/architecture.md).

## Architecture

```text
Expo app
  |-- Cognito email code sign-in
  |-- Apple on-device speech-to-text
  |-- authenticated HTTP API
        |-- DynamoDB: bot configs, direct chats, shared groups, device tokens, expiring invites
        |-- SQS: durable agent jobs
              |-- Lambda worker
                    |-- AgentCore Runtime -> Strands + Stan
                    |-- AgentCore Gateway -> reviewed external tools
                    |-- Expo Push Service -> APNs
```

The request path is asynchronous so a long agent turn is not limited by an HTTP request timeout.
The app polls only while a response is pending. DynamoDB is the source of truth for chat history;
the worker derives a stable AgentCore session ID from the user and bot IDs. In a team round, bots reply
one at a time so every later bot sees the people, the full bot roster, and earlier bot contributions.

## What is included

- Email-only Cognito sign-up and sign-in with one-time codes while the US SMS sender is registered
- Responsive chat UI with a collapsible bot list
- Push notification when an agent reply completes, with tap-to-open navigation
- Apple on-device speech-to-text in the message composer without saved audio
- Per-bot name, description, prompt, color, tools, and version-pinned skills
- Shared groups with multiple people and FrogBots, invite links, single-bot replies, and ordered team collaboration rounds
- Owner-controlled chat, bot, and group deletion with pending-work protection and invite revocation
- A skill library for creating, editing, and sharing reusable ways of working
- Three starter bots, three reviewed starter skills, and a dynamically refreshed capability catalog
- Bot snapshots, conversation snapshots, and live group invitations with 30-day links
- DynamoDB persistence, an encrypted SQS queue, retries, and a dead-letter queue
- Expo over-the-air updates on the production channel, automatically published after changes land on `main`
- A local preview mode that works before AWS is connected

## Local preview

The preview uses sample data and does not call AWS.

```bash
cd apps/mobile
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
```

The development target is account `188757775631` in `us-east-1`. Copy the deployed runtime ARN from
the status output. The runtime uses Claude Sonnet 4.5, so model access must be available in that
account and region.

### 2. Optional future phone sign-in

Request and register a US toll-free origination number in AWS End User Messaging SMS in `us-east-1`. While the
account is in the SMS sandbox, messages can reach only verified test destinations and only after an origination
identity exists. Request SMS production access before inviting general TestFlight users. US carrier registration
also requires a documented opt-in flow, public privacy policy and terms, and accurate legal business details.

### 3. Deploy the app backend

```bash
cd apps/mobile
nvm use
npm install
npm run backend:install
export FROGBOT_AGENT_RUNTIME_ARN='arn:aws:bedrock-agentcore:us-east-1:188757775631:runtime/REPLACE_ME'
npm run sandbox -- --once --identifier frogbot --profile YOUR_AWS_PROFILE
```

Amplify writes the real Cognito and API values to `apps/mobile/amplify_outputs.json`. Keep the sandbox
running during active development by omitting `--once`, then start the app in another terminal with
`npm run ios`. Expo SDK 57 requires Node 22.13 or newer; the pinned Node 22 line also avoids the
Amplify CLI incompatibility seen under Node 25.

Set `FROGBOT_AGENT_RUNTIME_QUALIFIER` only if the runtime should use a qualifier other than
`DEFAULT`.

## Skills and tools

The reviewed public catalog lives in [frogbot-capabilities](https://github.com/tmoreton/frogbot-capabilities).
Skill releases use immutable Git tags, and every bot stores the exact skill version it selected. Updating a skill
therefore does not silently change an existing bot or a previously shared bot. Catalog refreshes add or remove
listings without deleting old versions that existing bots still need.

Users can create instruction-only skills inside the app, attach only the tools that skill needs, and share a
30-day installation link. Shared skills are read-only for the recipient and require an explicit trust confirmation.
Executable code never comes from a community skill: external APIs are exposed as narrow, read-only AgentCore
Gateway targets with credentials held on AWS, not in the Expo app or skill repository.

The X and YouTube skill packs and their restricted OpenAPI schemas are ready in the catalog. They remain hidden
from users until their server-side credentials and gateway targets are deployed. This keeps the live tool picker
honest and prevents a bot from being saved with a tool that cannot run.

## Verification

```bash
agentcore validate
cd apps/mobile
npm run verify
```

## Mobile releases

The production EAS build profile listens to the `production` update channel. The GitHub Actions workflow at
`.github/workflows/eas-update.yml` publishes both an EAS Update and the static Expo website after every push to
`main`; the Expo credential is stored as the repository secret `EXPO_TOKEN`. Expo's fingerprint runtime policy
prevents an update from reaching an incompatible native build. On web, `/` is the public landing page and `/app`
opens the same passwordless FrogBot experience used by the native app.

## Key locations

- `app/FrogBot/main.py` - small AgentCore runtime entrypoint
- `app/FrogBot/frogbot_runtime/` - request validation and per-bot capability assembly
- `app/FrogBot/skill_catalog/` - selectable bot skills
- `agentcore/gateway/` - reviewed external tool schemas
- `agentcore/agentcore.json` - AgentCore source-of-truth configuration
- `apps/mobile/src/features/` - authentication, invitations, chat UI, and editors
- `apps/mobile/amplify/backend.ts` - Cognito, API, DynamoDB, SQS, and Lambda infrastructure
- `apps/mobile/amplify/functions/` - authenticated API, shared domain logic, and AgentCore worker
- [frogbot-capabilities](https://github.com/tmoreton/frogbot-capabilities) - versioned public skill and tool catalog
