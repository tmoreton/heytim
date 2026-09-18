# HeyTim Bots

This directory is the maintained monorepo source for HeyTim's ready-made bots,
reusable skills and reviewed tool definitions. Imported from the former public
`tmoreton/heytim-bots` repository at commit `62a1f53`; its history remains there.

- [app.heytim.ai](https://app.heytim.ai) is built from `../apps/website` using Vite and React.
- `bots/` contains evaluation scenarios for the small bot configurations in `catalog.json`.
- `skills/` contains readable, instruction-only ways of working.
- `tools/` contains the canonical, narrowly scoped OpenAPI definitions for reviewed external services.
- `catalog.json` is the machine-readable catalog consumed by the website and HeyTim app. The website presents its ready-made bots; skills and tools remain composable building blocks in the code.

There is no maintained browser chat. The website hands invitation links to the
native Apple app. Catalog publishing is independent of Apple releases.

## Repository map

```text
bots/<bot-id>/evals.json     Realistic prompts and observable outcome expectations
skills/<skill-id>/SKILL.md   One public skill per folder
skills/<skill-id>/evals.json Trigger examples and outcome expectations
tools/<provider>/            Reviewed external API definitions
infrastructure/              Declarative deployment for provider-specific gateway targets
scripts/validate_catalog.py  Catalog and package safety checks
tests/                       Catalog, capability, and publication checks
docs/                        Catalog decisions and maintainer notes
```

## Contribute a skill

1. Search `catalog.json` and existing pull requests.
2. In the monorepo's `catalog/` directory, copy the closest folder under `skills/`.
3. Give the folder a lowercase, hyphenated ID such as `trip-planner`.
4. Write a concise `SKILL.md` with only `name` and `description` in its frontmatter.
5. Add an `evals.json` file with realistic matches, near-misses, and outcome expectations.
6. Add the public metadata and reviewed `requiredToolIds` to `catalog.json`.
7. Run the checks below and open a pull request.

```bash
python3 scripts/validate_catalog.py
npm --prefix ../apps/website run build
python3 -m unittest discover -s tests
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the complete review rules and a copyable catalog example. If you only have an idea, use the [skill request form](https://github.com/tmoreton/heytim-bots/issues/new?template=skill-request.yml).

You do not need a pull request to make a private instruction-only skill. Add it directly in the HeyTim app. Repository review is required to make a bot, skill, or tool publicly discoverable.

## Contribute a bot

A public bot is intentionally just configuration: its identity, prompt, existing skill IDs, and any directly required tool IDs. It never chooses a model, reasoning level, schedule, memory policy, approval mode, or credential. Add its entry to the `bots` array in `catalog.json`, add at least three scenarios under `bots/<bot-id>/evals.json`, and follow the review rules in [CONTRIBUTING.md](CONTRIBUTING.md).

Chief is published here like every other bot. HeyTim setup requires the `chief` template and applies its protected coordinator role after installation; the public configuration itself needs no app-only role or setup fields.
Chief includes Skill Builder by default, so an explicit request in a direct chat can create a private skill for Chief or an existing teammate without granting new tools. Existing Chiefs receive it once after the new catalog is available, unless they have reached the 12-skill limit; a user can remove it later.

Installing a public bot never asks the user for a developer API key. HeyTim supplies credentials for shared public services, while access to private account data uses a provider-specific **Connect account** flow.

## Skill rules

- Skills are instructions and optional static Markdown, text, or JSON references.
- Skills cannot contain executable code, binaries, secrets, tokens, or hidden remote instructions.
- Each skill should solve one recognizable user outcome and explain its important boundary.
- Required tools are declared once in `catalog.json`; skill frontmatter does not repeat runtime bindings.
- Existing behavior is immutable. Bump `version` before changing instructions that users may rely on.

## Propose a tool

Tools can access services or take actions. A public proposal must describe the exact actions, data involved, authentication, external side effects, and least permissions needed. Contributors may open a focused pull request directly or start with a [tool request](https://github.com/tmoreton/heytim-bots/issues/new?template=tool-request.yml) when the shape is still uncertain.

A remote integration stays hosted by its provider or contributor. Shared public services use HeyTim-owned credentials; private account data requires a reviewed OAuth connection with the least permissions needed. Public built-ins maintained by HeyTim are enabled only after their server-side binding is deployed and tested. Secrets and executable integration code never live in this repository or the app bundle.

## What stays in the app backend

This directory owns capability definitions: names, descriptions, skill instructions, tool actions, runtime bindings, and external OpenAPI schemas. The monorepo's services keep the machinery needed to use them safely:

- catalog signature, validation, caching, and version pinning;
- user-created private skills, OAuth account connections, legacy private-connection records, and sharing records;
- per-user OAuth credentials encrypted in AWS Secrets Manager and resolved only at invocation time;
- reviewed runtime implementations such as the calculator and browser session manager;
- the allowlist that prevents public catalog entries from activating arbitrary bundled code; and
- AWS credentials, permissions, and deployed gateway resources.

Those pieces cannot be downloaded as community content because they execute with trusted server permissions. The app contains no fallback copy of this public catalog. Existing legacy private connections remain viewable, removable, and usable by their current bots, but the app no longer accepts new or edited developer-key connections. Write-capable connections require approval for each direct-chat turn and cannot run in schedules or group rounds.

The X and YouTube targets are the one deployment exception to the main AgentCore project file. AgentCore project schema v1 cannot express an API key's header/query location or prefix, so `infrastructure/gateway-targets.yaml` owns those two targets declaratively next to their canonical schemas. Remove that template when the project schema supports these fields; do not copy the schemas back into the app repository.

Before deploying that template, retrieve each provider's managed secret ARN with
`aws bedrock-agentcore-control get-api-key-credential-provider --name <provider-name> --query 'apiKeySecretArn.secretArn' --output text`
and pass the exact values as `XCredentialSecretArn` and `YouTubeCredentialSecretArn`. The template scopes the gateway role to
those two provider and secret ARNs plus the deployed `FrogBot-FrogBotTools` workload identity; do not replace them with
account-wide wildcards.

Release these targets before publishing bots that depend on them: tag the reviewed catalog commit with its
immutable `skills-vN` release, upload only the X and YouTube schemas from that tag to the matching private S3
release paths, deploy the template with the existing gateway ID and role plus the two exact managed-secret
ARNs, and wait until both gateway targets report `READY`. Before launch, verify that the production Google Cloud
project's current YouTube Data API **Search Queries** daily quota can cover the expected traffic from workflows
that intentionally make several searches; the current `search.list` limit is documented on the
[official method reference](https://developers.google.com/youtube/v3/docs/search/list). Raise that quota or delay
publication if it cannot support the launch. Smoke-test the targets' read-only search operations, then
merge the catalog change that enables the dependent bots. Publishing the catalog first creates a visible bot
whose required tools cannot run.

## Publishing model

Every accepted catalog change does two things without a mobile release:

1. The Vite website build publishes the public directory and catalog artifacts.
2. HeyTim’s AWS backend refreshes the same reviewed catalog and makes available entries selectable or installable in the app.

Bots remain pinned to the skill version they selected. A user can create a private, editable skill copy without changing the public catalog. Sharing a bot or skill never shares connected accounts, legacy private connections, or credentials.

See [docs/CAPABILITY_AUDIT.md](docs/CAPABILITY_AUDIT.md) for the current keep, retire, and next-tool decisions.
