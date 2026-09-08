# FroggyBot Product, UX, and Functional Audit

## Implementation follow-through — September 8, 2026

The repository has now completed the in-product release-gate work identified by this audit:

- Group-room attachments are authorized, copied into room-scoped encrypted storage, shown in the transcript, and provided only to the participating room bots.
- Direct and group routines now have a run inbox with output, activity, files, failures, retry, cancellation, and approval that resumes the same run.
- The preview now demonstrates a realistic three-specialist decision, named constraints and ownership, a reasoned synthesis, and a downloadable PDF.
- Modal and drawer semantics, focus trapping/restoration, control roles and state, loading labels, text contrast, and mobile drawer navigation were remediated.
- Sidebar previews are sanitized into bounded plain text; Room context, persistent Files / Tasks & runs access, and Quick / Advanced bot setup are implemented.
- Final team answers expose **Save decision**. Saved decisions preserve the source bot and saver, appear in the room ledger, can be removed by an authorized member, and become durable context for later team runs. Chief synthesis now requests a concise explanation of the constraints and specialist evidence used.
- The private-beta sign-in screen now offers a concrete access-request action.
- The separate public site now labels the private beta, offers a direct access-request path, demonstrates decision provenance, and gives every bot a representative request and result preview.

The current verification pass completed with all 21 Expo diagnostics, 10 frontend tests, 141 backend tests, 83 runtime tests, TypeScript checks, lint, source-size checks, and desktop/mobile browser journeys passing.

Two categories remain outside a safe code-only implementation: a production AWS target and alert recipient need real deployment values and an accountable destination, and the roadmap's metric-gated expansion items require user evidence before investment. Moderated user sessions, a production deploy/rollback/restore drill, global search, full notification/reply/mention parity, and the P2 expansion remain follow-up work rather than claims of completion.

## Original executive verdict (pre-remediation)

FroggyBot has a real product, not merely a promising interface. Direct chat, group rooms, specialist bots, scheduled work, generated files, memory controls, invitations, and approval flows are implemented; the repository's complete verification suite passes. The product is visually coherent on desktop and mobile, and the live application demonstrates that it can generate and deliver useful files. Its most distinctive interaction—the team round—also works end to end: a Chief frames the work, specialists contribute in sequence, and the Chief synthesizes the result.

The strongest market position is narrower than “an AI team.” Grok Bot, Claude Cowork, ChatGPT, Poe, and Microsoft all cover meaningful parts of that territory. FroggyBot's opportunity is to become **the shared decision room: one conversation in which several people and several trusted AI specialists make a decision and leave with the work done**. The combination of human group participation, explicit reply routing, room-isolated memory, visible specialist contributions, and downloadable outputs is unusually coherent. None of the reviewed competitors makes that complete loop its primary product promise.[^1][^2][^3][^4][^5]

The product should not yet be described as broadly launch-ready. The signature group experience cannot accept shared reference files, scheduled jobs lack a run inbox and history, the preview experience makes orchestration look generic, and important web accessibility failures allow keyboard focus to escape into hidden or background interfaces. The only configured AWS target explicitly says it is a development environment rather than a production baseline. These are tractable gaps, but several sit directly in the path of the product's main promise.

The recommended decision is therefore:

1. Position FroggyBot around group decisions and completed outcomes, not around generic autonomous agents.
2. Make one realistic shared-room scenario exceptional before expanding the feature surface.
3. Treat group files, trustworthy run visibility, accessibility, and a production deployment baseline as release gates.
4. Build the next moat around decision provenance, room-scoped trust, and reusable group workflows—not a cloud desktop or an unrestricted tool marketplace.

## Scope and evidence

This audit combines six forms of evidence:

- A repository review of the Expo product, Amplify backend, AgentCore runtime, architecture, operating procedures, parity roadmap, and verification history.
- A clean run of the repository-wide verification suite on September 8, 2026. AgentCore validation, CDK build/tests, runtime lint and tests, frontend unit tests, type checks, lint, Amplify checks, backend tests, Expo diagnostics, web export, and security checks all passed.
- Hands-on evaluation of the local preview at desktop and 390-by-844 mobile viewports.
- Read-only inspection of the authenticated live application, including a real generated PDF, scheduled-message treatment, activity disclosure, and public bot-library handoff.
- Keyboard, accessibility-tree, DOM-state, contrast, and console inspection of important flows.
- Competitor research using current first-party product and support documentation.

