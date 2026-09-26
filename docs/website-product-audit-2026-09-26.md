# HeyTim product audit and website redesign

Date: September 26, 2026

## Product position

**HeyTim is a personal team of AI specialists for iPhone and Mac, with shared rooms for the work people do together.**

The product now reaches well beyond group trip planning. Its strongest combination is continuity, reusable ways of working, collaboration, and controlled access to useful tools:

1. **Keep context:** remember preferences and previous work, with memory people can inspect and change.
2. **Finish useful work:** research, analyze, draft, create files, and carry out permitted actions.
3. **Work with people:** bring humans and specialists into one room with shared context and attributable decisions.
4. **Repeat what works:** reuse skills, schedule work, and react to specific events.
5. **Stay personal:** choose each bot's accounts and permissions; use device capabilities where they make sense.

The website leads with “A little team for your whole life.” This is a product positioning recommendation based on implemented capabilities, not a claim of exclusive features or a competitor benchmark.

## Audit method

Reviewed the current native UI, API handlers, worker/runtime boundaries, public catalog, provider registry, release assets, and website implementation. Older audit and roadmap documents were useful context, but current code takes precedence when they disagree.

This is an implementation and product-surface audit. It does not establish that every external provider is configured in production or that every AI workflow succeeds in a live account. The redesign changes the marketing site only.

## Capability inventory

Paths below are relative to the repository root.

