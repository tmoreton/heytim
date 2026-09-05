# FroggyBot capability-parity roadmap

This board separates code that is complete in the repository from functionality that is live in AWS.
Nothing is considered production-complete until the deployment and authenticated end-to-end checks pass.

## Competitive position — September 2026

FroggyBot already has the core persistent-team model: named bots, scoped memory, reusable skills,
reviewed tools, recurring work, human-and-bot group chats, native artifacts, and mobile/web continuity.
That foundation remains valuable, but it is no longer full Grok Bot parity. Grok Bot now also exposes
persistent cloud computers, autonomous bot-to-bot handoffs, parallel work, event-triggered routines,
teach-by-demonstration, computer preview/takeover, broad connectors, and structured inline results.
See the official [Grok Bot overview](https://docs.x.ai/grok-bot/overview),
[design explanation](https://x.ai/news/designing-grok-bot), and
[skills and routines guide](https://docs.x.ai/grok-bot/skills-routines-and-automations).

The clearest market opening is not another general assistant. ChatGPT is
[retiring group chats](https://help.openai.com/en/articles/12703475-group-chats-in-chatgpt), while Claude
concentrates skills, connectors, sub-agents, and schedules inside
[plugins and Cowork](https://support.claude.com/en/articles/13837440-use-plugins-in-claude). Poe supports
[multi-entity bot conversations](https://creator.poe.com/docs/server-bots/server-bots-functional-guides),
but its primary product model remains a creator platform for individual bots. FroggyBot can own the
more specific promise: multiple people and multiple persistent AI specialists collaborating in one
clear, trustworthy room.

### Recommended product sequence

1. **Shared working context:** allow group attachments, shared reference files, and room instructions so
   a team has durable project context instead of chat history alone.
2. **Useful integrations:** start with one coherent productivity suite—email, calendar, and cloud files—then
   add read actions, explicit write approvals, revocation, and audit history before expanding providers.
3. **Triggers and resumable approvals:** add incoming-event and webhook triggers, a run inbox, and approval
   requests that can safely pause and resume scheduled or group work.
4. **Real delegation:** let a coordinator assign independent work to specialists in parallel, preserve each
   contribution, and synthesize one final answer without making the person manage a workflow graph.
5. **Visible trust:** let people review or remove remembered facts, inspect sources and tool actions, and see
   which bot contributed each decision to a final result.
6. **Learn from successful work:** first offer “save this process as a skill or routine” from a completed
   conversation. Add browser teach-by-demonstration only after the text-based loop proves demand.

### Deliberately defer

- A general-purpose persistent cloud desktop and live takeover. It adds major security, support, and cost
  surface; reviewed connectors plus the existing browser/code sessions cover the near-term product promise.
- An unrestricted public bot or executable-skill marketplace. Curated, version-pinned, instruction-only
  skills are a stronger trust differentiator.
- Video generation, entertainment companions, and a broad model picker. They do not strengthen collaborative
  team outcomes.
- Full enterprise administration before a design partner supplies concrete role, identity, retention, and
  audit requirements.

## Critical foundation — implemented and deployed

- Permanent account deletion, Cognito removal, active-share revocation, user-file version deletion, and
  AgentCore memory cleanup
- Durable SQS processing with conditional work leases, idempotent scheduled turns, cancellation, retries,
  and a dead-letter queue
- Private ownership checks for bots, chats, groups, files, skills, and invitations
- Encrypted queues, topics, application logs, and audit storage; API access logs, X-Ray, alarms, and a
  service dashboard
- AgentCore telemetry retains operational spans and token/latency signals while redacting system prompts,
  user messages, model responses, tool payloads, and inline attachment bytes
- Dependency audit coverage for the mobile app, Amplify backend, AgentCore runtime, and generated CDK app

## Priority 1: continuity and user control — implemented and deployed

- User-scoped long-term preferences and facts, plus conversation-scoped summaries, in AgentCore Memory
- Stable two-hour browser and code-interpreter sessions that reconnect after a runtime process restart
- Per-turn approval for interactive browser work; scheduled and group work cannot bypass approval
- One-hour model prompt/tool caching and bounded conversation history

## Priority 2: core product parity — implemented and deployed

- Direct-chat image and document attachments through a private, versioned file bucket
- Short-lived, size-constrained uploads with server-side verification and ownership-checked downloads
- Downloadable text, Markdown, CSV, JSON, and HTML artifacts generated by a FroggyBot
- Cleanup of partial generated files on retries, failures, and cancelled completions
- Daily, weekday, weekly, and monthly routines with pause and run-now controls

## Priority 3A: private integration foundation — implemented

- Add a private HTTPS MCP server directly in the app without a catalog pull request
- Keep each connection and credential scoped to its owner
- Store credentials in Secrets Manager and resolve them only inside the runtime
- Support unauthenticated servers, bearer tokens, and custom API-key headers
- Require per-turn approval for connections that may change external data
- Strip private connections and dependent skills from bot and skill shares

## Priority 3B: provider shortcuts — requires product inputs

- Select the first credentialed providers and define whether each integration is read-only or can change
  external state
- Supply provider applications, credentials, redirect URLs, and least-privilege scopes
- Add a separate approval policy for every external write action; a broad connector must not inherit the
  browser approval implicitly
- Run provider-specific revocation, token-expiry, retry, and audit tests before exposing a connector

Suggested first wave: Google Calendar, Google Drive and documents, maps and places, Notion, email, and Slack.
Add provider-specific OAuth shortcuts only when they improve on the generic MCP connection flow and customer
demand justifies their additional maintenance.

## Priority 4A: richer creation — implemented and deployed

- Native PDF, DOCX, XLSX, and PowerPoint output without encoding binary data through the model
- Original PNG image generation with an active Stable Image Core model
- Private per-user storage, typed download metadata, generated-file limits, retry cleanup, and formula-safe
  spreadsheet cells
- Local visual checks for every native format, direct live runtime checks for every format, and an authenticated
  app-to-worker-to-AgentCore-to-download PDF test in AWS

## Priority 4B: hardening complete; enterprise product inputs remaining

- Organization workspaces, roles, SSO, centralized connector administration, retention policies, exports,
  and legal/audit workflows
- Initial service-level objectives, alarm response procedures, recovery runbooks, API tail-latency alarms,
  Lambda throttle alarms, and a consolidated alarm-status dashboard are implemented and deployed
- Authenticated workflows, concurrency/load testing, recovery drills, and cost budgets are implemented,
  deployed, and production-verified

## Production gate

1. **Complete:** deployed through `FrogBotDeploymentRole`; the bootstrap access key was removed after use.
2. **Complete:** AgentCore runtime, memory, gateway, browser, and code-interpreter resources are deployed and
   report ready.
3. **Complete:** the current runtime ARN and memory ID are wired into the deployed Amplify backend.
4. **Complete:** authenticated sign-in/bootstrap, group history, native artifact creation and download,
   attachment upload/read, schedules, share revocation, approval allow/deny, cancellation, and permanent
   account deletion passed in AWS. The destructive checks used only disposable accounts.
5. **Complete:** a 40-request, concurrency-8 authenticated production run completed with zero failures and
   2.12-second p99 latency against the five-second objective.
6. **Complete:** DynamoDB point-in-time restore and S3 version restore passed; the isolated recovery table,
   synthetic objects, and disposable accounts were removed.
7. **Complete in AWS, external delivery pending:** the encrypted monthly cost budget has 50% and 80% actual
   notifications plus a 100% forecast notification wired to the service alarm topic. A monitored team email
   or incident-system destination still needs to be supplied, subscribed, and confirmed.

## Decisions required for the remaining parity scope

- **Integrations:** choose the calendar, email, files, chat, and task providers; supply provider applications,
  credentials, redirect URLs, scopes, and which operations may write external data.
- **Enterprise:** define workspace roles, identity provider and SSO protocol, retention periods, export format,
  legal-hold rules, and audit recipients before those controls can be implemented safely.
- **Operations delivery:** provide a monitored team address or incident-system endpoint for the encrypted
  alarm topic. A personal mailbox will not be inferred from an existing user account.
