# Reviewed bot-mail replay during the AWS move

This utility covers SES notifications captured by the two unconsumed
`BotEmailInboundCapture` SQS queues while the source and destination receivers
are in store-only mode. It is **not a cutover switch**. The source account is
`188757775631`, the destination is `820323452649`, and both must be in
`us-east-1`. It does not alter receipt rules or the source mail quarantine
policy. The source currently remains live.

## Preconditions

1. Deploy the capture queue and separate `BotEmailQuarantine` bucket in both
   exact accounts. Confirm both S3/SNS/SQS deliveries with controlled mail.
   The snapshot tool checks each queue's 14-day encrypted retention, exact
   account/topic SNS grant, wrapped subscription, redrive target, and empty
   subscription failure queue. Complete the reviewed source writer freeze
   and data migration separately.
2. Stop application mail processing in both accounts during the overlap.
   Keep store-only receipt rules accepting and queueing mail. Do not run
   `dispatch` while any source or destination mail receiver can process the
   same notification.
3. Import destination bot routes, `MAIL_ALIAS` rows, retained inbox rows, and
   raw MIME. Run the separate `migrate_bot_email_objects.py --verify` gate.
4. Resolve every unclassified `received/` object, including any destination
   raw MIME without a retained inbox row or captured notification. This tool
   lists only its metadata in an owner-only snapshot and refuses to plan while
   an unclassified object remains. Never discard one just to clear the gate.
5. Preserve the capture queues and their delivery DLQs until the final
   reconciliation and zero-backlog checks. A snapshot samples visible SQS
   messages; it cannot prove that an active queue has stopped receiving mail.

## Capture and review

Use absolute paths outside Git. `snapshot` creates an owner-only `0600` JSON
file containing the **exact SNS wrapper and SES notification** for each
captured SQS message, plus MIME keys, sizes, and hashes. It never writes MIME
body bytes to disk. The SNS metadata contains private addresses; do not post
the JSON or tool output to a ticket or commit it. The command receives SQS
messages briefly and restores their visibility without deleting them.

```bash
python scripts/reconcile_bot_email.py snapshot \
  --source-profile '<source-profile>' \
  --destination-profile '<destination-profile>' \
  --source-app-stack '<source-Amplify-root-stack>' \
  --source-capture-stack 'HeyTimSourceMailCapture' \
  --destination-app-stack '<destination-Amplify-root-stack>' \
  --destination-capture-stack '<destination-Amplify-root-stack>' \
  --output /private/tmp/heytim-mail-capture-final.json
```

For every `observations[].id`, create a separate `0600` decisions file. Each
recipient observation needs `reviewed: true`, a substantive `note`, and an
`action` of `replay`, `imported`, `reject`, or `hold`. A replay needs a new normalized canonical UUID,
one `primary: true` among its group, and `delivery: review` or `automatic`.
Use the **same UUID only after reviewing that multiple SNS/SQS observations
represent one delivery**. Distinct SES IDs across accounts are expected.
Two legitimate emails can share the same MIME hash; that hash alone never
justifies merging them. Cross-account groups additionally require matching
recipient, MIME bytes, RFC Message-ID, envelope sender, and receipt times
within ten minutes. Ambiguous groups stay held, and a held recipient keeps
its SQS notification in the capture queue. A source notification already
processed before the freeze uses `action: imported`, with the reviewed
destination `userId`, `botId`, `inboxKey`, `delivery`, and canonical UUID. It
verifies the migrated row instead of creating another inbox. If it was
automatic, the transaction adds a durable outbox for its existing stable
`linkedTurnId`; a completed migrated turn is observed without another run.
Multiple SQS deliveries of that same source SES receipt may share one
reviewed imported canonical UUID. A failed SES spam or virus verdict, or a
recipient with no route in either account, can use `action: reject` with
`reason: ses_spam`, `ses_virus`, or `no_route`. The rejection gets a durable
marker and preserved destination MIME before its notification can be acked.
No other reason can silently drop mail.

