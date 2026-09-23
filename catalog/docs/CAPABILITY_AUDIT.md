# Capability audit

Updated September 23, 2026.

## Product lens

HeyTim's niche is group coordination: invite people easily, preserve editable shared memory, reach a decision, and automatically produce the itinerary, budget, list, brief, or file everyone can use.

The public catalog should contain workflows that materially change how a result is produced. Generic writing, summarizing, brainstorming, teaching, and planning remain available through the base model without separate skills.

## Shipped skills

- Group Trip Planner
- Event Planner
- Group Decision Helper
- Group Intake
- Shared Budget
- Deep Research
- Data Workspace
- Meme Lord
- YouTube Thumbnail Director
- YouTube Strategy
- Trend Scout
- Morning Brief
- Social Writer
- Meeting Prep
- Career Coach
- Skill Builder

The five group workflows are the product's core. Deep Research and Data Workspace remain as broadly useful advanced workflows. Meme Lord and the creator-research skills support an evidence-backed creator expansion. Morning Brief, Meeting Prep, and Career Coach add narrow outcome workflows whose sourcing, privacy, or artifact rules materially improve on a generic persona. Skill Builder makes explicit, private skill authoring repeatable and limits each new skill to the intended bot's existing tools. Generic writing, summarizing, brainstorming, and service-wrapper skills remain excluded because the base model already covers them and Git history preserves their earlier examples.

## Default skills

Chief installs the five group workflows and Skill Builder by default. These six cover coordination and on-demand creation of a reusable workflow. A one-off task is still handled directly; a skill is created only when the user explicitly requests one. The skill requires no new catalog tool because the app exposes guarded authoring actions only in direct bot chats. Chief can create a private skill for another existing bot; other bots can create a private skill for themselves. Existing Chiefs receive Skill Builder once when the new catalog version is available and they have room under the 12-skill limit, while preserving their other skills and allowing a later user removal.

No other skill is universal. Deep Research, Data Workspace, creator skills, and everyday specialists remain opt-in because their workflows and tool needs depend on the user's job. A generic writing or planning skill would duplicate baseline model behavior.

## Tool presentation

