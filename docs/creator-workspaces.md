# Reusable creator workspaces

## What is implemented

The proposed `skills-v22` public release replaces the overlapping creator portion of [catalog PR #2](https://github.com/tmoreton/froggybot-skills/pull/2) with two focused bots: Creator Studio combines public YouTube strategy with Thumbnail Director, while Trend Scout compares dated signals from YouTube, recent X posts, and the web. The older GitHub Engineer, Twitter Research, YouTube Research, Reddit Research, and Thumbnail Studio proposal remains unreleased and should not be merged wholesale.

The application supports group-owned scheduled tasks using the existing scheduler, queue, worker and push pipeline. The group owner opens **Tasks & runs**, chooses a time and IANA timezone, and can save, pause, delete or run a task immediately. A scheduled round asks Chief to scope the task, runs the specialists, then asks Chief for the final synthesis. Only the final reply queues completion notifications. A 07:00 schedule starts research at 07:00; notification delivery follows completion, not an exact 07:00 deadline.

Schedules and credentials are never copied into public bot definitions. The same installed bot can participate in different groups. Each group has its own notebook, transcript and isolated AgentCore memory actor. Cross-group artifact paths are checked against that actor. GitHub connections remain private and are not granted by installing a template. The GitHub bot stages repository archives in the sandbox, then uses the owner's GitHub connection for remote changes; it does not promise a fully authenticated local git clone.

Scheduled groups reject interactive tools, recheck membership and tool policy during execution, and use deterministic occurrence/reply identities so retries preserve completed contributions. Run history reports a failure if any specialist failed; it does not turn a partial team result into a successful run. Notifications are queued by the worker; actual phone delivery depends on a valid registered device and delivery receipt.

## Report delivery

The runtime defaults to delivering useful content inline: source-linked findings,
tweet and reply drafts, video ideas, and prioritized next steps belong in the final
chat message. Revisions show the corrected content, not just a changelog or a
"file updated" notice. Downloads are reserved for explicit export requests;
requested documents and generated images remain supported.

This shared runtime policy also takes precedence over older bot templates that
encourage automatic exports. The example schedules request complete inline briefs.
Historical messages and attachments are unchanged. On September 9, both existing
pilot schedule prompts were updated through the authenticated application API;
their IDs, time, timezone and enabled state were preserved.
See [implementation status](coworker-implementation.md) for deployment and validation.

## Pilot state, September 8, 2026

The sole confirmed pilot account has the upgraded GitHub and three social bots, Thumbnail Studio, and two groups: **Heytim.dev** and **strandsagents.com**, each with Chief and the three social specialists. Their notebooks contain separate audiences, voices, research watchlists and daily instructions. Existing connections, approval grants and unrelated bots were preserved.

The existing GitHub connection was checked read-only: branch creation, file updates, PR creation, PR inspection and merge tools are available. No repository was modified or PR merged by that verification.

The initial live research round in each group failed before model execution with `ValueError: group artifact scope is invalid`. The runtime previously rejected any non-null actor for group artifacts, conflicting with the newly enabled shared group memory. The fix validates the group actor against its artifact namespace, retains compatibility with older group requests without memory, and rejects personal or different-group actors. It was deployed as runtime version **38** on September 8 (Eastern), along with the worker retry fix and API backend. Runtime status is READY and both application functions updated successfully.

The user explicitly authorized a one-off root deployment for this repair; the normal recommendation remains IAM Identity Center or an appropriate deployment role. No IAM identities, permissions or authentication settings were changed by the repair deployment.

**Both recurring pilot schedules are installed and enabled**, daily at 07:00 America/New_York. Remote EventBridge state, timezone, group target and disabled flexible window were verified. Each run begins research at 07:00 and notifies on completion; this is not exact 07:00 delivery. The first clock-triggered occurrence has not yet been observed.

Fresh live trials completed all **10 of 10 replies** across both groups and saved the final Markdown reports. Both final notification delivery records reached SENT; this confirms application push handoff, not physical phone delivery. The prior error messages remain in chat history. Source coverage is still partial: Reddit blocks or rate-limits some requests, two personal X topic searches returned provider errors, and the work YouTube home channel remains unresolved. These limitations appeared in completed reports rather than crashing the round. The work Chief also produced a premature preliminary artifact in its lead turn; its later synthesis contained the actual specialist results, but that role-following behavior still needs refinement.

## September 9 deployment follow-up

The inline-first runtime is live on AgentCore version **40**, and the API/worker
updates are deployed. Both 07:00 Eastern schedules remain enabled. Full trials in
both groups completed all 10 replies with no artifacts; both final reports include
the actual content inline. Two further Chief smoke tests on version 40 also
completed with inline answers and no artifacts. Push submissions were ACCEPTED
and receipt checks queued; physical phone delivery is not established.

This verifies delivery behavior, not overall research quality. The personal lead
still reused older material and synthesized early, and some drafts or search-based
claims went beyond their evidence. See the [implementation evidence and remaining
issues](coworker-implementation.md) before treating these bots as reliable autonomous
coworkers.

## Install another profile

1. Install the reviewed public bots individually from the app library once the catalog PR is approved and released. Install the FroggyBot GitHub App on only the required repositories if private repository access is needed. Bot installation does not itself grant repository access.
2. Create a scheduled research group containing Chief and Trend Scout. Keep Creator Studio in direct chat because its image tool prevents group replies. Set the group's audience, subject, channel identifiers, voice and source watchlist in its notebook. Do not paste credentials into a notebook or prompt.
3. Use [creator-workspaces.json](../examples/creator-workspaces.json) as a profile example, replacing Heytim.dev and Strands with the new subjects. It installs both public creator bots but adds only Trend Scout to the scheduled groups. The example schedules are daily at 07:00 America/New_York and research/draft only. Adapt the timezone explicitly for other users.
4. Run a small manual research trial and inspect actual source links, missing data, costs and the final result before enabling recurrence.
5. Use **Tasks & runs** to create the daily group task after the backend is deployed. Notifications arrive when the research completes. If a report must be ready by 07:00, start collection earlier and add a separate fixed-time delivery stage; that is not implemented here.

Operators can provision the same profile through the account-verified application utility:

```bash
services/agent-runtime/.venv/bin/python scripts/configure-creator-workspaces.py \
  --email YOUR_EXACT_ACCOUNT_EMAIL \
  --profile YOUR_IAM_OR_SSO_PROFILE \
  --user-pool-id YOUR_USER_POOL_ID \
  --function-name YOUR_API_LAMBDA_NAME \
  --catalog /path/to/reviewed/catalog.json
```

The default is a read-only plan. `--apply` upserts bots/groups by exact case-insensitive names and preserves existing connections and approval grants. `--include-schedules` also upserts recurring tasks and requires the new backend routes; it enables schedules according to the pack. `--run-now` starts a real research round in each group; it is intentionally opt-in and incurs model/tool usage. Repeat installation without that flag to avoid duplicate trials. Account lookup must return exactly one enabled, confirmed Cognito user. The utility requires trusted operator permission to invoke the API Lambda; it is not a client-side authentication shortcut.

## Remaining channel integration work

The current YouTube gateway provides public search, video details and comments. The optional read-only YouTube owner connection can identify the authenticated channel and list its uploads, including private items visible to that account. It does **not** provide YouTube Analytics reports, metadata updates, thumbnail uploads or an experiment-management API. Public views and Data API statistics cannot establish CTR, retention, impressions, watch time, revenue or causation.

Add YouTube Analytics as a separate read-only capability only when those private reports are needed. Any later write connection must remain separate from research access: never grant write scopes merely to run daily research, and require a before/after preview plus revalidation of the approved video and current metadata before applying edits. Connections remain independent of bot prompts so the same bot works for another account or work channel.

Until Analytics access is implemented and authorized, accept owner-supplied YouTube Studio exports for private metrics and keep all titles/descriptions as drafts. Native Studio title/thumbnail tests can be configured manually where eligible; ordinary sequential metadata changes are not randomized A/B tests. See the [research notes](creator-research.md) for official API/testing references and initial creator recommendations.

The runtime has an OpenRouter image generator and private artifact storage. Creator Studio's Thumbnail Director can create draft 1280x720 thumbnails that request the user's copy and incorporate recent, user-owned image references from the same direct chat. Generated words must be visually checked before the image is called final because the model can misspell or alter text. Web search can locate official brand guidance and source pages, while exact marks should come from uploaded official assets rather than a model redrawing them. Because image generation is interactive, Creator Studio cannot participate in group replies or group schedules. Direct turns require approval for the bot's full tool set, even for research-only requests; a direct bot schedule can run only after Image Generator has been persistently allowed.

Daily to-dos are included in the group brief and recent transcript. They are not yet a standalone persistent task board with assignment/completion tracking or analytics across reports.

## Verification evidence

- App TypeScript, lint and backend infrastructure TypeScript checks pass.
- Backend unit tests cover group ownership, timezone, isolated routes, remote-create rollback, paused/manual runs, retry identity and execution-time tool policy.
- Runtime suite: 87 tests pass, including archive dependency verification and the shared-memory/artifact regression.
- Proposed `skills-v22` catalog validator: 11 bots, 11 skills, and 13 tools. Site build and all 15 tests pass.
- Browser preview: group task created at 07:00, manual run reached Complete, View in chat returned to the group. No browser console errors. This used local sample data, not the cloud scheduler or live model.
- Live pilot: runtime version 38, 10/10 replies complete, two final report files, and two notification records marked SENT. Clock-triggered recurrence and physical device receipt remain unobserved; research coverage and intermediate-role behavior retain the limitations above.