The audit did not include moderated usability sessions, destructive tests against a live account, App Store review, a full assistive-technology test matrix, or laboratory performance measurement. Findings about user comprehension should therefore be validated with target users, while the observed functional and accessibility defects are directly reproducible.

## The product FroggyBot should be

The product currently contains three overlapping mental models:

- a familiar messaging application;
- a roster of configurable AI specialists;
- an automation and artifact workspace.

The messaging model is the right front door because it minimizes learning. The specialist roster explains capability, and automation extends the relationship over time. The hierarchy becomes confusing only when all three are presented as equally central. “Create a bot,” “add a skill,” “configure required tools,” and “schedule a task” are implementation concepts. The customer-level job is simpler:

> Help our group turn an unresolved conversation into a trusted decision, an assigned plan, or a finished deliverable.

That job gives every major feature a clear role:

- The **room** contains the people, source material, and shared context.
- The **specialists** contribute distinct expertise.
- The **Chief** resolves and synthesizes, rather than merely repeating.
- The **room memory** records durable constraints and preferences.
- The **artifact** is the usable outcome.
- The **schedule or routine** keeps the outcome current.

This product model also creates a useful boundary. FroggyBot does not need to become a general remote computer to deliver its core value. It needs to be exceptional at collaborative deliberation, traceable synthesis, and follow-through.

## Experience audit

### 1. Marketing, acquisition, and sign-in

The public site communicates the benefit better than the in-product terminology. “Turn group talk into a plan everyone can use” is concrete, human, and well aligned with the strongest use case. The pages are visually confident, the public bot library is searchable and categorized, and the “Add this bot” handoff correctly opens the relevant template for an already signed-in member.

The acquisition loop is incomplete for anyone who is not already invited. “Open FroggyBot” leads to a sign-in page that says the product is for existing members only. That may be intentional during a private beta, but it produces a dead end after the marketing site has generated interest. The product should explicitly label the beta state and offer one next action: request access, join a waitlist, or ask an existing member for an invite. If growth is meant to be invitation-led, the site should explain that rather than making it look like a failed signup.

The bot library is attractive but asks visitors to infer value from names and taglines. Each template should include one representative request and one compact result preview. “Event Planner” becomes much more credible when the card shows a sample run-of-show, budget, and downloadable checklist. Example outputs are especially important because FroggyBot is selling completion rather than conversation.

**Verdict:** strong message and visual credibility; weak conversion path and insufficient proof.

### 2. First-run experience and activation

The preview shell is polished and immediately understandable. Bots and groups appear in a familiar sidebar, the composer is calm, and creation choices are logically grouped into bot library, custom bot, and new group. A new user can explore the product without learning a novel navigation system.

The preview's signature team response is currently the largest onboarding liability. In the tested group round, the Chief displayed a useful sequence of statuses—framing, specialist work, and synthesis—but each specialist contribution largely repeated its template tagline, and the final answer was generic. The interaction design promises an expert team; the content demonstrates a scripted mock. That mismatch risks reducing trust precisely when the product needs to establish it.

Preview mode should instead stage a credible five-minute win:

1. Start with a recognizable group goal, such as choosing a weekend trip within a fixed budget.
2. Include two people with visibly different constraints.
3. Give the Research specialist evidence, the Planner a structured proposal, and the Chief a reasoned tradeoff.
4. Produce a compact itinerary or budget artifact.
5. Prompt the user to change one constraint and show the team update the result.

This is also a better activation definition than “created a bot.” The meaningful activation event is: **a second person joins a room, the room receives a multi-specialist result, and someone uses or shares the output**.

**Verdict:** excellent shell, but the demo undersells the core intelligence and outcome.

### 3. Direct conversations

Direct chat is the most mature experience. It supports attachments, response cancellation, activity disclosure, approvals, generated artifacts, dictation, and schedules without making the composer visually busy. The live application showed an inline PDF card, a concise “step completed” disclosure, and a scheduled-message label. These details make the system feel operational rather than theatrical.

Several high-value capabilities are hidden behind the bot action menu: editing, documents, schedules, setup sharing, and conversation clearing. That keeps the header clean, but it also makes recurring value hard to discover. Documents and scheduled work should become persistent secondary destinations—tabs, a compact room utility bar, or a clearly labeled “Work” surface—once either contains content.

Sidebar previews need a presentation pass. Live previews can expose raw Markdown markers, code formatting, and long generated fragments. They should be converted to plain text, stripped of structural syntax, and summarized to a stable one- or two-line preview. The sidebar's job is recognition, not faithful rendering.

