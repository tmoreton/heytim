# HeyTim implementation plan: openness and autonomous work

**Date:** September 18, 2026
**Status:** Milestones 1–4 released in v6.2.5. Live room and GitHub App pilots pending.
**Basis:** [Grok Bot and openness audit](grokbot-openness-audit-2026-09-18.md) and this checkout.

## Implementation started

The first backend slice now has versioned room run identities, parallel dispatch for up to three contributors, a terminal-state synthesis barrier, and cancellation of queued steps. A saved room decision or signed GitHub issue-opened event can trigger an enabled routine with stable occurrence IDs; owner-owned interactive bots pause for exact-action approval. The GitHub route requires webhook secret configuration and a deployed replay test. Bot and room workspaces support scoped files, limits, later-message selection, short-lived export links, and explicit sync into Code Interpreter. The compatibility and approval boundary is recorded in [the workflow decision record](adr-workflow-runs-and-workspaces-2026-09-18.md). The native app now has run cancellation, a room routine editor/preview/run list, a workspace file view, a composer picker for saved files, and exact-action review. A complete portable archive/import remains open work.

## Recommendation

Build one portable run format for chat, scheduled work, event routines, and bot handoffs. Use it in the hosted product first, then support the same bot recipes and data archive in a self-hosted edition. Deliver the three new capabilities in this order:

1. **Parallel, visible specialist handoffs in rooms.** This gives the clearest improvement to an existing workflow.
2. **Event-triggered routines with resumable action approval.** Start with one internal event and one external provider event.
3. **A durable workspace, then evaluate a full cloud computer.** Persistent files and browser profiles are useful sooner; a single live desktop with browser and shell is a separate, larger product.

Do the portability work alongside these slices. In particular, define exportable recipes and a model policy before new workflow definitions become tied to AWS-specific fields. Avoid waiting for an entire self-hosted release to improve the hosted room.

## Starting point and constraints

| Area | What exists | Change required |
| --- | --- | --- |
| Team replies | `api/group_messages.py` creates lead, contributor, and synthesis messages; `worker/group_job.py` queues the next index only after the previous reply finishes. A generic Strands `subagent` tool also exists, but it is not a durable handoff to another named bot. | A bounded task graph, concurrent dispatch, a completion barrier, and an explicit handoff record. |
| Durable work | SQS, DynamoDB leases, retry handling, per-reply artifacts, background work polling, run-unit admission, and a run inbox already exist. | Reuse these mechanisms with run/task identities, terminal-state reconciliation, cancellation, and per-child accounting. |
| Routines | `api/schedules.py` and scheduled workers use EventBridge Scheduler to enqueue recurring bot or room work. | A versioned routine definition with a schedule or event trigger, verified event ingress, deduplication, filter testing, and a run record for each occurrence. |
| Approvals | Direct chat can pause a turn for approval. Room replies reject approval-gated tools; scheduled work cannot take interactive actions. | A specific proposed action that can be approved or denied after the run pauses, then resumed once with the same arguments. |
| Computer | Direct chats have AgentCore Browser live view, takeover, and optional saved login profiles. Code Interpreter and browser sessions have bounded lifetimes. The runtime has background coding jobs and scoped artifacts. Group browser use is explicitly rejected. | Durable file/workspace identity and lifecycle first; a full shared browser, terminal, filesystem, and live view needs a separate sandbox design and scope policy. |
| Openness | Prompts and memories can be edited; partial memory export exists. Model choice is deployment-wide OpenRouter configuration; no import or supported self-hosted path exists. | Versioned export/import, provider adapters, visible per-run model/cost, local deployment, and a license decision. |

The current private browser binding is keyed to an owner and bot. A room task must never silently inherit that binding, private credentials, or private memory. This should remain true when specialist tasks run concurrently.

## Shared contracts to define first

Add versioned, provider-neutral domain records. The names below are proposed API concepts, not a migration requirement for every historical row:

