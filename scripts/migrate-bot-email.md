# Inbound bot email during the AWS account cutover

**Status: NO-GO for live mail handoff.** This document and
`migrate_bot_email_objects.py` cover the unversioned SES raw-message bucket.
The [versioned S3 migration](migrate-versioned-s3.md) does not cover it.
The CDK now defines a durable notification capture queue, but it is not
deployed and does not by itself provide a store-only S3 destination or replay.
Do not run `--apply` or change an SES receipt rule until the source write
freeze, account/data migration, store-only capture, and replay are ready.

## Read-only checkpoint, September 30, 2026 UTC

The accounts were checked with STS and the bucket physical IDs with the
respective Amplify CloudFormation stacks. Source account `188757775631` had
five retained `BOT_EMAIL` inbox rows and five `received/` MIME objects; all
five row references existed. Destination account `820323452649` had a deployed
SES raw-mail bucket, one `received/` MIME object, and zero `BOT_EMAIL` rows.
The destination object's SHA-256 matched none of the five source objects. It
is **unclassified**, and neither its key nor content was logged. It must be
preserved and reconciled, or allowed to expire under the documented seven-day
retention with evidence that no inbox row or pending notification refers to it.
The source is still live; these counts are not a frozen snapshot.

At the next read-only SES check, both accounts had enabled `HeyTimBotInbox`
rules scoped to `bots.heytim.ai`, each with an S3 action. The source active
set also contains a separate `inboxai-inbound` rule for another recipient
scope. The operator then saved exact-account active-set snapshots and
deactivated **only the destination** active rule set. The destination now has
no active receipt rule set; source `inboxai-inboxai-cc` remains active and
unchanged. The destination `heytim-production-bot-mail` set is retained for
controlled reactivation. Do not treat its one unclassified raw object as
proof of completed delivery or replay.

The bucket stores raw MIME for seven days while inbox previews remain until
user/bot/account deletion. An older inbox row with a missing raw object is
expected under that policy; a row less than seven days old with missing raw
mail is a blocker. Copying an object resets its destination lifecycle clock
and can extend raw-mail retention. Before applying, record the original
object timestamps and a destination-only expiry cleanup schedule for each
copied object, or explicitly review a different retention treatment. The
current utility does not delete source or destination objects.

## Tool scope and ordering

The utility discovers exactly one `IncomingBotMail` S3 bucket and one `Data`
table in each named live CloudFormation stack, then checks the supplied bucket
names, exact STS accounts, region, unversioned bucket state, SSE-S3 encryption,
public-access blocking, seven-day destination lifecycle, and every retained
inbox row. It reads raw MIME only to calculate SHA-256 in memory. A private
mode-0600 manifest stores object keys, sizes, and hashes but never MIME bodies
or addresses. Terminal output contains only counts, blockers, and a plan
digest. `--apply` writes only missing destination objects, with an explicit
SSE-S3 setting and checksum, then reads them back. Any unexpected or divergent
destination object stops the copy without deletion or overwrite.

1. Deploy and test the durable reception path below in each exact account.
   Complete a revised source freeze that disables its raw-bucket lifecycle
   and leaves a separate store-only inbound quarantine path accepting mail.
   Keep both app mail receivers from processing during the overlap.
2. Run the read-only inventory. Resolve every blocker and repeat it after the
   frozen DynamoDB source snapshot. The expected plan digest must come from
   that final private manifest, not this document's live checkpoint.
3. Import the application table with `migrate_dynamodb_state.py` and confirm
   its two active bot address aliases, retained inbox rows, and current
   account consent fields. Check that all five raw references still exist.
4. Run the destination-only MIME copy with the reviewed digest and the
   cutover flag. It refuses to run while the source bucket lifecycle is
   enabled. Re-run it safely after interruption only if the destination
   objects still match; it never overwrites them.
5. Run `--verify` before enabling destination mail processing. It requires
   complete source/destination `BOT_EMAIL` row parity after identity remap and
   byte-for-byte parity for all source `received/` objects. Older absent raw
   objects must remain absent on both sides.