**Verdict:** solid and usable; improve discovery and information hygiene.

### 4. Group rooms and team rounds

Group rooms are FroggyBot's strategic center. The tested room successfully supported a people-only message, adding two specialists, selecting a reply target, and completing a Chief-led team round. Progress states made the orchestration legible instead of presenting a long silent wait. That transparency is one of the product's best pieces of interaction design.

The reply controls—people only, a specific bot, Chief, or team—are powerful but require clearer language. “People only” describes who will not answer rather than what will happen. “Chief” and “Team” assume the user already understands the roster hierarchy. A clearer set could be:

- **Just the group** — post without an AI reply.
- **Ask [bot]** — one specialist responds.
- **Ask the Chief** — one synthesized response.
- **Bring in the team** — specialists contribute and the Chief resolves.

The team round must also prove that each specialist has a real role. Contributions should be distinct, attributable, and useful on their own. The final synthesis should show which constraints or evidence changed the recommendation. Without this, the visible multi-agent sequence adds latency but not perceived intelligence.

The largest functional contradiction is group attachments. The public promise centers on group planning and useful outputs, yet the composer enables file attachment only when a direct bot is selected. The implementation explicitly passes `canAttach={Boolean(bot)}`, excluding group rooms. A travel plan without shared reservation details, an event without venue proposals, or a project room without a brief is structurally incomplete. Group files and shared references are not parity polish; they are part of the core job.

Room context is currently split across a bar labeled “Shared memory,” a “Pinned group notebook,” and “Learned group memory.” These are different concepts but are presented as near-synonyms. Use a visible **Room context** destination with three plain-language sections:

- **Files and links** — source material available to the room.
- **Pinned facts** — constraints or decisions people deliberately maintain.
- **What FroggyBot learned** — editable inferred preferences, with source and date.

The next collaboration layer should record decisions and owners, not imitate every consumer-chat feature. Threaded replies, reactions, mentions, unread markers, and mute settings will eventually matter, but a decision ledger is more differentiating. A completed team answer should offer “Save decision,” “Assign next steps,” and “Create/update routine.”

**Verdict:** genuinely differentiated and functionally real; missing shared inputs and stronger evidence of specialist value.

### 5. Bots, skills, and tools

FroggyBot offers unusually deep customization: identity, prompt, skills, required tools, optional tools, private connections, and approval behavior. The skills-and-tools screen explains the conceptual difference among prompt, skills, and tools better than most developer-oriented products. Private-tool boundaries and interactive approval controls reinforce trust.

The editor nonetheless presents the system's internal model too early. A user creating “Neighborhood Event Helper” should not need to reason through a long form of prompt, skills, required tools, extra tools, and approvals before seeing value. Provide two layers:

- **Quick setup:** name, what it helps with, tone, and the information it should always remember.
- **Advanced:** system prompt, explicit skills, tool policy, model/runtime options if ever exposed, and approval details.

Templates should remain editable, but editing should start from an outcome description and example tasks. When an advanced setting creates risk—such as allowing an interactive tool—the interface should explain the consequence in user language at the point of choice.

The best long-term learning loop is “save what worked.” Grok Bot already lets users turn successful work into a reusable skill and supports routines with run records.[^1] FroggyBot should let a room convert a strong turn into a reusable room routine without requiring the user to reverse-engineer a prompt. This would connect the product's best moment to retention.

**Verdict:** powerful foundation; too much power-user configuration before value.

### 6. Scheduled work and approvals

The schedule editor works and is understandable. It supports daily, weekdays, weekly, and monthly recurrence, a timezone, active state, manual run, and deletion. The backend verification history confirms schedule creation, execution, and deletion in a disposable live workflow.

The missing surface is operational confidence. A recurring job is only trustworthy if the user can answer:

- Did it run?
- What did it produce?
- Is it waiting for me?
- Did it fail, and will it retry?
- What changed since the last run?

The product currently lacks a run inbox/history with status, duration, output, failures, and pending approvals. Interactive writes are already appropriately constrained in groups and scheduled execution, but a denial without a resumable item becomes a dead end. ChatGPT and Grok Bot both expose task/routine management and run visibility, while Claude carries schedules across its surfaces.[^1][^2][^3]

