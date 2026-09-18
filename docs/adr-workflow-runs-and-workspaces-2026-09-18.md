# Workflow runs, event routines, and durable workspaces

**Status:** Implemented locally; production release and live event verification pending.
**Date:** September 18, 2026

## Decision

Keep SQS and DynamoDB as the workflow engine for the first room handoff release. A room reply has one versioned `WORKFLOW_RUN` record (`RUN#<runId>`) and each bot message carries a versioned `runId`, `taskId`, and `taskRole`. The bot message remains the authoritative task status for compatibility with existing clients. A run records its task IDs and message keys. No AWS ARN, queue URL, or credential is part of the portable record.

Chief's lead reply runs first. For a team with at most three contributors, the worker enqueues the contributors independently after the lead completes. A completion barrier queues one synthesis after all contributors reach a terminal state. The existing reply lease prevents duplicate execution when SQS delivers a job again. Larger existing rooms retain sequential execution until they can be admitted to a bounded parallel graph without surprising spend. The whole round is admitted against its existing run-unit budget before individual work proceeds.

The room input is fixed at the user message key for parallel contributors. Each contributor sees Chief's completed lead reply, but not sibling work or newer unrelated room messages. Chief's synthesis sees completed contributors and a short failure description for failed contributors. Shared room memory and bot configuration are still read at task start; immutable snapshots of those resources are a later migration.

The requester or room owner can cancel a run. Cancellation marks queued replies as `CANCELLED` and prevents new contributor or synthesis dispatch. An invocation that already started may finish its current step. The API therefore reports a cancellation request, not a claim that external work was rolled back.

## Event routine contract

An owner can define an enabled room routine with `routineVersion: 1`, a prompt, and `trigger: {kind: "event", eventType: "group.decision.saved"}`. Saving a decision emits an internal event. A stable `(routineId, decisionId)` run ID ensures duplicate deliveries reuse the same message and replies. A routine created after a decision does not replay that decision. A routine's own output cannot emit another routine event. The event payload is separated from the owner's instruction in the generated prompt and is treated as task data.

Room event routines may include interactive tools owned by the room owner. A tool call pauses for exact approval; another member's interactive bot is rejected. A GitHub App `issues.opened` webhook can trigger an owner routine bound to a selected connection and repository. The endpoint verifies `X-Hub-Signature-256` over the raw body using `webhookSecret` in the existing `GITHUB_APP_SECRET_ARN` JSON secret. It reads an installation/repository subscription partition and queues one event job per routine. Each job rechecks the current routine, room owner, GitHub connection revision, installation, and selected repository before starting. A stable `(routineId, deliveryId)` run ID handles redelivery; a revoked or reconnected grant blocks an old routine until the owner saves it again. Set the GitHub App webhook URL to `/public/webhooks/github`, configure a random secret of at least 32 characters in both the App and the stored JSON, and subscribe the App to the Issues event before enabling a routine. The live delivery and replay still require verification.

## Workspace contract

Bot and room workspaces store up to 50 files and 100 MB in separate S3 prefixes. A file manifest is stored in DynamoDB with `workspaceVersion: 1`; an atomic counter reserves capacity before copying a reviewed upload. Room membership is required for reads and additions. Only the uploader or room owner can delete a room file. Bot deletion and room deletion remove the scoped objects and metadata.

The API lists files, returns a short-lived download link, deletes files, and exports a JSON manifest with short-lived links for bulk client download. A message can select up to five workspace files. If Code Interpreter is available, the runtime validates every selected object key against the exact bot or room prefix and exposes `load_workspace_files` to copy those files into the current code session. Files can therefore be loaded again after that session expires. This is explicit sync; it is not a shared live filesystem or a desktop computer. A single portable archive and import flow remain separate work.

The native Details screen now lists the files, lets a member add and open them, and exports the five-minute download list. The chat composer can select a saved file for a later message. This does not yet produce a single offline archive.

## Cloud computer decision

Defer an always-on room computer. The benefit would be preserving one live shell, browser, processes, and working directory across tasks, with shared inspection and takeover. The current Browser profile, ephemeral Code Interpreter, and durable S3 workspace cover file continuity without paying for idle EC2 compute. AWS currently charges AgentCore Instances for EC2 time plus a 12% management fee and EBS separately, including EBS while compute is stopped. Use measured demand for multi-day shell/browser continuity to decide whether a suspendable room computer spike is justified; do not turn a persistent instance on by default. [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/) and [Instance data lifecycle](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-instances-data-management.html) document the tradeoff.

## Approval boundary

Direct chat and owner-controlled room runs now intercept proposed tool calls with `BeforeToolCallEvent`. The runtime saves the Strands interrupt snapshot under the turn's encrypted S3 scope and reports the exact tool name, arguments, tool-use identity, and canonical digest. The app displays the arguments before allowing one action. The API binds a 15-minute request to the turn/task and approver, rechecks membership, bot grants, connection revision, and routine revision, and writes a one-use execution key. The worker conditionally consumes the key before runtime resume. A failed or uncertain dispatch after consumption cannot replay the action; it ends with an error instead. Denial, expiry, and run cancellation prevent the paused call from executing. The system deletes the current snapshot on a terminal response, denial, expiry, or cancellation; versioned S3 noncurrent objects follow the bucket's 30-day retention. Connected provider APIs still do not offer a uniform external idempotency key, so an uncertain result requires inspection before a new action is proposed. Scheduled groups remain read-only; an event routine requires an owner-owned bot for interactive calls.

## Compatibility and release

Older room messages and schedules remain readable without workflow fields. A run created before this release may have no `WORKFLOW_RUN` row; the worker tolerates that case. Current scheduled room jobs continue to create stable reply IDs. Generated Swift and TypeScript route constants follow `api/api-contract.json`.

Before broad activation, exercise the API and worker against a deployed test room, verify cost and error receipts with concurrent specialists, and test a signed GitHub delivery and replay against the deployed webhook. The native app now has a workspace file view and composer picker plus a room routine editor with preview and run history.

Local verification: 454 API/worker unit tests, 266 runtime tests, API contract generation check, TypeScript typecheck, Apple unit test scheme, and `git diff --check` passed. These tests do not replace a deployed webhook replay, concurrent room cost check, or live Code Interpreter file-sync check.
