# Contributing

Frog Bots accepts small, reviewable additions that help a person or group reach a concrete outcome.

## Choose the right contribution

- **Skill:** readable instructions that shape how a FroggyBot approaches work.
- **Bot:** a small configuration that combines a prompt with existing skills and required tools.
- **Tool or connector:** a public definition for reading from or acting in another service.
- **Website or documentation:** a focused improvement to `site/`, `README.md`, or `docs/`.

Do not put executable integrations inside a skill. Remote integrations stay hosted outside this repository. FroggyBot supplies any credentials required by shared public services, while private account data uses a reviewed provider OAuth flow.

Private instruction-only skills and custom bot configurations do not need review and can be created directly in the FroggyBot app. Tools and account connections require review before they are offered to users.

## Add a bot

Add the bot directly to the `bots` array in `catalog.json`. Keep the configuration declarative and small: identity, prompt, skills, and required tools. Models, reasoning modes, credentials, schedules, memory, and approval choices belong to the app or the person installing the bot.

```json
{
  "id": "example-bot",
  "version": 1,
  "name": "Example Bot",
  "tagline": "Turns a specific input into a useful outcome.",
  "prompt": "Ask for the inputs that matter, do the work, and state uncertainty clearly.",
  "color": "#58BEAA",
  "category": "Planning",
  "author": "Your GitHub name",
  "tags": ["example", "planning"],
  "skillIds": ["example-skill"],
  "toolIds": ["web_search"]
}
```

`toolIds` means required tools; omit it when the selected skills already provide everything. There is no optional-tool list. A bot may reference only tool and skill IDs already present in `catalog.json`.

Add at least three realistic scenarios to `bots/<bot-id>/evals.json`. Each scenario needs a user prompt and at least two observable expectations. Increment the bot version whenever its prompt, skills, or tools change behavior.

### API tokens and MCP credentials

Never put an API token, secret, authorization header value, or credential-bearing URL in a bot, skill, evaluation, or pull request. A bot references a tool by ID only.

When a required integration needs authentication, the tool proposal must explain whether it uses a FroggyBot-owned service credential or per-user OAuth, which request field carries authorization, and the minimum permissions it needs. Installing a bot must never ask a user to paste a developer API key. FroggyBot-owned values stay in operator secret storage, while per-user OAuth credentials are stored by the app's reviewed connection flow. Shared bot configurations never include either kind of credential.

## Add a skill

1. Search `catalog.json` and open pull requests for overlap.
2. Copy the closest existing skill folder and rename it with a lowercase, hyphenated ID.
3. Keep the package instruction-only: one `SKILL.md`, one `evals.json`, and optional `.md`, `.txt`, or `.json` references.
4. Write a description that states the outcome and when the skill applies.
5. Include only guidance that changes the quality, safety, or consistency of the result.
6. Add the catalog entry and run the checks.

A minimal `SKILL.md`:

```markdown
---
name: example-skill
description: Turn a specific input into a useful, clearly bounded outcome.
---

# Example Skill

Use this skill when ...

1. Confirm the inputs that materially affect the result.
2. Produce the outcome in the shortest useful form.
3. State any uncertainty or action that needs approval.

Do not ...
```

Add `evals.json` beside it so reviewers can check both activation and results:

```json
{
  "shouldTrigger": ["A realistic request that needs this workflow."],
  "shouldNotTrigger": ["A similar request that needs a different workflow."],
  "expectations": ["A concrete property the finished result must have."]
}
```

Use at least three realistic examples in each trigger list and at least three observable outcome expectations. Near-misses are more useful than unrelated negative examples.

Its matching `catalog.json` entry:

```json
{
  "id": "example-skill",
  "version": 1,
  "name": "Example Skill",
  "description": "Turn a specific input into a useful, clearly bounded outcome.",
  "category": "Planning",
  "author": "Your GitHub name",
  "tags": ["example", "outcome"],
  "path": "skills/example-skill/SKILL.md",
  "requiredToolIds": []
}
```

Use at most six meaningful tags. Add `featured: true` only when maintainers have chosen the skill as a primary starting point. A skill may name only tool IDs already present in `catalog.json`.

## Change an existing skill

Preserve its ID. If instructions change behavior, increment its integer `version` and update the catalog release. Existing tagged versions remain available to bots that already selected them.

## Propose a tool

Open a focused pull request, or use the tool request first when you want design feedback. Include:

- the user outcome and exact actions;
- what information is read, stored, created, or changed;
- the authentication method and where credentials will live;
- whether actions are read-only, sandboxed, or interactive;
- rate limits, cost, and failure behavior; and
- the smallest permissions that support the outcome.

Community pull requests never add secrets or hosted executable code. Public built-ins maintained by FroggyBot use reviewed OpenAPI schemas under `tools/<provider>/openapi.yaml`. A remote integration needs a reviewed runtime binding; when it requires authentication, it uses either a FroggyBot-owned service credential or provider OAuth for private account access.

## Run the checks

```bash
python3 scripts/validate_catalog.py
python3 scripts/build_site.py
python3 -m unittest discover -s tests
```

Open `dist/index.html` through a local HTTP server when changing the site:

```bash
python3 -m http.server 8000 --directory dist
```

Then check the homepage, bot-directory search and filters, mobile layout, contribution links, legal pages, and invite forwarding.

## Review checklist

Reviewers check that a public contribution is useful, distinct, concise, safe, least-privilege, and understandable without private context. They also review its trigger examples for overlap with nearby skills and its expectations for outcomes a user can verify. Review determines public discoverability; users can still create private instruction-only skills and custom bot configurations in the app.