Create a unified **Runs** surface covering scheduled work and longer team tasks. Each run should show queued/running/succeeded/failed/needs approval/cancelled, its initiating room or bot, output, and any action needed. A paused approval should resume the same run after authorization rather than asking the user to start over.

**Verdict:** scheduling mechanics work; monitoring and recovery are not yet productized.

### 7. Artifacts, documents, and outcomes

Documents are a strong part of the product promise. Direct chats can generate files, the live interface renders downloadable cards, and the documents screen works. The product should make artifacts more central to its story because they are evidence that the conversation finished something.

The current documents surface behaves like a per-bot file list. The stronger model is a room outcome library with previews, provenance, version, and status. Each artifact should answer:

- Which conversation and source materials produced it?
- Which specialists contributed?
- When was it last updated?
- Is it a draft, accepted decision, or superseded version?
- Can a scheduled run keep it current?

Grok Bot emphasizes previews, evidence, and action logs for outputs.[^1] FroggyBot can differentiate by tying those properties to a multi-person decision: not only “the agent created this,” but “the room accepted this after these constraints were resolved.”

**Verdict:** important working capability; promote it from a hidden utility to the proof of completion.

### 8. Memory, privacy, and trust

The architecture's separation of private bot memory and group-scoped memory is one of FroggyBot's strongest trust decisions. Group members can manage learned group memory, and private direct-chat context is not intended to leak into a room. Interactive tool approvals also default toward explicit human control. These choices should be visible product benefits, not implementation details.

Trust needs provenance. A learned memory should show where it came from, when it was learned, where it is used, and who can see it. “Shared with this group” and “Learned from conversation” are a good start. Add a plain-language privacy summary when a bot joins a room: what it can access, which private sources remain unavailable, and which actions require approval.

Grok's bots share one user-scoped computer, which its documentation explicitly says is not a security boundary.[^1] FroggyBot should lean into the opposite mental model: **rooms are bounded contexts, and adding a specialist does not silently import its private history**. That is legible, safe, and well suited to family and small-team collaboration.

**Verdict:** strong architectural differentiation; make scope and provenance continuously visible.

### 9. Mobile responsiveness

At a 390-by-844 viewport, the main room, header, shared-context bar, messages, composer, and drawer fit well. Touch targets are generally comfortable and the layout retains the same mental model as desktop. The mobile navigation feels intentionally composed, not simply squeezed.

The drawer is only visually modal. Keyboard focus can immediately move to the underlying “Details” control, and background content remains exposed to the accessibility tree. This affects mobile users with keyboards and switch devices as well as desktop users testing a narrow viewport. The drawer needs dialog semantics, an accessible name, focus placement on open, focus containment, background hiding, Escape handling on web, and focus restoration on close.

**Verdict:** visually strong; modal interaction semantics are incomplete.

### 10. Accessibility and inclusive UX

Accessibility is the clearest release-quality weakness. The following issues were observed directly:

- Opening the mobile drawer did not move or trap focus; Tab focused content behind it.
- After navigating from an action sheet to Documents, keyboard focus could still reach controls belonging to the hidden action sheet.
- Group reply chips changed visually but did not expose a selected or pressed state in the rendered web DOM.
- Visually selected bot checkboxes and schedule radio options did not expose their checked state correctly in the inspected accessibility tree.
- Several actionable `Pressable` elements have no explicit role, including Exit preview, memory edit actions, and the drawer backdrop. A static scan found 6 of 91 opening `Pressable` elements without `accessibilityRole`; role presence alone does not guarantee correct semantics.
- The mobile loading indicator had no accessible status or label.
- Multiple normal-text colors fall below the WCAG AA 4.5:1 contrast threshold: composer hint 2.61:1, sidebar section text 3.17:1, timestamps 2.42:1, auth footnote 2.60:1, editor subtitle 3.62:1, library metadata 3.31:1, and invitation labels 3.16:1.[^6]

These are not abstract compliance concerns. They make state unknowable and navigation unpredictable for keyboard and screen-reader users. WCAG requires user-interface components to expose name, role, and state, and requires focus order to preserve meaning and operability.[^7][^8]

Before broader beta, run a focused remediation and regression pass:

1. Implement one shared modal/sheet primitive with focus management and background isolation.
2. Use native web semantics for toggles, checkboxes, radio groups, and selected reply targets where possible; otherwise map React Native accessibility state to verifiable ARIA output.
3. Add accessible names and roles to every icon-only or text-like action.
4. Raise all normal secondary text to at least 4.5:1 and large text to at least 3:1.
5. Test critical journeys with keyboard-only navigation and VoiceOver on iOS/Safari, plus one desktop screen reader.
6. Add automated accessibility checks for the web export, while retaining manual modal and screen-reader tests.