Example structure, with IDs from the private snapshot:

```json
{
  "schemaVersion": 1,
  "snapshotDigest": "<digest from snapshot>",
  "observations": {
    "<observation id>": {
      "reviewed": true,
      "note": "Matched the source and destination observations after reviewing both envelopes.",
      "action": "replay",
      "canonicalId": "<new normalized UUID>",
      "primary": true,
      "delivery": "review"
    }
  }
}
```

The read-only planner validates all observations and produces a separate
owner-only plan. The digest printed by this command is required for every
write step. Never reuse an old digest after taking a new snapshot.

```bash
python scripts/reconcile_bot_email.py plan \
  --snapshot /private/tmp/heytim-mail-capture-final.json \
  --decisions /private/tmp/heytim-mail-decisions.json \
  --output /private/tmp/heytim-mail-reviewed-plan.json
```

## Apply, dispatch, and acknowledge separately

`apply` rechecks both STS accounts, CloudFormation physical resources, each
same-account MIME object, and the destination route. It copies missing MIME
only into the destination raw bucket, never overwrites divergent bytes, then
uses one DynamoDB transaction to conditionally create a `MAIL_REPLAY` marker,
`BOT_EMAIL` inbox row, and an outbox item for an automatic turn. An imported
delivery transaction checks the existing inbox and writes its marker and
optional outbox. A retry after
an uncertain transaction result reads all three and verifies their immutable
identity. Existing imported inbox rows with no matching marker cause a stop.

`dispatch` runs only after every observation is reviewed with no holds and the
destination is the sole processing owner. It sends each durable automatic
outbox request to the destination jobs queue. A crash before or after SQS send
leaves the outbox pending; rerunning sends the same stable turn ID. If the
email worker created the turn but failed before queueing `AGENT_REPLY`, the
dispatcher retries that existing turn. It observes a completed, failed, or
paused turn before closing the outbox. Monitor pending outboxes until none
remain. The existing jobs queue is at-least-once; turn creation is guarded by
its stable key and the worker's claim lease.

`ack` handles **one** captured SQS notification after every recipient it
contains has a matching replay marker, inbox row, destination MIME, and
outbox if automatic. It writes an acknowledgement intent in destination
DynamoDB before deleting the SQS message, then marks that intent deleted.
If a process crashes between deletion and the final update, the intent stays
visible for manual reconciliation. It never guesses that a missing queue
message was safely deleted.

Each mutating step requires `HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED=true`
plus its own step flag. The user-approved outage authorizes the migration;
these flags bind a reviewed operator run to its exact private plan digest.

```bash
HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED=true \
HEYTIM_MAIL_REPLAY_APPLY_APPROVED=true \
python scripts/reconcile_bot_email.py apply \
  --snapshot /private/tmp/heytim-mail-capture-final.json \
  --decisions /private/tmp/heytim-mail-decisions.json \
  --source-profile '<source-profile>' \
  --destination-profile '<destination-profile>' \
  --expected-plan-digest '<digest from plan>'
```

Replace `apply` and its step flag with `dispatch` /
`HEYTIM_MAIL_REPLAY_DISPATCH_APPROVED=true` only after the receiving-owner
switch. Replace them with `ack` /
`HEYTIM_MAIL_REPLAY_ACK_APPROVED=true`, and add `--account` and
`--sqs-message-id` from the snapshot, to acknowledge one notification.
Repeat for each reviewed notification. Keep source and destination capture
queues until a new snapshot has no unseen messages, both queue/DLQ counts
remain zero through the final watermark, all outboxes are observed, and the
separate app/data/memory/provider cutover gates pass.

Run the read-only `status` subcommand with the same snapshot, decisions,
profiles, and plan digest after any interruption. It reports missing or
divergent replay records, pending outboxes, unacknowledged snapshot messages,
and point-in-time queue counts. It is never proof by itself that no later
mail was delivered.
