# FrogBot

FrogBot is a small iOS-first AI team app. One Amazon Bedrock AgentCore runtime serves every bot;
each bot supplies its own prompt, enabled tools, enabled skills, and stable session ID. The Expo app
provides a Grokbot-style chat interface, while Amplify provisions passwordless SMS sign-in and the
serverless chat API.

## Architecture

```text
Expo app
  |-- Cognito SMS code sign-in
  |-- authenticated HTTP API
        |-- DynamoDB: bot configs, conversations, expiring shares
        |-- SQS: durable agent jobs
              |-- Lambda worker
                    |-- AgentCore Runtime
                          |-- Strands + Stan
```

The request path is asynchronous so a long agent turn is not limited by an HTTP request timeout.
The app polls only while a response is pending. DynamoDB is the source of truth for chat history;
the worker derives a stable AgentCore session ID from the user and bot IDs.

## What is included

- Phone-only Cognito sign-up and sign-in with a six-digit SMS code
- Responsive chat UI with a collapsible bot list
- Per-bot name, description, prompt, color, tools, and skills
- Three starter bots and three packaged Stan skills
- Bot-only and bot-plus-conversation sharing with 30-day links
- DynamoDB persistence, an encrypted SQS queue, retries, and a dead-letter queue
- A local preview mode that works before AWS is connected

## Local preview

The preview uses sample data and does not call AWS.

```bash
cd frogPhone
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

### 2. Prepare passwordless SMS

Configure an origination identity in AWS End User Messaging SMS in `us-east-1`. While the account is
in the SMS sandbox, add each test phone as a verified destination. Request SMS production access before
inviting general TestFlight users.

### 3. Deploy the app backend

```bash
cd frogPhone
nvm use
npm install
npm run backend:install
export FROGBOT_AGENT_RUNTIME_ARN='arn:aws:bedrock-agentcore:us-east-1:188757775631:runtime/REPLACE_ME'
npm run sandbox -- --once --identifier frogbot --profile YOUR_AWS_PROFILE
```

Amplify writes the real Cognito and API values to `frogPhone/amplify_outputs.json`. Keep the sandbox
running during active development by omitting `--once`, then start the app in another terminal with
`npm run ios`. Expo SDK 57 requires Node 22.13 or newer; the pinned Node 22 line also avoids the
Amplify CLI incompatibility seen under Node 25.

Set `FROGBOT_AGENT_RUNTIME_QUALIFIER` only if the runtime should use a qualifier other than
`DEFAULT`.

## Verification

```bash
agentcore validate
cd frogPhone
npm run typecheck
npm run backend:typecheck
npm run lint
npx expo-doctor
```

## Key locations

- `app/FrogBot/main.py` - AgentCore entrypoint and per-bot Stan configuration
- `app/FrogBot/skill_catalog/` - selectable bot skills
- `agentcore/agentcore.json` - AgentCore source-of-truth configuration
- `frogPhone/src/features/` - authentication and chat UI
- `frogPhone/amplify/backend.ts` - Cognito, API, DynamoDB, SQS, and Lambda infrastructure
- `frogPhone/amplify/functions/` - authenticated API and AgentCore worker