**Verdict:** visually refined but not yet reliably operable with assistive technology.

## Functional and readiness scorecard

Scores reflect the current product experience, not code quantity. Five means the capability is coherent, trustworthy, and ready for its intended audience.

| Area | Score | What works | What prevents a 5 |
| --- | ---: | --- | --- |
| Direct chat | 4/5 | Attachments, stop, approvals, activity, files, dictation | Important work is hidden; previews are noisy |
| Group collaboration | 3.5/5 | People-only posting, bot targeting, invites, team rounds, shared memory | No group files; limited conversation mechanics; terminology overlap |
| Specialist orchestration | 3/5 | Visible Chief/specialist sequence and final synthesis | Sequential only; weak demo contributions; limited provenance |
| Bot creation and customization | 3.5/5 | Deep prompts, skills, tools, templates, sharing | Editor is long and technical; no progressive disclosure |
| Scheduled work | 2.5/5 | Recurrence, timezone, active state, run now, backend execution | No run inbox/history, retries, or resumable approvals |
| Artifacts | 3.5/5 | Generation, download cards, document listing | Hidden location; weak provenance/versioning; not yet group-centered |
| Memory and trust architecture | 4/5 | Group isolation, editable learned memory, explicit approvals | Scope/provenance need stronger in-product explanation |
| Integrations | 2/5 | Web/content tools, Gmail shortcut, private MCP | Narrow connector set; limited consumer group inputs |
| Mobile visual UX | 4/5 | Responsive, compact, consistent | Drawer semantics and assistive navigation |
| Accessibility | 2/5 | Many controls have labels/roles and touch sizing is generally good | Modal focus, state exposure, roles, status labels, contrast |
| Reliability evidence | 4/5 | Complete local verification passes; live disposable workflow passed | Some runtime deprecation debt; no production target |
| Production readiness | 3/5 | Backups, alarms, redaction checks, deployment evidence | Development-only target; alert recipient pending; production drills absent |

The engineering baseline is healthier than the UX gaps might imply. The September 5 live-development evidence records 40 authenticated bootstrap requests at concurrency eight with zero failures and 2.12-second p99 latency, successful attachment/schedule/share/approval/cancellation/deletion workflows, successful restore drills, and clean service alarms. It also records that a human or incident-system alarm subscription was still pending. The repository itself warns that none of this substitutes for a dedicated production target.

## Competitive landscape

The competitive set divides into four shapes: autonomous agent workspaces, AI project workspaces, bot marketplaces, and enterprise collaboration platforms. FroggyBot should learn from each without inheriting all of their complexity.

| Capability | FroggyBot | Grok Bot | ChatGPT | Claude Cowork | Poe | Copilot in Teams |
| --- | --- | --- | --- | --- | --- | --- |
| Persistent named specialists | Strong | Core product | GPTs/agents, less room-centric | Plugins/subagents | Large bot marketplace | Agents |
| Several people in one live AI room | Core direction | Not the primary documented model | Group chats retired; shared projects remain | Shared projects, not shared live task sessions | Users and bots can be mentioned in chats | Native channels/group/meeting chats |
| Several AI specialists in one conversation | Working sequential team round | Strong, including parallel coordination | Limited as a user-facing room model | Subagents inside tasks | Multiple bots via mentions/workflows | Possible through installed agents, not a unified team ritual |
| Room-scoped editable memory | Strong foundation | Durable user/bot context; shared computer model | Project memory/instructions | Project files/context/instructions/memory | Chat context | Tenant/agent configuration |
| Files and useful artifacts | Direct chats only for input; output works | Strong previews, files, evidence/actions | Strong files/canvas/project sources | Strong files/previews/artifacts | Bot-dependent | Strong Microsoft 365 grounding |
| Scheduled/event work | Basic recurring schedules | Routines, event triggers, run records | Scheduled tasks and connectors | Scheduled tasks | Bot-dependent | Broad Power Platform automation |
| Tool approvals and trust | Explicit approval foundation | Action-specific approvals and logs | Task approvals for some actions | Permission/connectors model | Creator-defined | Enterprise governance |
| Consumer-friendly shared decision focus | Best opening | Agent-work focus | General assistant/project focus | Knowledge-work focus | Bot discovery/creation focus | Enterprise work focus |

