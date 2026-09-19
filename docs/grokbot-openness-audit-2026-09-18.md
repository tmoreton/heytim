# Grok Bot comparison and HeyTim openness audit

**Date:** September 18, 2026
**Decision status:** Product recommendation, not an approved license or pricing change.

## Executive judgment

HeyTim already covers the durable-bot basics: editable bot instructions, reviewed skills, scoped memory, direct and group conversations, scheduled work, approvals, files, and bot sharing. Its strongest distinction is a room where multiple people can work with specialists and keep shared decisions in one bounded context. Grok Bot is ahead in autonomous coordination and general computer work: its documented bots can run in parallel, hand tasks to one another, use a persistent shared cloud computer, learn browser workflows by demonstration, and start some routines from events. [Grok Bot overview](https://docs.x.ai/grok-bot/overview), [collaboration](https://docs.x.ai/grok-bot/chat-and-collaboration), [skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations).

The opening is **user control over a working team**, rather than a claim to beat a frontier model. HeyTim can make the bot definition, memory, context boundary, provider choice, cost, and data exit legible. Today that promise is only partly implemented. Personal memory can be edited and exported, but a complete workspace cannot be exported and re-imported; model routing is set by deployment; and this AWS-based app has no supported self-hosted edition. The current monorepo has no root `LICENSE` file, so publishing its source alone would not grant the permissions normally meant by “open source.” [GitHub's licensing guide](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

**Recommendation:** Make one portable product core with two operating modes: a managed monthly service and a self-hosted edition using the customer's own models and infrastructure. Ship ownership features in the hosted product before announcing the self-hosted edition. Choose a real open-source license when the runnable core, documentation, third-party notice review, and release boundary are ready. Keep both modes compatible through the same versioned data format and bot recipe format.

## Evidence and limits

- HeyTim findings come from this checkout's native client, HTTP contract, backend, runtime, catalog, deployment config, and prior dated audits. The prior [code audit](code-functional-audit-2026-09-17.md) found a published-site versus deployed-API catalog mismatch; this review did not repeat a live deployment check.
- Grok Bot findings describe its public product documentation as of this date. I did not use a signed-in Grok Bot account or inspect its private implementation. A missing documented feature is marked *not documented*, not asserted impossible.
- This is a product and architecture review. It does not set a subscription price or make a legal determination about a license or App Store billing.

## Functional comparison

| Area | Grok Bot's documented behavior | HeyTim in this checkout | Discrepancy and priority |
| --- | --- | --- | --- |
| Persistent bots and context | Named bots retain role, conversation context, memory, files, browser sessions, and preferences. [Overview](https://docs.x.ai/grok-bot/overview) | Named bots, editable prompts, pinned skills, AgentCore memory, and stable direct-chat browser/code sessions. [Architecture](architecture.md) | Broadly present. HeyTim's browser/code sessions are bounded, not one durable account computer. |
| Bot coordination | Parallel reasoning, asynchronous bot-to-bot messages, group handoffs, and ownership transfer. [Collaboration](https://docs.x.ai/grok-bot/chat-and-collaboration) | Chief-led group rounds are intentionally sequential: lead, contributors, synthesis. `shared/group_chat.py` plans that order. Human group members and saved decisions are a strength. | **High:** parallel delegation and visible handoff are the clearest workflow gap. Preserve room-scoped authorization if added. |
| Computer work | Shared account cloud computer with browser, filesystem, terminal, preview, and takeover. Its bots share files and logins; separate bots are not a security boundary. [Overview](https://docs.x.ai/grok-bot/overview), [security](https://docs.x.ai/grok-bot/approvals-security-and-privacy) | AgentCore Browser and Code Interpreter sessions, artifacts, and direct-chat approval flow; no equivalent persistent desktop or general takeover. [Architecture](architecture.md) | **Medium for this product:** powerful parity gap, but costly to build and a different trust model. Favor dependable connectors and visible action records first. |
| Repeatable work | Saved skills, scheduled routines, some event triggers, run history, and gradual browser demonstration capture. [Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) | Reviewed/private skills, daily/weekday/weekly/monthly schedules, and run inbox; no general event triggers or browser demonstration capture. [Roadmap](grokbot-parity-roadmap.md) | **Medium:** add “save this successful room process” and narrow event triggers after export/model work. |
| Integrations and approvals | Marketplace connectors, browser fallback, action review, and admin rules on eligible plans. [Skills and routines](https://docs.x.ai/grok-bot/skills-routines-and-automations), [security](https://docs.x.ai/grok-bot/approvals-security-and-privacy) | Reviewed provider connection code exists for major work tools; availability depends on deployed OAuth configuration. Direct interactive actions require approval; group and scheduled work cannot use those tools. [Capability audit](../catalog/docs/CAPABILITY_AUDIT.md) | **High for useful unattended work:** safe resumable write approvals and provider rollout matter more than adding connector names. |
| Files and results | Broad attachment types, previews, downloadable outputs, and evidence/action logs. [Files and results](https://docs.x.ai/grok-bot/files-and-results) | Direct and group uploads, native document generation, image output, and member-checked downloads. [Architecture](architecture.md) | Mostly present; improve linked sources, artifact versioning, and a portable archive. |
| Discovery and sharing | Bot template links expose shared configuration; recipients install copies without the creator's computer, logins, or history. Marketplace surfaces skills/connectors. [Bots](https://docs.x.ai/grok-bot/bots) | Public reviewed bot/skill directory, editable installed copies, and expiring bot/chat/skill share links. Shared bots strip private connections. [Catalog](../catalog/README.md) | Strong start; no searchable community bot listings or bot detail page that explains prompt, skills, tools, permissions, version, example run, and author together. |
| Platforms | macOS, Windows, Linux, iPhone, iPad, Android. [Overview](https://docs.x.ai/grok-bot/overview) | Shared SwiftUI iPhone and Mac app; public website is a library and handoff, not browser chat. [README](../README.md) | **Medium:** platform reach is narrower. A browser client would also make a self-hosted route easier. |
| Business model | Access is bundled with eligible Cursor or linked subscriptions, with weekly included use and optional metered overflow. [Cursor plans](https://cursor.com/help/grok-bot/plans) | Private beta; durable usage admission and accounting exist, but no subscription checkout or customer billing ledger. [Operations](operations.md) | **High before paid launch:** subscription entitlements, usage display, spend ceilings, and payment handling. |

### What Grok Bot leaves open for differentiation

Grok Bot's settings say that Cursor manages model selection and there is no model picker. Its bot sharing copies configuration but excludes learned memory and conversation attachments. The official product docs describe correcting memory through conversation; they do not document a first-class memory-record editor or one-click portable workspace export. A Cursor staff reply on the [community export thread](https://forum.cursor.com/t/best-way-to-export-memory/170714) says there was no one-click memory export at that point and suggests asking bots for a file backup. This is a dated product observation, not proof that no other account data export exists. [Settings](https://docs.x.ai/grok-bot/settings-and-notifications), [Bots](https://docs.x.ai/grok-bot/bots).

## The openness factor: current state

Scores are directional product judgments on a 0–5 scale, not security or quality measurements.

| User promise | Current score | Evidence | What would make it credible |
| --- | ---: | --- | --- |
| Inspect and edit remembered facts | **4/5** | Personal, bot, and group memory APIs support list/create/edit/delete; the native app exposes memory management. `api/memories.py`, `FeatureSheets.swift`. | Show scope, source, learned time, usage, and correction history in the same view. |
| Download and restore personal context | **2/5** | Account settings downloads JSON of the user's facts, preferences, and summaries. Group memory, shared room context, decisions, chats, files, bots, skills, and schedules are outside that export; there is no matching import. `api/memories.py`, `api-contract.json`. | One versioned workspace archive plus a tested import preview and restore path. |
| Inspect and reuse bot instructions | **3/5** | Installed bot prompt is visible/editable; official catalog JSON and skill Markdown are published; share snapshots carry configuration. No explicit bot/skill/routine download or portable recipe import. `catalog/`, `api/bots.py`, `api/sharing.py`. | Public “How it works” page, downloadable recipe, stable schema, and safe import. Expose the effective instruction layers without exposing secrets. |
| Choose model and compute | **1/5** | Runtime uses deploy-time OpenRouter primary/fallback IDs and one service credential; the client has no model setting. `runtime/model/load.py`, `agentcore/agentcore.json`. | Per-workspace or per-bot model policy, provider adapters, capability checks, visible model/cost receipt, optional user key, and a local-compatible endpoint. |
| See where data and cost go | **2/5** | Usage accounting stores model IDs and token/cost envelopes, but the client does not show a per-run model or cost receipt. The current public privacy page names AWS and Expo but does not name the OpenRouter model route. `docs/architecture.md`, `apps/website/src/pages/privacy.tsx`. | Show provider, model, data path, retention, and run cost in the app; review the public privacy copy against the current native and provider architecture. |
| Find and share bots | **3/5** | Curated public directory plus expiring bot/chat/skill links; no discoverable user-published bot registry. `apps/website/src/library.tsx`, `api/sharing.py`. | Searchable opt-in public recipes, versioned authorship, permission disclosures, examples, review/reporting, and safe installation. |
| Fork and run independently | **0/5** | No root license; backend depends on Amplify/Cognito/SQS/DynamoDB/S3 and AgentCore; client API/auth settings are bundled from Amplify; no supported non-AWS install. `README.md`, `apps/iOS/Sources/HeyTimCore/APIClient.swift`, `agentcore/agentcore.json`. | Licensed runnable core, local deployment guide, configurable client endpoint, compatible auth/storage/jobs/memory adapters, and a smoke-tested local model path. |

**Overall:** approximately **2/5 for user control**, with the strongest existing work in editable memory and curated definitions. This is a roadmap signal, not a claim that HeyTim is less trustworthy than Grok Bot. Several controls are stronger here already; the major deficit is taking the entire working context elsewhere.

## Product design: one core, two ways to run it

### Managed HeyTim: monthly subscription

Sell a reliable shared workspace: hosted rooms, sync, schedules, backups, notifications, maintained connectors, a reviewed bot library, updates, and support. Include a clearly stated compute allowance and an explicit monthly spend ceiling. Show the model/provider used and estimated or provider-reported cost for each run. Let users switch among supported provider/model combinations with capability warnings. A user-supplied model key can be an advanced option, but should not be necessary to get value.

Avoid an unlimited promise. A group round can consume several model calls, browser/computer work has variable cost, and the current run-unit quota is only a capacity gate rather than a dollar ledger. The app already stores idempotent usage envelopes; use real per-workflow cost distributions before setting a price or included allowance. [Current controls](operations.md). Apple treats app-delivered SaaS subscriptions and cross-platform purchases under its [App Review billing rules](https://developer.apple.com/app-store/review/guidelines/), so the purchase flow needs review before launch.

### Self-hosted HeyTim: free to run, bring your own compute

Publish a runnable, documented edition with bot/room chat, scoped memory, skills, schedules, artifacts, and export/import. Start with an OpenAI-compatible local endpoint and at least one tested local model path, then add adapters for other providers as demand and capability tests justify. A compatibility table should say which models support tool use, vision, large context, and structured output. “Any model” should mean any model that satisfies the needed capabilities, not a promise that every model performs every workflow equally.

The current AgentCore deployment is a useful AWS reference, but an AWS-account fork that still requires managed AgentCore and OpenRouter would be a narrower option than the self-hosting promise above. A local runtime/storage/auth/jobs seam must exist first. The hosted and self-hosted modes should consume the same bot recipes and workspace archive so users can leave or return without transcription.

### What to license

If maximum adoption and genuine forkability are the goal, **Apache-2.0 for the runnable core, client, recipe/portable-data schemas, and public catalog** is the clearest default. It permits commercial forks, which is the cost of that openness, and includes an express patent grant. The subscription must win on convenience and service quality. Keep HeyTim's name and marks governed separately; exclude secrets, production state, private customer content, and credentials from any release. [Apache-2.0](https://opensource.org/license/apache-2.0).

If preventing a closed hosted fork matters more than low-friction adoption, **AGPL-3.0** is the alternative to evaluate for the server: network users of a modified deployed version must be offered its corresponding source. That is a materially different tradeoff and merits license counsel and dependency review before selection. [GNU AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html). Avoid calling an available repository “open source” until the actual license and runnable scope are explicit.

## The portable contract to build first

One export should produce a versioned archive with a human-readable manifest and machine-readable data:

```text
manifest.json                 format version, export date, checksums, app version
bots/*.json                   identity, full user-authored prompt, skill/tool refs, model policy
skills/*.md                   versioned instructions and metadata
memories/*.jsonl              content, scope, source, timestamps, related bot/room
rooms/*.json                  shared context and saved decisions
conversations/*.jsonl         messages and safe activity metadata
schedules/*.json              definitions, disabled on import by default
artifacts/*                   owned files with metadata and checksums
connections/manifest.json     provider IDs and scopes only; never tokens or secrets
```

The export screen should show exactly what is included and excluded. Private bot memory stays private; a room export requires an explicit membership/owner policy and must not silently include other people's private data. Import should validate checksums and schema versions, show a preview, remap identities, and require fresh connector authorization. Imported schedules stay paused until a person enables them. Give users separate **Export bot**, **Export room**, and **Export everything** actions backed by the same format.

## Recommended sequence and acceptance checks

The concrete architecture and delivery dependencies for this sequence are in the [openness and autonomy implementation plan](openness-and-autonomy-implementation-plan-2026-09-18.md).

1. **Make existing openness visible.** Add a bot detail page with full authored prompt, pinned skill versions, tool permissions, author, example input/output, and import/share controls. Label the currently used model and provider per answer, and update the public data-flow explanation. Document which system instructions are platform-owned versus user-authored. Acceptance: a person can explain what a shared bot will read, where the data goes, and what it may do before installing it.
2. **Complete portability.** Implement the archive above and its import preview. Include personal and group memory according to explicit scope rules. Acceptance: export from one disposable account, import into another clean environment, and recover bots, skills, memories, room context, decisions, schedules in paused state, chats, and files without secrets crossing.
3. **Introduce provider choice.** Refactor `model/load.py` behind a model-adapter contract while preserving usage accounting, fallback safety, context management, and tool compatibility. Expose a small supported set first, then compatible custom endpoints. Acceptance: the same representative direct and group workflow runs on two providers and one local endpoint; the result records which model ran and what degraded.
4. **Make a real self-hosted path.** Separate AWS-backed adapters from the application domain, provide local storage/queue/memory/auth choices, and make the client endpoint configurable. Acceptance: a new contributor can start the supported self-hosted edition from a documented clean machine and complete a room workflow plus export/import using their own model.
5. **Launch paid hosting with measured limits.** Build subscription entitlements, usage and cost views, spend controls, cancellation, and account portability. Acceptance: account state changes cannot orphan data, users see allowance and overage before expensive work, and export works after cancellation under a published retention policy.
6. **Then close the most valuable Grok gaps.** Add resumable approval for scheduled/group writes, one narrow event trigger, save-a-successful-workflow, and parallel specialist delegation with provenance. Measure weekly rooms with accepted decisions or delivered artifacts before investing in a persistent desktop.

This updates the priority implied by the older [parity roadmap](grokbot-parity-roadmap.md), which deferred a broad model picker. If openness is the product position, **model portability and context portability are core work**. A giant uncurated model menu can still wait.

## Decision to make

Choose whether the intended public promise is **open definitions and data** or **a fully runnable open-source product**. I recommend the second, paired with managed hosting, but only after the self-hosted path passes its acceptance check. In the meantime, ship the data and model controls in the hosted app and describe the current product accurately.