The fixed, user-facing tools are Web Search, Shared Lists, Files & Data, Interactive Browser, and Image Generator. Web Reader, Calculator, World Clock, Focused Delegate, Bot Manager, and Meme Lord's compositor remain internal dependencies. The legacy shared-credential X and YouTube Gateway tools are disabled and retired: they must not be offered as bot toggles or used as skill prerequisites. X search and YouTube search are functions of the user's connected account, assigned to a specific bot. This is a product access rule, not an API requirement for searching public content. The YouTube API also supports app-key searches, but HeyTim intentionally requires a user connection for the bot tool. See [YouTube search.list](https://developers.google.com/youtube/v3/docs/search/list) and [Google OIDC user identity](https://developers.google.com/identity/openid-connect/reference).

| Tool source | User-visible assignment | Scope |
| --- | --- | --- |
| Fixed web, browser, files, image and list tools | Toggle on each bot; fixed catalog entries | No private social account implied |
| X and YouTube | Connect the platform account, then toggle that specific account on a bot | Read/search through the user's OAuth grant; no posting or uploads |
| Home Assistant Assist | Add its public HTTPS Assist endpoint as an MCP server, then toggle that server on a bot | Only entities exposed to Assist; existing grants keep their connection IDs |
| Custom MCP server | Add a name, public HTTPS URL, and bearer token; repeat for multiple servers; toggle each connection on selected bots | The server's advertised tools are discoverable only after assignment; treat the server as trusted code/data |
| Other private providers | OAuth or GitHub App connection, then per-bot toggle | Provider-specific permissions, resource filters, and rate limits |

Connected providers are presented with X, YouTube, Slack, and Teams first, followed by the other integrations. The bot editor uses the same provider groups for connected and unconnected states, so a disconnected platform offers a Connect link rather than a nonfunctional tool toggle. The three creator skills that previously required retired global X/YouTube tools now require only their general research tools; their instructions use X or YouTube only if those specific account connections are assigned.

## Creator expansion

Creator Studio and Trend Scout are the first creator bots. Creator Studio deliberately installs both YouTube Strategy and YouTube Thumbnail Director so public research and image creation work together. Image Generator asks for a one-time Always Allow grant on first use; after the bot owner grants it, the bot can use the tool without per-action prompts, including in eligible schedules and owner-controlled group replies. Trend Scout is safe for point-in-time group or scheduled research, but it must not claim continuous monitoring unless the user configures a schedule.

The research and sequencing evidence is recorded in [BOT_CATALOG_RESEARCH.md](BOT_CATALOG_RESEARCH.md).

## Everyday specialists

Morning Brief, Social Writer, and Meeting Prep are featured catalog choices. Career Coach is available but not featured because it is valuable at a specific life moment rather than part of most users' recurring setup. None is installed universally; Chief remains the only setup-required bot, while featured specialists sort first and can be installed explicitly by a user or Chief.

Morning Brief and Meeting Prep use only read or sandbox capabilities, so they can participate in groups and point-in-time scheduled runs. Morning Brief cannot create its own schedule or read private calendars, email, or feeds. Meeting Prep deliberately stops before calendar changes, invitations, live attendance, or transcript processing. Social Writer has read-only public research and produces drafts only; it does not bundle Image Generator or any publishing connection, preserving group and schedule eligibility. Career Coach adds Files & Data for user-supplied resumes and editable artifacts but cannot submit applications or contact employers.

## Connection model

HeyTim supports three capability sources:

1. HeyTim built-ins maintained by the project.
2. Community skills and connector definitions merged into this public repository.
3. Private instruction-only skills created directly in the app, plus reviewed provider account connections.

HeyTim-owned keys for shared services stay server-side and are never entered by users. Private account access uses provider-specific OAuth; its per-user credentials are encrypted, retrieved only by the runtime, and excluded from prompts, skill documents, bot shares, and skill shares. Custom MCP servers can be added from the existing Connections screen with a URL and bearer token. Each endpoint has a separate server-side Secrets Manager secret and per-bot connection ID. A repeated URL replaces only that endpoint's credential; a different URL creates another server connection. The runtime rejects non-HTTPS, localhost, private-address, userinfo, query-string, fragment, and non-443 endpoints; it disables HTTP redirects and rechecks DNS before outbound requests. These checks narrow, but do not eliminate, DNS-rebinding and malicious-server risk. A production egress firewall or pinned-resolution transport remains a worthwhile hardening step before recommending arbitrary third-party MCP servers at scale. Server-provided tool descriptions are untrusted input, and a user should connect only servers they trust.

## Next integrations

The backend now has reviewed connections for Gmail, Google Workspace (Drive, Docs, Sheets, and Calendar), Slack, Notion, Microsoft 365 and Teams, GitHub, HubSpot, Jira, Zoom, YouTube, and X. A connection is usable only after its provider configuration and OAuth grant are available in the deployed environment and the user assigns it to a bot. The earlier Google, Notion, email, and Slack candidates are therefore no longer missing from the codebase.

The clearest remaining product tool is **read-only maps and places**: reliable place identity, addresses, travel times, and routes would improve group trips and events. Keep booking and purchases outside that first integration. Select a provider only after checking coverage, quotas, terms, source attribution, and user location privacy.

## AgentCore and Strands review

The September 2026 review found no missing general-purpose agent engine component. HeyTim already uses AgentCore Runtime, Memory, Gateway web search, Browser, Code Interpreter, Identity for platform keys, traces, a structural online evaluator, and production alarms. Strands supplies per-bot skills, delegation, task lists, streaming, memory access, and bounded context handling. The app backend owns chat history, group coordination, approvals, account scoping, and long-running work. A second AgentCore Harness would duplicate that custom orchestration rather than simplify it.

One runtime default was worth tightening: for a bot with no selected skills, Strands harness could scan a local skills directory. The runtime passes `skills=False`, leaving only the validated per-bot `AgentSkills` plugin. Its automatic context manager handles summarization and large-result offloading. [Strands harness skills](https://strandsagents.com/docs/user-guide/harness/configure/skills/), [Strands harness context management](https://strandsagents.com/docs/user-guide/harness/configure/context-and-caching/).

The next quality investment is **behavioral evaluation of actual skill and tool selection**. The checked-in scenario matrix pre-activates selected skills and runs without external tools; the deployed online evaluator detects structural completion failures. Neither proves that Chief chooses the right skill or that an agent calls the right connected tool for a realistic request. Start with synthetic accounts and deterministic tool stubs in an offline regression suite. AgentCore now offers skill-selection and skill-instruction evaluators, but they require skill and conversation content in traces; assess that against HeyTim's content-minimizing telemetry before enabling them on private production chats. [AgentCore skill evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/skill-evaluators.html).

Keep the following platform features out of the default build until there is a specific need:

- **AgentCore Policy:** it evaluates actions through Gateway; HeyTim's Gateway tools are currently read-only, while private-account actions have separate approval and authorization paths. Adding a policy engine now would not cover those paths. [AgentCore Policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html).
- **AWS Agent Registry:** the reviewed, versioned HeyTim catalog already owns public bot, skill, and tool discovery. Registry becomes useful for multiple teams or accounts publishing independent agents. [AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html).
- **AgentCore Consent Portal:** it requires a JWT-authenticated Gateway and an OpenID Connect provider, while this app uses its own reviewed OAuth flows and an IAM-authenticated Gateway. Revisit only if account consent moves to AgentCore Identity. [AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html).
- **AgentCore payments, A2A, and another sandbox:** no current chatbot workflow needs agent payments, a public agent-to-agent endpoint, or a second code/browser execution system.

At higher traffic, add durable per-user spending limits and consider Gateway rate limits for shared web-search capacity. The present runtime caps apply to one invocation, and AWS Gateway rate limits can cap callers, targets, or tools; the IAM Gateway currently sees the shared runtime identity, so per-user fairness would also need application-level identity or accounting. [Gateway rate limits](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-rate-limits/).
