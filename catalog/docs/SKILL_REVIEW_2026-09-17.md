# Skill review — 2026-09-17

## Decision

Add **Skill Builder** to Chief's default six-skill set. Keep the existing five group workflows. Do not add another universal skill now: Chief's prompt and the installed group skills already cover intake, decisions, planning, budgets, and handoffs, while research, data, creator, and career work are better selected for the job.

Skill Builder creates a private, focused skill only on an explicit request. Chief can attach it to itself or one selected teammate; other bots retain their existing self-authoring path. The created skill can require only tools already assigned to its owner. A one-time bootstrap update adds Skill Builder to existing Chiefs after the catalog publishes when they have room under the 12-skill limit, preserves their other settings, and does not re-add it after a user removes it.

## Redundancy and cleanup pass

All 16 public skills are referenced by at least one catalog bot, and every required tool is currently enabled. No published skill is a clear deletion candidate. Deleting a catalog skill would also disturb users whose bots are pinned to its version, so a removal needs a demonstrated replacement and migration plan.

The closest pairs serve different decisions: Group Intake gathers separate constraints before a choice; Group Decision compares options and records the result. Trend Scout ranks emerging signals; YouTube Strategy turns video evidence into a specific video plan. Deep Research synthesizes broad sourced questions; Morning Brief is a dated, short recurring briefing. Meme Lord captions a stored or supplied image; YouTube Thumbnail Director generates an original thumbnail. Their different triggers and outputs justify keeping them separate.

Chief has both group-specific skills and access to specialist templates because Chief is the only bot installed during setup. Removing trip, event, or budget skills from its defaults would weaken useful first-run work when no specialist has been added. The new Skill Builder is the only additional default recommended by this pass.

## Ideas checked

| Source | Useful pattern | HeyTim decision |
| --- | --- | --- |
| [mattpocock/skills](https://github.com/mattpocock/skills/blob/main/README.md) | Small, composable skills; distinguish explicitly invoked orchestration from reusable workflow guidance. | Make Skill Builder activate for an explicit reusable workflow request. Keep Chief's default set narrow. |
| [Anthropic skill creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) | Define triggers, near misses, expected outputs, and iterate with examples. | Add realistic positive, negative, and outcome cases to Skill Builder's `evals.json`. |
| [OpenAI skill creator](https://github.com/openai/skills/blob/main/skills/.system/skill-creator/SKILL.md) | Keep the core skill concise and include only guidance that changes decisions. | Use a short instruction-only workflow, with no copied executable helpers or broad persona text. |
| [Vercel agent skills](https://github.com/vercel-labs/agent-skills/blob/main/README.md) | Give specialized tasks specific activation criteria and quality checks. | Continue offering focused opt-in skills; developer-focused React, deployment, and design skills do not belong in Chief's consumer-facing defaults. |

## Ideas to revisit after usage evidence

- **Team Handoff:** add an opt-in skill if real Chief-to-bot or person-to-person handoffs repeatedly lose decisions, inputs, or ownership. Chief already requests these fields in its base prompt, so another default skill would duplicate it today.
- **Meeting Follow Through:** add an opt-in skill if users need a recurring workflow that turns meeting notes into decisions, owners, and due dates. Meeting Prep handles work before a meeting, and Group Decision handles unresolved choices; observe the gap before adding a package.

The reviewed repositories target coding agents and sometimes bundle scripts or tool integrations. HeyTim public skills remain instruction-only under this catalog's validation and review rules.

Catalog release `skills-v28` includes Skill Builder and supersedes the unshipped `skills-v27` audit changes. Publication still needs the matching backend deployment and versioned gateway schema assets before the public API and website can agree.

The subsequent `skills-v29` release updates Skill Builder with the GitHub import route and moves Chief's template to version 6. The Apple app can browse a public repository or direct `SKILL.md`, preview one file, and save an editable private instruction-only copy with its source link. Chief can then attach that saved skill to itself or another bot on request. Existing Chiefs with Skill Builder receive its new guidance once the catalog publishes; a user who removed it does not get it back. The app does not copy scripts, references, assets, or tool permissions from the repository.