6. Reconcile the durable overlap queues and the destination-only object,
   then enable destination processing. Do not infer this from DNS propagation.

Example read-only inventory, with physical names checked against the current
CloudFormation stack before use:

```bash
services/runtime/.venv/bin/python scripts/migrate_bot_email_objects.py \
  --source-profile '<source-profile>' \
  --destination-profile '<destination-profile>' \
  --source-stack '<source-amplify-root-stack>' \
  --destination-stack '<destination-amplify-root-stack>' \
  --source-bucket '<source-IncomingBotMail-physical-name>' \
  --destination-bucket '<destination-IncomingBotMail-physical-name>' \
  --manifest /private/tmp/heytim-bot-email-final-plan.json
```

The process exits `2` for a readable dry run with blockers. Keep the private
manifest out of Git and verify its owner-only permissions. During a reviewed
maintenance window, the same command with `--apply`,
`--expected-plan-digest '<digest-from-final-dry-run>'`, and
`HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED=true` performs the bounded
destination-only copy. After the table import, replace `--apply` and its
digest argument with `--verify` to require final parity. Neither command is
proof of a full application cutover on its own.

## Preserve the two existing bot addresses

`bots.heytim.ai` addresses encode the **source Cognito UUID**. A plain
Cognito subject remap produces different addresses even if the route token is
retained. The migration plan now keeps each active bot's `emailToken` and
preferences, writes its exact prior address into `legacyEmailAddress`, and
adds one `MAIL_ALIAS` row keyed by SHA-256 of that address. The destination
receiver looks up that exact alias and reads the destination bot with a
consistent read. It accepts the address only while the bot's current token,
bot digest, and saved legacy address still match. The app and outbound mail
use the saved address until the owner rotates or disables the inbox. Rotation
or disabling removes the saved address; even if alias cleanup fails, the
token check prevents the old address from routing. Bot and account deletion
also remove alias rows. This copies bot route tokens, **not** Plaid access or
refresh tokens. Consent `STATE` fields remain in the normal identity remap.

Do not enable destination reception until the table migration confirms two
active alias rows and the two exact owner/bot mappings. Verify a live test to
each old address, a rotated address rejection, and outbound Reply-To continuity.

## Durable mail while app writes are frozen

**A disabled source receipt rule is not a retry plan.** SES's documented S3
action stores the message and can publish an SNS notification with the SMTP
envelope recipient and SES receipt verdicts. The CDK now attaches an
unconsumed `BotEmailInboundCapture` SQS queue to the existing
`IncomingBotMailTopic`, with a separate SNS delivery DLQ. Both queues use
SSE-SQS, TLS-only transport, 14-day retention, and `RETAIN` on stack deletion.
Their policies allow `sns.amazonaws.com` only for the exact topic ARN and
account. CloudFormation outputs identify the queue and DLQ in each account.
The source writer preflight recognizes them and permits a nonempty capture
queue; a nonempty subscription DLQ blocks the preflight. Deploy only after
reviewing the source and destination stack diffs for replacement of existing
mail resources, and prove the topic publishes to SQS with a controlled test.

The SQS notification is not the MIME body. The current SES S3 action still
writes to the seven-day `IncomingBotMail` bucket. A safe source freeze needs a
**separate private source quarantine bucket** for SES writes while the old
raw bucket is frozen, and a reviewed receipt-rule S3-action switch to it.
That quarantine bucket needs encryption, blocked public access, TLS-only
access, retained objects during the maintenance window, exact-account SES
put permission, and a later cleanup policy. The destination needs an
equivalent store-only setting during overlap. The app receivers must remain
off; an SNS-to-Lambda retry window alone cannot retain the backlog. SQS
retention does not extend the existing raw MIME bucket's seven-day expiry.
Record the exact receipt-rule JSON, bucket policies, topic subscriptions,
queue redrive/retention, encryption, lifecycle, and restore inputs before any
rule change. Test a normal mail, a large mail, a disabled route, and an SNS
delivery failure while both copies are held without processing. Guard every
read and write by STS account (`188757775631` source, `820323452649`
destination), region `us-east-1`, CloudFormation-discovered bucket/table,
and expected queue/topic ARNs.