### Grok Bot

Grok Bot is the closest conceptual competitor for the “team of agents” claim. It offers persistent named bots, a shared cloud computer, files, browser and terminal use, multi-bot coordination, parallel work, context handoffs, routines, event triggers, run records, approvals, searchable history, and teach-by-demonstration.[^1] Its design language emphasizes a roster of coworkers, visible progress, and removing management overhead.

Trying to match that feature-for-feature would pull FroggyBot into expensive infrastructure and a security model that is not necessary for the initial wedge. FroggyBot's advantage is that the room belongs to a human group and has an explicit context boundary. The comparison should be “make this decision with us,” not “operate my computer for me.”

### ChatGPT

ChatGPT has broad familiarity, shared projects, project files and instructions, project-only memory, connected apps, saved project sources, and scheduled tasks. OpenAI's help center says ChatGPT group chats were retired on July 9, 2026; users can retain content by converting a group chat into a standard conversation.[^2] This removes a direct first-party group-chat surface but does not remove ChatGPT's distribution, model quality, or project collaboration.

FroggyBot should exploit the product-shape gap: a persistent live room with several humans and explicit specialist roles. It cannot win by offering a generic single-assistant chat with folders.

### Claude Cowork

Claude Cowork combines projects, files, instructions, memory, plugins, connectors, subagents, scheduled tasks, and continuity across web, desktop, and mobile.[^3] It is a strong benchmark for a calm knowledge-work interface and progressive disclosure. Its shared projects support common context, but its documented model is still centered on individual task sessions rather than a shared live conversation among several people.

FroggyBot should borrow Cowork's clarity around project context and plugins while preserving the immediacy of a group chat. It should not expose every configuration primitive in the primary flow.

### Poe

Poe is the marketplace and multi-bot comparison. Its developer platform supports mentioning bots and users within the same chat and constructing multi-model workflows.[^4] It has far greater breadth and creator supply, but that breadth makes consistent trust, shared memory, and outcome quality harder to guarantee.

FroggyBot should prefer a curated specialist roster and a coherent room contract. “Eight specialists that reliably finish common group jobs” is more valuable for the initial audience than hundreds of bots with uneven behavior.

### Microsoft Copilot in Teams

Microsoft lets organizations publish agents into Teams and add or mention them in channels, group chats, and meeting chats, with enterprise sharing and administration.[^5] This is formidable inside Microsoft-centered workplaces.

FroggyBot should avoid competing first on enterprise administration. Its opening is cross-context, consumer-friendly collaboration for families, friends, community organizers, and small project teams who do not want to configure a Microsoft tenant or build a Copilot Studio agent.

## Differentiation to own

### Primary position: the shared decision room

Recommended product sentence:

> **FroggyBot is the shared room where people and AI specialists make a decision and leave with the work done.**

Shorter campaign line:

> **Group chat that finishes the work.**

This position is specific enough to guide prioritization and broad enough to support trips, events, household decisions, purchases, research, volunteer groups, and small projects. It also explains why the product needs both people and specialists.

### Four defensible product pillars

1. **Human-group first.** The room is not one person's agent console with guests added later. Everyone can contribute constraints, ask a specialist, and understand how a conclusion was reached.

2. **Bounded shared context.** Files, pinned facts, learned preferences, and decisions belong to the room. Private bot memory and private connections do not silently cross the boundary.

3. **Visible deliberation.** Specialists make distinct, attributable contributions; the Chief resolves conflicts and explains the tradeoff. The interface shows meaningful progress without requiring users to manage agents.

4. **Decision-to-outcome.** Every substantial room can end in a decision, owners, a checklist, budget, itinerary, comparison, or other durable artifact. Schedules keep the result current.

Together these create a stronger moat than the number of bots or models. The durable asset becomes a high-quality record of how a group works: its constraints, accepted decisions, effective routines, and trusted specialist patterns.

### What not to lead with

- **“Your team of autonomous AI agents.”** Accurate in spirit but crowded and invites an unfavorable Grok comparison.
- **A cloud computer or desktop takeover.** High cost, support burden, and security risk without strengthening the shared-room wedge.
- **An unrestricted bot marketplace.** Supply breadth would dilute quality and trust before demand is proven.
- **Enterprise administration.** Necessary only after a design partner requires it.
- **Model choice.** Buyers care about a resolved decision and usable result, not which provider generated each paragraph.