```text
Run        id, owner/scope, source (chat|schedule|event), occurrenceId,
           status, createdAt, deadline, budget, model receipt, task IDs
Task       id, runId, parentTaskId, bot recipe/version, assignment,
           dependency IDs, input snapshot, status, result, artifact IDs
Routine    id, target bot/room, prompt or recipe, trigger (schedule|event),
           event filter, action policy, enabled, last run
Workspace  id, owner/scope, storage location, retention, access policy,
           file manifest, optional computer session reference
Approval   id, run/task, exact tool + target + arguments digest, requester,
           approver, expiry, decision, one-use execution key
```

Keep AWS queue URLs, ARNs, browser session IDs, credential references, and signed links out of exported recipes. Store a snapshot of the bot recipe, allowed tools, room membership, and relevant context at run start; later edits should apply to the next run. A room run may read room context and deliberately shared artifacts. It may use a private connection only through an explicit owner-authorized binding for that room and action.

Use a narrow state machine: `PENDING → RUNNING → COMPLETE | ERROR | CANCELLED`, with `WAITING` for dependencies and `AWAITING_APPROVAL` for an exact action. Every transition needs conditional writes and an idempotency key. Keep existing SQS/DynamoDB execution initially; add Step Functions only if long waits and nested graphs make the conditional barrier hard to operate. AWS documents [Parallel states](https://docs.aws.amazon.com/step-functions/latest/dg/state-parallel.html) and [callback tokens](https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html) as options, but an immediate orchestration rewrite would add migration work before proving the product flow.

## Delivery slices

| Slice | Work and likely code areas | Done when | Relative effort |
| --- | --- | --- | --- |
| 0. Contracts and migration plan | Write an architecture decision record and versioned schemas in `api/api-contract.json`, `shared/`, and Swift models. Define room authorization, budget, retention, export, and cancellation semantics. | Existing direct and scheduled requests still run; the new records can be read by old clients without breaking them. | Small |
| 1. Explain and export | Bot “How it works” view; prompt/skill/tool/model receipt; archive export, preview, and import. Touch memory, sharing, artifact, schedule, catalog, website, and native UI paths. | A disposable account can export and restore bots, skills, memories, room decisions, chats, files, and paused routines without credentials. | Large |
| 2. Model choice | Adapter contract around `runtime/model/load.py`; bot/workspace model policy; capability checks; model and cost receipt; compatible custom endpoint. | A direct and room workflow run on two hosted providers and one local-compatible endpoint, with unsupported tools called out before execution. | Medium–large |
| 3. Parallel room handoffs | Extend `shared/group_chat.py`, `api/group_messages.py`, `worker/group_job.py`, `worker/handler.py`, runtime group instructions, usage controls, and room UI. | Chief dispatches a bounded set of specialists concurrently, shows their status and evidence, and synthesizes exactly once after all finish or time out. | Medium–large |
| 4. Resumable action approval | Tool interception and a durable approval request, approve/deny endpoints, pause/resume worker path, push/run inbox UI, and action audit. | A room or routine can request a precise write; approving executes only that saved action once, while denial/expiry ends it safely. | Large |
| 5. Event routines | Extend schedule definitions and API into routines; verified event adapter, rules, dedupe, retry/DLQ, run history, UI filter preview. | A room decision event and one GitHub issue event can each start an enabled routine once per provider event ID. | Medium–large |
| 6. Durable workspace | Workspace metadata, scoped file storage, list/download/delete/export, code-session mount or explicit file sync, lifecycle/quotas, client file view. | Files survive new code sessions and app restarts, remain within their owner/room scope, and leave with the workspace archive. | Medium–large |
| 7. Full computer decision spike | Prototype a single sandbox containing shell, Chromium, shared files, and live takeover; measure idle/resume, isolation, cost, and recovery. | Choose a platform only after one room can stop, resume, inspect, and delete its computer with no cross-room access. | Spike: small; production: extra large |
| 8. Self-host and managed plans | Local adapters for auth/storage/queue/memory, web client or configurable native endpoint, local model smoke path; hosted subscription entitlements, spend limits, cancellation/export. | The same recipe and archive round-trip between hosted and clean self-hosted installs; paid accounts see a clear allowance and limit. | Extra large |

“Small/medium/large” express sequencing risk, not a calendar commitment. The full computer and self-hosted release contain the largest infrastructure and support unknowns.

### Parallel bot handoffs

**First release:** retain Chief as coordinator. Alongside its short visible lead reply, it returns a structured assignment list with at most three specialist bot IDs, bounded tasks, and expected outputs. The server validates the schema, membership, bot ownership, tool grants, and run budget; writes child tasks; then dispatches them independently. All specialists receive the same immutable room snapshot and their own assignment. They do not consume one another's partially completed messages. Each writes a task result and scoped artifacts. A conditional completion barrier queues one synthesis when every child reaches a terminal state or a deadline; the synthesis includes failures and dissent rather than waiting forever.

Expose the graph in the room as “Chief → three specialists → synthesis,” with task status, answer, model, cost, artifacts, and a cancel control. Persist separate `Task` rows rather than relying on the display order of `GROUP_MESSAGE` rows. Keep a single final room answer. The current `group_history_from_items()` reads completed messages from the live transcript, so the worker needs an explicit snapshot and child-result input to prevent race-dependent prompts.

**Second release:** add named-bot `delegate_task` for a direct chat or routine to request another authorized bot asynchronously. Reuse the same task graph and inbox. Cap depth, fan-out, total tasks, time, and spend; reject cycles; carry caller identity and scope; never treat a bot's request as new permission. The existing generic `subagent` capability can remain a local reasoning tool, with a distinct label from a durable named-bot handoff.

Test duplicate SQS delivery, two children finishing together, late completion after timeout/cancel, missing bot or changed membership, partial failure, quota denial, background work pause, schedule-origin group runs, and artifact visibility. Require exactly one final synthesis and one usage charge per actual invocation.

### Event-triggered routines

Extend the current schedule UI/API into a `Routine` with `trigger.kind = schedule | event`; preserve existing schedule IDs and their occurrence deduplication during migration. An event occurrence carries `source`, `eventType`, `providerEventId`, `receivedAt`, trusted account/installation mapping, and a safe payload reference. An indexed subscription maps the trusted source/resource to candidate routines; each saved filter selects a room or bot and a prompt template. Imported event routines remain disabled until the new owner connects the source.

Build event ingress in layers:

1. Emit a first-party event when a room member saves a decision. It proves filtering, deduplication, and run history without an external webhook. Prevent a routine from retriggering itself through its own outputs.
2. Add one GitHub App webhook event, such as an issue opened in an explicitly selected repository. Verify the provider signature over the raw request, map the installation and repository to an authorized connection, and dedupe the delivery ID before enqueueing. Treat issue text as untrusted task data.
3. Normalize verified events and route them to the same worker as schedules. EventBridge event-pattern rules and a dedicated bus are useful if event sources expand; for the first two sources, an indexed subscription lookup plus the existing SQS queue may be simpler. In either case, retain a durable occurrence record, retries, a dead-letter queue, replay controls, and per-routine concurrency/spend caps. A conditional `(routineId, providerEventId)` write should create one run record despite duplicate delivery. External writes need their own idempotency key or a state check before retry. AWS documents [event patterns](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rules.html), [custom events](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-putevents.html), and [delivery retries/DLQs](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rule-retry-policy.html).

The routine editor should show a sample event, matched fields, chosen bot/room, tools, spend cap, and a dry-run preview. Require action-level approval for external writes unless a narrow, explicit policy permits a particular target and operation. Record whether a run was skipped, deduplicated, paused, completed, or failed. Do not grant an event payload authority to change the routine's instructions or permissions.

### Persistent workspace and full cloud computer

Define **workspace persistence** as files, artifacts, and selected browser profile data surviving individual execution sessions. Define **live computer** as one inspectable environment where shell, browser, filesystem, and takeover operate together. The current direct-chat Browser already has live view and saved login profiles, but it is scoped to one owner/bot and is not a room computer.

For the first milestone, keep files in an owner- or room-scoped durable store with a manifest and versioned export. Code Interpreter now supports customer-managed [S3 Files or EFS mounts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-filesystem-configurations.html) that persist across its sessions; evaluate these against an app-level S3 sync for cost, VPC, locking, and deletion behavior. The mount option requires VPC access; the current `agentcore/agentcore.json` runtime uses `PUBLIC` networking and a generic Code Interpreter connection, so verify that the maintained schema can describe the needed tool configuration before choosing this path. AgentCore Runtime has separate [filesystem options](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-filesystem-configurations.html). Neither feature alone turns the existing Browser and Code Interpreter into a single desktop. [Browser sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-resource-session-management.html) and [Code Interpreter sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-session-characteristics.html) can each run for at most eight hours.

For the full-computer spike, compare a custom isolated VM/container with AgentCore Instances. [AgentCore Instances](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-how-it-works.html) can retain an EBS workspace across stop/resume and run multiple agents in one session, but its documented API/CLI modality does not by itself provide a shared graphical browser and takeover. Validate those pieces explicitly. The checked-in `.llm-context/agentcore.ts` schema does not currently expose an Instances capacity provider; if selected, update the declarative toolchain or declare separate maintained infrastructure rather than editing generated CDK. Decide whether the initial computer is per owned bot or per room; recommend **per room with explicit member access and separate credential grants** for collaboration, while preserving private direct-bot computers. Provide idle suspend, storage/compute caps, network controls, recording/action history, file export, and deletion before broad release.

## Cross-cutting work and release gates

- **Authorization and privacy:** Recheck room membership when a child begins and before a proposed external action executes. Snapshot allowed capabilities at dispatch, but revocation must prevent future tool use. Scope artifacts and workspace storage by owner/room. Update account deletion and room deletion to cancel tasks, stop sessions, and remove files and event subscriptions.
- **Costs:** Admit the maximum permitted graph before fan-out; meter actual invocations and computer time/storage separately. Show the projected cap before running and final receipt afterward. A subscription allowance should apply to total work, not just the number of chat turns.
- **Portability:** Export routine definitions, task/result history, artifact manifests, workspace files, bot recipes, model policy, and permission *descriptions*. Never export credentials or session tokens. Import with identity remapping and routines disabled. Self-hosted adapters can initially omit a live computer while accurately declaring that capability.
- **Observability:** One run ID through queue jobs, model calls, approvals, files, and notifications. Record task duration, retries, duplicate suppression, failed event deliveries, approval wait time, and cost. Show a user-facing run timeline and an operator trace.
- **Verification:** Test duplicate and reordered events, concurrent completions, late approval, cancellation, quota exhaustion, membership revocation, secret and memory isolation, export/import integrity, and deletion. Use an end-to-end room run and external event sandbox before enabling each feature broadly.
- **Open-source release:** Decide license and repository boundary after dependency/secret review; document a clean local install. Keep one canonical recipe/archive schema for hosted and self-hosted modes. Do not call the product self-hostable until a clean-machine smoke test passes.

## First implementation milestones

1. **Architecture decision and schema PR:** settle scope rules, run/task/routine/workspace schemas, compatibility migration, budget ceilings, and one-use approval semantics. Include fixtures for old scheduled and group messages.
2. **Parallel room vertical slice:** two specialists in parallel and one Chief synthesis, read-only tools, visible statuses, cancellation, and duplicate-delivery tests. Generalize to a bounded three-specialist plan after measurements.
3. **Approval and event vertical slice:** exact-action pause/resume; first-party decision event; GitHub webhook pilot; event preview and run inbox. Keep external writes behind an approval request.
4. **Durable workspace vertical slice:** persistent files across code sessions, owner/room file view, export/delete, and cost limits. Use the full-computer spike findings to decide whether a desktop belongs in the next release.
5. **Portability release track:** complete archive/import and model adapters during milestones 2–4, then ship the local runtime and hosted subscription controls against the same contracts.

**Product decisions needed before implementation locks the schema:** whether shared computers are room-owned (recommended), which external event source is the first pilot (GitHub issues recommended because a GitHub App already exists), and whether the eventual license goal is permissive forkability (Apache-2.0 is the current recommendation). None of these decisions blocks the first run/task contract or the read-only parallel slice.