| Area | Implemented capability | Evidence | Website treatment |
| --- | --- | --- | --- |
| Native apps | Shared iPhone/macOS client, adaptive navigation, common account and workspace | `apps/iOS/Sources/HeyTimUI/MainView.swift`, `apps/iOS/README.md` | Homepage Apple section; platform-specific download cards |
| Access and onboarding | Invitation-based email code sign-in, Chief setup, additional bot selection | `apps/iOS/Sources/HeyTimUI/AuthView.swift`, `services/API/amplify/functions/api/bot_setup.py` | Clear private-beta and invited-account requirements |
| Specialist catalog | 17 available bots and 19 available skills at audit time | `catalog/catalog.json`, `apps/website/src/catalog.ts` | Counts derived from the live checked-in catalog, searchable libraries |
| Bot configuration | Private editable bot identity, prompt, tools, connections, and skills | `apps/iOS/Sources/HeyTimUI/FeatureSheets.swift`, `services/API/amplify/functions/api/bots.py` | Team section and full features guide |
| Chief and private skills | Chief can manage bots; bots can create private instruction skills without granting new tools | `services/runtime/runtime/heytim_runtime/bot_management.py`, `catalog/skills/skill-builder/SKILL.md` | Custom skills explained as reusable instructions |
| GitHub skill import | Preview public repository skills, inspect contents, create a private copy | `apps/iOS/Sources/HeyTimUI/GitHubSkillImportView.swift`, `services/API/amplify/functions/api/github_skills.py` | Included in custom skills |
| Direct chat | Persistent conversations, Markdown, attachments, progress, stopping and approvals | `MainView.swift`, `services/API/amplify/functions/api/direct_chat.py` | Illustrated product stories; guide explains actual controls |
| Groups | People and bots, invitations, membership, reply targeting, coordinated team rounds | `services/API/amplify/functions/api/groups.py`, `group_messages.py`, `services/API/amplify/functions/worker/group_job.py` | Main differentiation; human and specialist contributions |
| Decisions | Saved, attributed group decisions and owner-permitted removal | `FeatureSheets.swift`, `services/API/amplify/functions/api/groups.py` | Shared outcomes and durable context |
| Memory | Personal preferences/facts, bot summaries, isolated group memory, edit/delete/export | `services/API/amplify/functions/api/memories.py`, `services/runtime/runtime/heytim_runtime/memory.py` | Lead feature with inspectable controls |
| Persistent files | Bot/group workspaces, reusable references, upload/download/export, scoped membership | `services/API/amplify/functions/api/workspaces.py`, `attachments.py`, `apps/iOS/Sources/HeyTimUI/SupportingFeatureSheets.swift` | Features guide; scoped shared files |
| Schedules | Hourly, weekdays, daily, weekly, monthly; timezone; run now, edit, pause, delete | `FeatureSheets.swift`, `services/API/amplify/functions/api/schedules.py`, `group_schedules.py` | Homepage follow-through section; full cadence list in guide |
| Event routines | Group decision saved and connected GitHub issue opened; prompt preview and run history | `SupportingFeatureSheets.swift`, `services/API/amplify/functions/api/group_routines.py`, `github_webhook.py` | Explicitly described as the two supported event triggers |
| Background work | Working checklists, focused delegates, code execution, persistent browser/sandbox sessions, resumable long jobs | `services/runtime/README.md`, `services/runtime/runtime/heytim_runtime/background_work.py` | Practical research and analysis; no guaranteed completion claim |
| Run history and notifications | Status, output, failures, native notification registration and routing | `FeatureSheets.swift`, `apps/iOS/Sources/HeyTimPlatform/NativeNotifications.swift` | Notifications on completion, not at an exact delivery deadline |
| Web research | Web reader, web search, exact arithmetic, timezone lookup | `catalog/catalog.json`, `services/runtime/runtime/heytim_runtime/local_tools.py` | Research and source-linked answers |
| File creation | PDF, Word, Excel, PowerPoint, Markdown, CSV, JSON, HTML and charts | `services/runtime/README.md`, runtime artifact/document/spreadsheet/presentation renderers | Exports on request, with useful chat answers as the default |
| Creative work | Image generation, reference-aware thumbnails, local meme template captioning | `image_generation.py`, `memes.py`, `meme_templates.py` under `services/runtime/runtime/heytim_runtime/` | Creator Studio and Meme Lord, with distinct outcomes |
| Voice and meetings | On-device transcription; long transcript attachment; meeting-note skill | `apps/iOS/Sources/HeyTimPlatform/DictationModel.swift`, `MainView.swift`, `catalog/skills/meeting-notes/SKILL.md` | Clearly distinguishes on-device transcription from submitting text to a bot |
| Mac control | Per-bot local grants, semantic Accessibility controls, optional local OCR, human takeover pause | `apps/iOS/Sources/HeyTimPlatform/DesktopControlCoordinator.swift`, `apps/iOS/README.md` | Permissioned supported controls; no unrestricted desktop takeover claim |
| Browser handoff | Private interactive browser, human sign-in handoff and scoped sessions | `apps/iOS/Sources/HeyTimUI/BrowserHandoffView.swift`, `services/API/amplify/functions/api/browser_sessions.py` | Described alongside Mac Operator |
| Apple Health | Explicit per-bot read-only activity, workouts, running and step aggregates | `apps/iOS/Sources/HeyTimPlatform/AppleHealthCoordinator.swift`, `catalog/skills/health-coach/SKILL.md` | iPhone-only; no routes, clinical records, or writes |
| Account connections | Separate accounts and bot assignment; supported resource narrowing | `services/API/amplify/functions/shared/connection_providers.py`, `services/API/amplify/functions/api/connections.py` | Per-bot access is a central differentiator |
| Provider adapters | Gmail, Workspace, Slack, GitHub, YouTube, X, Notion, Microsoft 365/Teams, HubSpot, Jira, Zoom, QuickBooks, Plaid | Provider registry; runtime provider adapters | Full directory states scope and beta availability |
| Custom tools and home | HTTPS bearer-token MCP servers; Home Assistant through Assist MCP | `services/runtime/runtime/heytim_runtime/mcp_connections.py`, provider registry, `docs/connections-and-tools-audit-2026-09-23.md` | Explain MCP in context; include endpoint/authentication limits |
| Bot email | Per-bot inbox, owner-authenticated automatic intake, review mode, app/email response delivery | `services/API/amplify/functions/api/bot_inbox.py`, `apps/iOS/Sources/HeyTimUI/BotInboxView.swift` | “Where enabled”; current release limitations retained |
| Account and data controls | Export/delete memory, revoke shared links, revoke tool grants, delete account | `SupportingFeatureSheets.swift`, `services/API/amplify/functions/api/account.py`, `sharing.py` | Dedicated control section and privacy links |
| Usage and billing | Usage & Plan, credits, remaining allowance, Plus subscription management | `SupportingFeatureSheets.swift`, `services/API/amplify/functions/api/billing.py` | Capability mentioned; no invented price or availability promise |
| Source and contributions | Public source under PolyForm Noncommercial; reviewed contribution proposals | `README.md`, `catalog/CONTRIBUTING.md` | Source-available wording; existing contribution policy preserved |

## Important distinctions confirmed in current code