## Prioritized roadmap

### Now: release gates

| Priority | Change | Why it is a gate | Minimum acceptance evidence |
| --- | --- | --- | --- |
| P0 | Replace the placeholder preview with a realistic shared-room scenario | The demo currently weakens belief in the signature capability | Three distinct specialist contributions, a reasoned synthesis, a downloadable output, and successful comprehension in five target-user sessions |
| P0 | Add group attachments and shared reference files | Core group jobs require source material | Every room member can add/view/remove permitted files; all participating bots receive only room-authorized references; mobile and web pass |
| P0 | Build a run inbox and history | Recurring work is untrustworthy without status and recovery | Status, timestamps, output, error, retry, cancellation, and resumable approval are visible for every run |
| P0 | Fix modal semantics, control state, accessible names, and contrast | Current keyboard and screen-reader failures block users | Keyboard and screen-reader critical-path checklist passes; normal text meets WCAG AA; automated regressions added |
| P0 | Establish a dedicated production target and alert recipient | Current deployment explicitly is not a production baseline | Production deploy/rollback/restore drill completed; alerts reach an accountable human/system; authenticated smoke workflow passes |
| P0 | Sanitize sidebar message previews | Raw model formatting harms scanning and perceived quality | Markdown/code stripped, stable two-line plain-text summary, useful fallback for artifacts/tool activity |

### Next: make the wedge unmistakable

| Priority | Change | Intended result |
| --- | --- | --- |
| P1 | Replace “Shared memory” with a Room context surface | Users distinguish files, pinned facts, learned memory, decisions, and access boundaries |
| P1 | Add a decision ledger and next-step ownership | Rooms finish with an accepted decision and accountable actions |
| P1 | Add provenance to the Chief synthesis | Users can see which specialist, source, or group constraint affected the result |
| P1 | Introduce Quick setup and Advanced bot editing | New users create a useful specialist without understanding prompt/tool architecture |
| P1 | Make Documents and Runs persistent after first use | Finished work and automation become discoverable retention surfaces |
| P1 | Save a successful answer as a reusable routine/skill | High-value work compounds instead of disappearing into chat history |
| P1 | Add global search across messages, files, decisions, and runs | Persistent rooms stay usable over time |
| P1 | Add unread state, notification controls, replies, and mentions | Multi-person rooms support normal collaboration without becoming noisy |

### Later: expand power after the core loop retains

| Priority | Change | Trigger to invest |
| --- | --- | --- |
| P2 | True parallel delegation and bot-to-bot handoffs | Team rounds are frequent and latency/complexity is a measured barrier |
| P2 | Event and webhook triggers | Users repeatedly ask routines to react to mail, calendars, forms, or external systems |
| P2 | Curated connectors for calendar, maps, reservations, documents, and tasks | One vertical shows repeated demand and safe authorization patterns |
| P2 | Roles, billing, audit export, and workspace administration | A paying team or organization requires them |
| P2 | Curated third-party specialist publishing | First-party specialists have quality evaluation, permissions, and outcome metrics |

## Measurement and research plan

The product should measure completed group outcomes, not message volume. A useful north-star metric is:

> **Weekly rooms with a multi-person, multi-specialist outcome that is accepted, downloaded, assigned, shared, or scheduled.**

Supporting funnel measures:

| Stage | Event or measure | What it answers |
| --- | --- | --- |
| Acquisition | Marketing visit → request access/invite redemption | Is the public promise converting? |
| Setup | Room created → second person joined | Does the group model activate? |
| First value | Joined room → first useful team result | How quickly does collaboration pay off? |
| Outcome | Result → accepted decision/artifact/assignment | Did the conversation finish work? |
| Retention | Outcome → repeated room use within 7/28 days | Is the room becoming infrastructure? |
| Automation | Routine created → successful runs → outputs used | Does scheduled work create durable value? |
| Trust | Approval response, memory edit/delete, provenance open | Are controls understandable and useful? |
| Quality | Reruns, rewrites, cancellations, “people only” fallback | Where does AI participation fail or annoy? |

Instrument reply-target changes, team-round phases, specialist inclusion, artifact interactions, decisions, assignments, schedule states, approval pauses, and accessibility-critical errors. Do not log private content merely to obtain analytics; event properties should identify states and object types, not message bodies.

Run three research tracks in parallel after the release gates:

