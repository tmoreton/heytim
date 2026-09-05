# FroggyBot architecture

This repository deliberately has three product boundaries:

```text
apps/mobile/        User experience and its serverless application backend
app/FrogBot/        One AgentCore runtime shared by every FroggyBot personality
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

Amplify owns Cognito and the application-facing AWS resources. One HTTP API Lambda keeps deployment
and permissions simple, while focused modules under `amplify/functions/api` own each application
domain. The API handler only routes requests. Shared rules live under `amplify/functions/shared`.
The SQS worker uses the same pattern: its handler routes jobs, and focused worker modules claim work,
invoke AgentCore, persist results, and send final-response notifications.

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

Group rounds use one SQS step per bot. Each later bot receives the group roster, people, shared
transcript, and completed replies from earlier bots. A group/bot/session tuple provides stable
AgentCore isolation while preserving that bot's memory inside the group.

## Agent runtime

`app/FrogBot/main.py` is only the AgentCore transport adapter. `frogbot_runtime/request.py`
normalizes untrusted invocation payloads, `configuration.py` builds per-bot and per-group
instructions, and `capabilities.py` assembles only the tools and skills enabled for that bot.
Stan and Strands stay behind this boundary so the mobile/API layers do not duplicate agent logic.
AgentCore OpenTelemetry remains enabled for errors, timings, token usage, and tool activity, while both the
AWS model instrumentation and Strands tracer redact prompt, response, tool payload, and attachment content.

Direct conversations use stable, hashed AgentCore actor and session identifiers. AgentCore Memory
recalls user preferences and facts across bots and session summaries within a conversation. Browser
and code-interpreter sandboxes are named by the stable conversation ID and reconnect to READY sessions
after runtime process replacement. Generated files use a turn-scoped S3 prefix and are attached to the
completed reply only after the worker verifies and records them.

Executable community code is not accepted. Skills are versioned instructions plus approved tool
references; secrets and executable integrations stay in reviewed AgentCore Gateway targets.

## Invariants

- `agentcore/agentcore.json` is the source of truth for AgentCore resources; generated CDK is not.
- Existing CDK construct IDs and resource names are stable because renaming them can replace data.
- Every authenticated read/write verifies ownership or group membership server-side.
- Invitation tokens are random, time-limited, and stored as hashes for sign-up validation.
- A bot can receive only the reviewed tools and version-pinned skills in its saved configuration.
- Agent jobs are retried through SQS and failed permanently only after the configured retry limit.
- One worker owns a turn at a time through a renewable lease; completion is conditional on that ownership.
- Scheduled executions are idempotent by schedule execution ID, use IANA timezones, and never embed bot prompts in EventBridge.
- Attachments and generated artifacts are bound to the current user's hashed storage prefix.
- Interactive tools cannot run in scheduled or group work, and direct browser turns require explicit approval.
- Account deletion revokes active shares, cancels pending work, deletes user data and all S3 versions, and disables the Cognito identity.
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

The remaining parity work is tracked by product capability rather than infrastructure severity:
credentialed third-party connectors and enterprise identity/data governance. Production-scale authenticated
end-to-end, load, cost-control, and recovery checks are complete. The remaining features require provider
credentials or product policy before they can be safely enabled. Operational targets and recovery procedures are maintained in
[`operations.md`](operations.md).
