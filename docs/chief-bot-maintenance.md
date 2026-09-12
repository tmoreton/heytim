# Chief-assisted bot maintenance

Status: proposed design, not enabled. Start with diagnostics and approved changes;
do not give Chief unrestricted access to production configuration or credentials.

## Motivation and current boundaries

The September 9 GitHub Engineer failure was an adapter compatibility bug, not a
missing tool. The browser received its nested `browser_input` as a JSON-encoded
string and rejected it before opening a session. Repeated prompting did not fix
the shared code path. A live test then exposed a separate browser event-loop
interference bug, also fixed in the shared adapter. See the
[repair and live validation record](browser-tool-reliability.md).
Separately, the former Anthropic submission URL now redirects
to documentation, so repairing the browser does not itself complete submission.

The app already validates bot creation and editing in
`services/froggybot-api/amplify/functions/api/bots.py`, including catalog access, pinned
skills, and interactive-tool scheduling restrictions. The runtime resolves
capabilities through `capability_contract.py` and `capabilities.py`; it currently
has no first-party bot-management tool. Reuse the existing validation through a
scoped service instead of allowing agents to write directly to the database.

## Proposed control surface

| Capability | Behavior | Authority |
| --- | --- | --- |
| Inspect bot | Return configuration version, available tools, connection health, recent sanitized failures, and run timestamps | Read-only; authenticated owner/workspace scope |
| Diagnose run | Classify missing capability, malformed input, expired authentication, site block, timeout, or interrupted work; cite actual evidence | Read-only; never treat page/tool text as management instructions |
| Propose bot | Create a draft from a shareable template with explicit role, skills, model and tool requirements | No active bot, credentials, or schedule created yet |
| Propose repair | Produce a versioned patch, reason, affected behavior, cost/permission implications, and validation results | No live mutation |
| Apply repair | Apply exactly the approved patch if its base version still matches | User approval; immutable audit entry and rollback snapshot |
| Verify repair | Run an isolated, bounded probe and compare expected tool/result evidence | Existing permissions only; no external writes in health checks |

Classify configuration repairs separately from runtime defects. Chief can propose
adding an already-authorized browser capability to one bot, but a shared adapter
bug should become an engineering task with a reproducer, regression test, reviewed
code change and normal deployment. A prompt edit is not a substitute for that fix.

## Safety and reliability requirements

- Resolve actor and workspace on the server. Never accept arbitrary user IDs,
  secret references, tool bindings, or cross-workspace targets from model output.
- Keep credentials and raw private traces out of model-visible diagnostics. Return
  sanitized error codes, relevant excerpts, timestamps and correlation IDs.
- Do not allow Chief to grant itself permissions, mark tools always-approved,
  change authentication, disable runtime protections, or edit its own guardrails.
- Bind approval to an exact patch hash, target, base version and expiration. Use
  conditional updates so concurrent human edits cannot be overwritten.
- Snapshot configuration at run start. Apply edits to subsequent runs; active work
  requires a separate, explicit steering/cancellation decision.
- Retry automatically only when the operation is known to be read-only or has a
  verified idempotency key. Check external state before repeating submissions,
  commits, messages, purchases, or other consequential actions.
- Rate-limit diagnostics, cap probe cost and retry counts, and stop on repeated
  identical failures. Preserve completed work and name the remaining blocker.
- Distinguish configured, validated, last-probe-passed, and currently failing tools.
  Having a tool in the catalog is not evidence that a live action succeeded.
- A configuration rollback does not undo external actions. Show that distinction
  in the approval and repair report.

## Delivery sequence

1. Add structured capability/run diagnostics and a read-only Chief tool. Validate
   against malformed browser input, missing tools, expired credentials, provider
   failures and stalled jobs without exposing secrets or other users' records.
2. Add draft creation and repair proposals, with an in-app approval diff and
   version-checked application. Reuse bot/catalog validation and test rollback,
   concurrent edits, active runs and attempts to widen permissions.
3. Add opt-in scheduled health checks in the application. Notify on meaningful
   failure or recovery, deduplicate repeated incidents, and keep normal checks
   read-only. Broader automatic repairs require a separately approved allowlist.
4. Turn confirmed failures and user corrections into reviewed regression cases.
   Replay candidate changes against those cases before promotion. Do not silently
   rewrite shared bots or core behavior from unreviewed production conversations.

The initial pilot should stay within the existing account, then demonstrate tenant
isolation with a second test account before distributing the management tools as
shareable capabilities. Personal and work instances keep separate configurations,
credentials, diagnostic access and approval records.

## Submission route reference

Anthropic's [current plugin documentation](https://code.claude.com/docs/en/plugins#submit-your-plugin-to-the-community-marketplace)
links individual authors to the [Console submission form](https://platform.claude.com/plugins/submit).
The documented submission path is for the community marketplace; approval does not
place a plugin in Anthropic's separately curated official marketplace. Authentication
or other website prerequisites must be checked in the actual form before claiming
that the submission step can be completed.