1. **Comprehension tests:** Can a new participant explain the difference among Just the group, Ask the Chief, and Bring in the team? Can they identify what context is shared?
2. **Outcome diary:** Follow 8–12 real groups for four weeks and catalog which decisions recur, which outputs leave the app, and where people fall back to another tool.
3. **Wedge comparison:** Test trip planning, event planning, and a small project brief against ChatGPT, Claude Cowork, and ordinary group chat. Measure time to accepted decision, number of manual context transfers, and confidence—not subjective “AI quality” alone.

## Launch decision checklist

FroggyBot is ready for a controlled design-partner beta now, provided expectations are explicit and support is close. Broader public promotion should wait until all of the following are true:

- Group rooms accept and correctly scope shared files.
- The preview demonstrates a credible team result and artifact.
- Scheduled and long-running work has a run history, visible failures, and resumable approvals.
- Critical keyboard and screen-reader journeys pass, and normal text meets WCAG AA contrast.
- A dedicated production target, alert recipient, rollback plan, and restore drill exist.
- The public site offers a valid next action to a visitor without an invite.
- Analytics can measure joined rooms, useful team outcomes, and retained group use without collecting unnecessary content.

The product does not need another broad feature wave before those gates. It needs its best idea—the shared decision room—to feel unquestionably real, trustworthy, and complete.

## Sources

[^1]: xAI, [Grok Bot overview](https://docs.x.ai/grok-bot/overview); [Chat and collaboration](https://docs.x.ai/grok-bot/chat-and-collaboration); [Skills, routines, and automations](https://docs.x.ai/grok-bot/skills-routines-and-automations); [Files and results](https://docs.x.ai/grok-bot/files-and-results); [Approvals, security, and privacy](https://docs.x.ai/grok-bot/approvals-security-and-privacy); and [Designing Grok Bot](https://x.ai/news/designing-grok-bot), accessed September 8, 2026.
[^2]: OpenAI, [Projects in ChatGPT](https://help.openai.com/en/articles/10169521); [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617); and [Group chats in ChatGPT](https://help.openai.com/en/articles/12703475-group-chats-in-chatgpt), accessed September 8, 2026.
[^3]: Anthropic, [Use plugins in Claude](https://support.claude.com/en/articles/13837440-use-plugins-in-claude); [Get started with Claude Cowork](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork); [Organize tasks with projects in Claude Cowork](https://support.claude.com/en/articles/14116274-organize-your-tasks-with-projects-in-claude-cowork); and [Use Claude Cowork on web, desktop, and mobile](https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile), accessed September 8, 2026.
[^4]: Poe, [Server bot functional guides](https://creator.poe.com/docs/server-bots/server-bots-functional-guides) and [Script bots quick start](https://creator.poe.com/docs/script-bots/quick-start), accessed September 8, 2026.
[^5]: Microsoft, [Add an agent to Microsoft Teams](https://learn.microsoft.com/en-us/microsoft-copilot-studio/publication-add-bot-to-microsoft-teams), accessed September 8, 2026.
[^6]: W3C Web Accessibility Initiative, [Understanding Success Criterion 1.4.3: Contrast (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), accessed September 8, 2026. Ratios in this audit were calculated from computed foreground and background colors in the local web preview.
[^7]: W3C Web Accessibility Initiative, [Understanding Success Criterion 4.1.2: Name, Role, Value](https://www.w3.org/WAI/WCAG22/Understanding/name-role-value), accessed September 8, 2026.
[^8]: W3C Web Accessibility Initiative, [Understanding Success Criterion 2.4.3: Focus Order](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html), accessed September 8, 2026.

### Internal evidence

- `README.md` and `apps/froggybot/README.md`, product model and implemented capabilities.
- `docs/architecture.md`, authorization, memory, scheduling, artifact, and group-boundary design.
- `docs/grokbot-parity-roadmap.md`, implemented-versus-live status, intended differentiation, known gaps, and deferral decisions.
- `docs/verification-history.md`, dated live-development performance, workflow, recovery, redaction, and alarm evidence.
- `agentcore/aws-targets.json`, development target status.
- `apps/froggybot/src/features/chat/conversation-panel.tsx`, group attachment exclusion at line 203.
- `apps/froggybot/src/features/chat/chat-app.tsx`, mobile drawer implementation at lines 396–400.
- `apps/froggybot/src/features/chat/message-composer.tsx`, group reply-chip semantics at lines 185–205.
- Hands-on local preview and read-only live application evaluation, September 8, 2026.
