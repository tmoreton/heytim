# Account-owned bot workflows

FroggyBot can provision a repeatable specialist workflow without adding another
AgentCore runtime or hard-coding a user's private connection IDs. A workflow pack
combines private skills, account-owned bots, provider requirements, an optional
training turn, and optional direct schedules. The installer resolves the exact
confirmed Cognito account and invokes the same authenticated application handlers
used by the Apple and browser clients.

The first example is [`examples/jopbot-workflow.json`](../examples/jopbot-workflow.json).
It installs JOPbot, resolves that user's connected Gmail account by provider, learns
an abstract Journey on Points voice profile from relevant newsletters and public
pages, stores the profile in the account's private versioned skill, and prepares a
disabled weekly newsletter-draft task. Doctor of Credit and Frequent Miler are
research leads; the workflow requires original copy, dated links, primary-source
verification when available, and explicit offer caveats.

## Safety boundaries

- Exact account lookup must return one enabled, confirmed Cognito user.
- OAuth grants remain in Secrets Manager and are never copied into packs, prompts,
  output, or source control.
- Connections are resolved by provider for each account. A pack never contains a
  user's connection ID.
- Training can approve the requested turn once. The utility cannot grant permanent
  tool approval.
- Gmail can search/read and create drafts. It cannot send, delete, archive, or
  relabel messages.
- Learned mailbox-derived style is stored only in the private account skill. The
  checked-in pack contains the reusable method, not private newsletter content.
- Schedules in the example start disabled. Enabling an unattended Gmail draft task
  requires the account owner to review the bot and explicitly allow Gmail for future
  turns in the app.

## Install or inspect a workflow

The default command produces a read-only plan:

```bash
python scripts/configure-bot-workflow.py \
  --email YOUR_EXACT_ACCOUNT_EMAIL \
  --user-pool-id YOUR_USER_POOL_ID \
  --function-name YOUR_API_LAMBDA_NAME \
  --pack examples/jopbot-workflow.json
```

Apply the private skill and bot, run the one-time voice training turn, and add the
disabled schedule:

```bash
python scripts/configure-bot-workflow.py \
  --email YOUR_EXACT_ACCOUNT_EMAIL \
  --user-pool-id YOUR_USER_POOL_ID \
  --function-name YOUR_API_LAMBDA_NAME \
  --pack examples/jopbot-workflow.json \
  --apply --train-now --approve-once --include-schedules
```

Reruns upsert by exact case-insensitive names and preserve unrelated bots, skills,
connections, approvals, groups, chats, and schedules. Existing schedule enabled
state is also preserved unless `--sync-schedule-state` is explicitly supplied.
Training is skipped after the completion marker is present; use `--force-train`
only when intentionally rebuilding the private profile.

## Adapt the pattern

Copy the example pack and replace its brand, source, and editorial instructions.
Keep account-specific secrets and connection identifiers out of the file. A bot can
request any reviewed provider using `connectionProviders` (for example, `gmail` or
`google_workspace`), while ordinary tool IDs remain in `toolIds`. Use `skillKeys`
to attach skills declared in the same pack. Keep schedules disabled until a manual
trial is complete and any interactive tools have been explicitly approved by the
account owner.
