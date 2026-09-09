# Reliable coworker implementation

This is an implementation checklist, not a claim that these capabilities are live.
The pilot is limited to Heytim.dev and strandsagents.com, research and drafts only.
Other users must be able to install the same generic capabilities with their own
profiles, data, schedules and permissions.

## Baseline

- Existing changes committed and pushed as `3e7f868`.
- GitHub release run `34305717684` succeeded (application and web).
- Local verification: 87 runtime tests, 153 backend tests, 10 application tests,
  2 infrastructure tests, type checks, lint, security checks and web export passed.
- AWS refresh and new live-bot validation await renewal of expired CLI credentials.
  Root deployment and pilot testing are explicitly authorized for this task only.
  No IAM or authentication configuration changes are implied by that authorization.

## Checkpoints

1. **Honest delivery state:** separate push submission, ticket acceptance and
   provider receipts. Preserve duplicate protection and unknown outcomes.
2. **Evidence contracts:** capture tool-result provenance, collection times,
   source links, scope and limitations; validate structured findings and expose
   quality separately from execution status. Never label model assertions verified
   merely because another model agrees or a URL exists.
3. **Durable action items:** scoped records with proposal/approval/progress/blocker/
   completion states, owners, evidence, dependencies, deliverables and optimistic
   concurrency. Completion needs a result. Repeated reports reuse existing items.
4. **Profiles and feedback:** preserve factual experiences, audience and approved
   voice examples independently per group. User feedback must not silently become
   fabricated biography or leak across groups or public templates.
5. **Data quality:** connector health, bounded retries and dated fallbacks; owner-
   authorized YouTube analytics and imports, with unavailable metrics explicit.
   OAuth consent requires the account owner; no credentials enter bot definitions.
6. **Scoped actions:** exact-payload approval and execution-time revalidation for
   posting/channel edits; revision-bound approvals and required checks for merges.
   Research schedules do not gain write permissions. No live publication in tests.
7. **Morning delivery:** independent collection/delivery stages, deadline-aware
   partial reports, bounded time/cost and recoverable failures. A 07:00 collection
   schedule is not a guarantee of a report or physical notification at 07:00.
8. **Behavioral validation:** replay observed failures, test cross-group isolation,
   false claims, stale evidence, premature synthesis, duplicate actions and task
   carry-forward. Compare actual bot runs against reviewed evidence and outcomes.

## Validation for each checkpoint

Run focused tests, then repository verification; inspect the deployment diff;
deploy only intended changes; run bounded live trials in the actual pilot groups;
inspect persisted records, linked artifacts, tool activity and output quality.
Record deployment version, run IDs and limitations. Do not infer phone receipt,
content performance or successful side effects from a model's final prose.

## Progress

- Honest delivery state: implemented locally; not deployed or live-validated.
  Submission status is ACCEPTED / PARTIALLY_ACCEPTED / REJECTED / UNKNOWN.
  Provider receipt status is tracked separately; it never claims device display.
  A failed receipt-check queue handoff can resume without resending a push.
  Regression tests cover malformed/missing tickets, provider failures, uncertain
  submissions, exhausted polls, duplicate callbacks and cross-user record checks.
  Full verification passed before the final four added edge cases; the final
  backend suite passed all 165 tests (12 delivery tests), with lint, security and
  source-size checks passing again. Runtime and frontend were not changed.
- Remaining checkpoints: planned; not implemented by this checklist.

### Inline-first delivery, September 9, 2026

Implemented locally; not deployed or validated with live bots. Following the
Bedrock runtime guidance, the delivery policy lives in the shared runtime rather
than a pilot-only bot customization. It overrides automatic-export suggestions
in older templates and asks final responses to contain the actual report, drafts,
evidence, and next steps. Corrections return revised content instead of a file
status or changelog. Explicit document exports and requested images remain
available. Intermediate group roles retain their contribution constraints.

Updated both example daily prompts and the composer hint. Existing cloud schedules,
historical messages, attachments, and bot installations have not been rewritten.
This is instruction-level behavior, not a deterministic tool-permission gate.

Verification: all 95 runtime tests (including eight new inline-delivery checks),
165 backend tests, 10 application tests, 2 infrastructure tests, configuration
validation, type checks, lint, security checks, Expo Doctor and web export passed.
Two new behavioral scenarios cover inline briefs and revised briefs; their corpus
validation passed, but model execution and real-group trials still await AWS login.