- **Group tools changed since earlier audits.** `group_messages.py` permits the requester's own interactive bot tools through approval checks. It rejects using another owner's interactive bot for those actions. `group_schedules.py` requires the appropriate existing grants. The new site does not repeat the older blanket claim that groups reject every interactive tool.
- **Provider registration is not production availability.** `services/API/amplify/infrastructure/provider-connections.ts` disables providers without configured secrets. The features directory distinguishes supported adapters from the Connections screen's currently enabled providers.
- **Gmail is read/draft only.** The app cannot send, delete, archive, or relabel Gmail messages. Bot-address email delivery is a separate capability.
- **X and YouTube searches require connected accounts.** The old shared public catalog tools are disabled. The current site does not advertise login-free access to them.
- **Mac distribution is direct.** The latest published release inspected during this audit was v1.0.11, with DMG, update ZIP, and appcast assets. The download page uses the stable GitHub `releases/latest` destination rather than pinning an old version. iPhone remains on TestFlight. An invitation is still required for the account on either platform.
- **On-device transcription is not fully local AI.** Speech becomes text locally; users submit that text to their bot. The site makes no “all data stays on your device” claim.
- **Scheduled time is start time.** Completion and notification follow execution. There is no promise of a finished report at an exact hour.
- **MCP is bounded.** Current custom servers require public HTTPS and a bearer token; not local-network, tokenless, or OAuth-only endpoints.
- **Bot inbox is gated.** Availability depends on email deployment configuration. Email attachments are listed but not downloaded or provided to the bot in this release.
- **No unsupported product promises.** The site does not advertise browser chat, Android, universal app control, a general-purpose webhook builder, YouTube Analytics, a standalone persistent task board, automatic social publishing, or an OSI open-source license.

## Website findings and implementation

| Before | Now |
| --- | --- |
| Group-trip messaging represented nearly the whole product | A personal team is the entry point; shared groups remain a central differentiator |
| Short homepage omitted memory controls, schedules, devices, connections, and creative work | Six core differentiators on the homepage, plus a complete features and integration guide |
| Soft multicolor gradients and repeated generic cards | Cobalt, ink, bright citron, restrained surfaces, large DM Sans type, serif accents, and the existing Tim character |
| One static conversation | Three explicitly illustrative examples that visitors can switch between |
| Bot and skill libraries had small, dense text | Clearer typography, distinct bot identities, search, category filters, reset state, and direct bot anchors |
| Mac instructions still said TestFlight | Separate Mac release and iPhone beta paths, with invited-account requirements |
| Every route inherited homepage share descriptions | Route-specific titles, descriptions, canonical URLs and share tags; sitemap; handoff routes excluded from indexing |
| Desktop-first navigation with links removed at narrow widths | Keyboard-operable mobile menu, Escape dismissal, visible focus, no-JavaScript navigation fallback |

## Maintainer notes

- Bot and skill availability/counts continue to come from `catalog/catalog.json`; public catalog files remain byte-identical in the site build.
- `src/feature-content.ts` contains the maintained capability and integration copy. Review it whenever capabilities or provider boundaries change.
- The redesign keeps Vite, React, current package versions, the lockfile, Pages publishing, invitation token parsing, Apple association files, and billing handoff behavior.
- Typography is self-hosted. Provider images reuse the existing native app assets. No third-party font requests, analytics, or model calls were introduced.
- Legal and SMS policies receive the shared visual design; their terms were not rewritten.
- No native app, server, catalog behavior, cloud resource, or resource identifier changed.

## Verification

- `./scripts/verify.sh application` passed under Node 22: client/release boundary checks, 2 API contract tests, catalog validation, source-size checks, 4 website tests, TypeScript, the complete production build/prerender checks, and 14 catalog tests.
- Production JavaScript is 285,716 bytes (about 87.9 KB gzipped), within the existing 400 KB budget. Public catalog and skill bytes match their sources; the bundle contains no chat/auth/Expo dependencies or client backend configuration.
- Checked 12 page routes at 320, 390, 768, and 1440 pixels: 48 layouts, each with one main region, one H1, and no horizontal overflow. Production browser logs showed no warnings or errors during that sweep.
- Inspected homepage, library, features, and download layouts. Checked computed text contrast on those four routes; no below-threshold text was found by the targeted check. This is not a claim of a full accessibility certification.
- Exercised bot search, category filtering, no-results state, reset to all 17 bots, skill search and instruction links, example switching, FAQ expansion, keyboard menu opening, Escape dismissal, and restored menu focus.
- Verified that valid invitation parameters produce the expected native link and ignore an unrelated redirect parameter. Duplicate/invalid invitation kinds show recovery instructions and no app link.
- Checked 337 local links, fragment destinations, and asset references in the production HTML: no missing files or anchors. Provider images loaded successfully.
- Prerender checks cover every public page, route-specific canonical/share metadata, the sitemap, and non-indexed app/invitation/billing handoffs. Static page content and the mobile navigation fallback remain available without JavaScript.
- `git diff --check` passed. These checks cover the website; native app and cloud deployments are outside this change.