[AWS says](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-receipt-rules-console-walkthrough.html)
that when multiple SES accounts receive a common domain, **all matching
receipt rules run simultaneously**. Both accounts use the same regional SES
MX endpoint, so changing NS or MX within `us-east-1` does not choose an AWS
account. Do not allow a Bounce action in one account to conflict with
acceptance in the other. The safe overlap sequence is:

1. With destination app processing disabled, keep source accepting to its
   durable quarantine S3+SNS-to-SQS path. Reactivate the retained destination store-only
   S3+SNS-to-SQS rule. Confirm both rule sets are active, non-bouncing, and
   writing/queuing the same controlled test. Source normal customer-state
   writers and its old raw bucket remain frozen.
2. During overlap, **neither** account runs automatic bot turns or outbound
   mail. Capture notifications and raw mail in both. Read and reconcile the
   union of messages by envelope recipient, SES IDs, Message-ID, and raw MIME
   SHA-256. SES IDs are not assumed equal across accounts. Ambiguous matches
   stay in review rather than triggering duplicate bot actions.
3. Once destination store-only capture is proven and all source quarantine
   notifications are accounted for, disable the source matching rule and
   verify its state. Keep destination store-only until source queue/bucket
   counts and the reconciliation watermark stop changing. Replay each unique
   accepted message into destination once, at review disposition, with a
   durable idempotency marker and the original verdict/envelope metadata.
4. Enable normal destination receiver processing only after queue drain and
   per-message checks. Rollback uses the reverse controlled overlap, again
   with one processing owner and durable queues. Never disable both matching
   rules without a proven external SMTP queue and retry contract.

The current saved destination active-set snapshot is
`/private/tmp/heytim-dest-ses-active-before-20260930.json`; the source one is
`/private/tmp/heytim-source-ses-active-before-20260930.json`. These are
operator-local rollback evidence, not repository artifacts. Before
reactivation, read back both active sets and verify the source is still
accepting, the destination receiver is still disabled, and the retained
destination set contains only the reviewed bot-mail rule. On rollback,
deactivate destination again and read back `none`; restore source from its
snapshot only if an authorized change to that account was made.

### Replay contract before any queue is drained

Capture the SNS envelope and SES notification exactly, then parse the receipt
recipient, SES message ID, timestamp, and verdicts. Resolve the corresponding
S3 object in the **same account**, verify its SHA-256, and copy missing MIME
to the destination with account and bucket guards. Do not rely on SES message
IDs or raw MIME hashes alone to deduplicate across accounts: two accounts can
assign different IDs to one delivery, and two legitimate deliveries can have
identical MIME. A private reviewed reconciliation manifest must map every
source and destination notification to one canonical delivery or an explicit
hold. Use recipient, headers, timestamps, and hashes as evidence; ambiguous
matches stay held without bot processing.

For each selected canonical delivery, write a destination `MAIL_REPLAY` marker
and the `BOT_EMAIL` row conditionally in one DynamoDB transaction. Include a
durable outbox item for an automatic bot turn in that transaction; a separate
dispatcher sends it and marks it complete so a crash cannot silently lose or
duplicate a turn. Replay retries must verify the same canonical ID, recipient,
MIME hash, and bot route before treating a prior marker as success. Only
acknowledge/delete an SQS notification after the destination MIME and this
transaction are verified. Keep both capture queues and their DLQs until every
notification has a disposition and a final zero-backlog check.

This is an **implemented queue definition, not a deployed quarantine/replay
path**. The existing source freeze draft disables the source SES rule and
denies writes to its current raw bucket; it must be revised before execution.
The separate store-only bucket/rule setting and the idempotent replay worker
remain blockers for live cutover. The source currently remains the sole active
matching receiver; destination's active rule set remains deactivated.
