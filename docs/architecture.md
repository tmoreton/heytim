# FrogBot architecture

This repository deliberately has three product boundaries:

```text
apps/mobile/        User experience and its serverless application backend
app/FrogBot/        One AgentCore runtime shared by every FrogBot personality
agentcore/           Declarative AgentCore infrastructure and gateway schemas
```

## Mobile application

`apps/mobile/src/app` contains Expo Router route shells only. Product behavior belongs under
`src/features`, reusable visual primitives under `src/components`, and AWS/API adapters under
`src/lib`. The signed-in chat is composed from a drawer, header, message list, composer, and
focused bot/group/skill editors. Web and iOS use the same feature code.

The public website is the static `/` route. `/invite` previews a share link before opening the app
or sign-up experience. `/app` hosts the authenticated product. Development builds may use
`/app?preview=1` to exercise the complete UI without calling AWS; production builds ignore that
flag.

## Application backend

Amplify owns Cognito and the application-facing AWS resources. One small HTTP API Lambda keeps
deployment and permissions simple for this stage of the product. Domain-heavy, independently
testable behavior lives under `amplify/functions/shared`; the API handler validates ownership and
persists state, while the SQS worker invokes AgentCore and sends final-response notifications.

Daily and weekly bot tasks are stored with the user's other application data. Each task has one EventBridge Scheduler
schedule that sends only stable identifiers to the existing SQS queue. The worker reloads the current task and bot at
execution time, creates an idempotent scheduled chat turn, and then follows the same agent and notification path as a
person-started message. Scheduler retries use the existing dead-letter queue, and schedule names contain hashes rather
than user identifiers.

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

Group rounds use one SQS step per bot. Each later bot receives the group roster, people, shared
transcript, and completed replies from earlier bots. A group/bot/session tuple provides stable
AgentCore isolation while preserving that bot's memory inside the group.

## Agent runtime

`app/FrogBot/main.py` is only the AgentCore transport adapter. `frogbot_runtime/request.py`
normalizes untrusted invocation payloads, `configuration.py` builds per-bot and per-group
instructions, and `capabilities.py` assembles only the tools and skills enabled for that bot.
Stan and Strands stay behind this boundary so the mobile/API layers do not duplicate agent logic.

Executable community code is not accepted. Skills are versioned instructions plus approved tool
references; secrets and executable integrations stay in reviewed AgentCore Gateway targets.

## Invariants

- `agentcore/agentcore.json` is the source of truth for AgentCore resources; generated CDK is not.
- Existing CDK construct IDs and resource names are stable because renaming them can replace data.
- Every authenticated read/write verifies ownership or group membership server-side.
- Invitation tokens are random, time-limited, and stored as hashes for sign-up validation.
- A bot can receive only the reviewed tools and version-pinned skills in its saved configuration.
- Agent jobs are retried through SQS and failed permanently only after the configured retry limit.
- Scheduled executions are idempotent by schedule execution ID, use IANA timezones, and never embed bot prompts in EventBridge.
- User-visible notifications are queued only after the final answer, never for thinking updates.

## Verification

Run the complete local checks before a deployment:

```bash
agentcore validate

cd app/FrogBot
uv run ruff check .
uv run pytest -q

cd ../../apps/mobile
npm run verify
npm run build:web
uvx ruff check amplify/functions
uvx bandit -q -r amplify/functions -x amplify/functions/tests
```

The highest-value next production hardening steps are an authenticated API end-to-end test in CI,
CloudWatch alarms for the dead-letter queue and Lambda failures, and idempotency leases before any
future tool is allowed to perform irreversible external actions.
