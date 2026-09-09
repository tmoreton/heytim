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
- AWS access was renewed on September 9; deployment and pilot evidence is below.
  Root deployment and pilot testing were explicitly authorized for this task only.
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

- Honest delivery state: deployed September 9; live push acceptance and receipt-check
  queueing verified. Provider receipts and physical device display remain separate.
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

Deployed and checked with the real pilot bots on September 9. Following the
Bedrock runtime guidance, the delivery policy lives in the shared runtime rather
than a pilot-only bot customization. It overrides automatic-export suggestions
in older templates and asks final responses to contain the actual report, drafts,
evidence, and next steps. Corrections return revised content instead of a file
status or changelog. Explicit document exports and requested images remain
available. Intermediate group roles retain their contribution constraints.

Updated both example daily prompts, existing pilot schedule prompts, and the
composer hint. Schedule IDs, timing, enabled state, historical messages,
attachments, and bot installations were preserved.
This is instruction-level behavior, not a deterministic tool-permission gate.

Verification: all 95 runtime tests (including eight new inline-delivery checks),
165 backend tests, 10 application tests, 2 infrastructure tests, configuration
validation, type checks, lint, security checks, Expo Doctor and web export passed.
Two new behavioral scenarios cover inline briefs and revised briefs; their corpus
validation passed. The standalone model matrix has not been run; real-group trials
are recorded below.

### Deployment and real-bot checks

- Commits: `9c8d8b6` (push state), `6e3bdaa` (inline delivery), and `bc4289a`
  (package dependency pin) pushed to main.
- Runtime: AgentCore `DEFAULT` endpoint READY on version **40**, in-place update.
  API and worker updates completed successfully in `us-east-1`.
- CI initially caught a fresh CodeZip install choosing `multidict` 6.8.0 outside
  the 6.7.1 lock. Explicitly pinned the existing locked version; all 95 runtime
  tests passed again and the deployed staging bundle was verified against the lock.
- Both existing schedules have the inline brief prompt, remain enabled at 07:00
  America/New_York, and retain group targets with flexible windows OFF.
- Version 39 full trials: Heytim.dev round `f3e64055-051c-417c-b903-dfb26391d293`
  and Strands round `65c5a7c9-4936-48f8-bb8f-240d97e6b68f`: 10/10 replies COMPLETE,
  zero artifacts. Final answers contain drafts, video ideas, source links and
  prioritized tasks (4,945 and 8,200 characters respectively).
- Version 40 smoke tests: Heytim.dev round `2887b185-ce93-4cb5-92fd-4d21e72e251b`
  and Strands round `77056307-2d13-44d6-a1ef-d41e85e15138`: both COMPLETE with
  substantive inline answers and zero artifacts, without an explicit chat-only
  instruction. No new research or social publication was requested in these tests.
- All four final notification submissions reached ACCEPTED with receipt checks
  queued. Receipts were still PENDING_RECEIPTS at inspection; no device-delivery
  claim is made.
- App/web release: [run 34370708360](https://github.com/tmoreton/frogbot/actions/runs/34370708360)
  succeeded for `bc4289a`, including all three verification jobs, the production
  over-the-air update and desktop web publication. The JavaScript bundle served
  by `app.froggybot.com` contains both new inline-response composer hints.

**Content quality is not yet a pass:** the personal lead reused prior research as
if the new request were a duplicate and synthesized prematurely. A draft used
"what worked for me" without supporting owner evidence in the inspected notes.
The work brief promoted limited
search coverage into universal absence claims (for example, that no official
channel or independent tutorial exists) and overstated secondary announcements.
Inline delivery is verified; freshness, provenance, calibrated claims, complete
source URLs and stage discipline remain work for the evidence-contract checkpoint.

### Mobile tables and conversation scrolling, September 9, 2026

- Native mobile and narrow web layouts now use the available bubble width, with
  normal edge padding. Desktop retains the existing centered 780px conversation
  and 650px/84% bubble limits; full-width desktop was explicitly not requested.
- Markdown tables share readable column widths across their headers and rows.
  Wide tables scroll horizontally inside the bubble, with an overflow hint;
  links, emphasis, selectable text, and larger native font scales are preserved.
- Chat scrolling follows the newest content only while the reader is following
  the bottom. Scrolling up or expanding working notes releases that behavior
  until the reader returns, sends a message, or chooses “Jump to latest.”
  Jump targets use measured content height, including padding, rather than
  FlatList's estimated last-item position. Switching conversations resets it.
- The React review moved high-frequency scroll tracking into refs and kept
  unchanged Markdown trees stable across polling, reducing layout churn.
- Verification: 20 application tests, 165 backend tests, type checks, lint,
  source-size/security checks, 21 Expo Doctor checks, web export, and iOS Hermes
  export passed. The repeatable local preview browser test passed at 320, 375,
  390, 1280, and 1920px with no uncaught errors: history survives incoming team
  replies, jump/follow and room switching work, desktop stays bounded, and phone
  tables scroll without page overflow. These are local sample-bot tests and
  browser viewport checks, not an on-device iOS gesture or live-bot validation.
- Re-run with an Expo dev server on port 8082 and
  `node apps/froggybot/scripts/chat-layout-browser-test.mjs http://localhost:8082`.
  The runner only accepts localhost preview URLs and creates an isolated browser
  session. It saves screenshots in a temporary directory and closes its session.
- Released commit `a02c2ca` in successful [run 34374392873](https://github.com/tmoreton/frogbot/actions/runs/34374392873):
  all three verification jobs, the production mobile update, and desktop web
  publication completed. The live site returned HTTP 200 and served
  `entry-5ff6df0893cba66f043da7f77417dccc.js`, containing the new horizontal-table
  hint, jump-to-latest control, and measured scroll target. A final browser pass
  explicitly dismissed the responsive drawer before checking phone screenshots;
  all five widths and scrolling scenarios passed with no uncaught errors.
