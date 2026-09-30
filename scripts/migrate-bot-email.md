# Inbound bot email during the AWS account cutover

**Status: NO-GO for live mail handoff.** This document and
`migrate_bot_email_objects.py` cover the unversioned SES raw-message bucket.
The [versioned S3 migration](migrate-versioned-s3.md) does not cover it.
The CDK now defines durable notification capture and a separate quarantine
bucket, but neither account's capture stack has been deployed. The guarded
replay path is not yet verified in either account.
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

The SQS notification is not the MIME body. By default the current SES S3
action still writes to the seven-day `IncomingBotMail` bucket. The CDK now
defines a private `BotEmailQuarantine` bucket with SSE-S3, blocked public
access, TLS enforcement, 14-day lifecycle, and retention on stack deletion.
The **addition-only** source and destination stacks each import the existing
SNS topic and SES delivery role, then add the capture queue/subscription,
failure queue, quarantine bucket, and a narrow `received/*` SES role grant.
They do not change the existing receipt rule or Lambda subscriber. No full
source Amplify deployment is part of this path. The existing source Lambda
must therefore be held separately before the SES action changes. A normal
Amplify deployment with `HEYTIM_BOT_EMAIL_CAPTURE_ONLY=true` and
`HEYTIM_BOT_EMAIL_AVAILABLE=false` creates a *different* capture queue and
bucket and omits its Lambda subscriber; it cannot be deployed concurrently
without reconciling both capture subscriptions and MIME stores.

For each addition-only deployment, first use STS to prove the exact account
and `us-east-1`, resolve the existing SNS topic and SES role from that
account's CloudFormation stack, and record their physical ARNs privately.
From `services/API`, set only the corresponding
`HEYTIM_SOURCE_MAIL_TOPIC_ARN`/`HEYTIM_SOURCE_SES_ROLE_ARN` or
`HEYTIM_DESTINATION_MAIL_TOPIC_ARN`/`HEYTIM_DESTINATION_SES_ROLE_ARN`. Run an
account-guarded CDK **diff** for `HeyTimSourceMailCapture` with
`node --import tsx amplify/source-mail-capture-app.ts`, or
`HeyTimDestinationMailCapture` with the destination app path. The acceptable
change is only two encrypted retained queues, one SNS subscription, one
private retained quarantine bucket/policy, and one inline grant on the
existing SES role. Reject any replacement/deletion or different-account
ARN; only then run the same CDK app as a separately reviewed deploy. Never
run both the standalone source stack and a full source Amplify deploy that
creates the same capture resources. Both standalone stacks use termination
protection. Their CloudFormation outputs and the active receipt-rule JSON
must be read back before any SES change.

**Source receiver hold:** after the source SQS subscription is deployed,
send a controlled mail through the still-normal source rule and prove its
SNS notification reached the queue and its MIME reached the old raw bucket.
Record the existing SNS-to-Lambda subscription ARN and attributes. Reserve
the existing receiver Lambda at concurrency **zero**, then set only that
Lambda subscription's `FilterPolicyScope=MessageAttributes` and
`FilterPolicy={"heytim_cutover_capture_hold":["source-188757775631-20260930"]}`.
Leave the SQS subscription unfiltered. [SNS filter changes can take up to
15 minutes](https://docs.aws.amazon.com/sns/latest/dg/sns-subscription-filter-policies.html)
to propagate; wait longer than 15 minutes and prove a second controlled
notification reaches SQS while the Lambda produces no inbox row or turn.
The zero-concurrency hold covers the propagation interval. Investigate and
account for any SNS delivery retries and Lambda DLQ records; never restore
concurrency while the source subscriber could replay stale work. Then change
only the source `HeyTimBotInbox` S3 action to the new quarantine bucket,
keeping its exact topic, role, prefix, recipient scope, and enabled state.
Prove a third controlled notification and MIME object in quarantine. The
source writer preflight and freeze capture now require that exact held
subscription, zero Lambda concurrency, enabled store-only SES rule, empty
capture DLQ, and writable protected quarantine. Pass the standalone stack
as `--mail-stack-name HeyTimSourceMailCapture`; omitting it fails closed.
This filter is a temporary CloudFormation drift on the existing subscription.
Keep its original attributes and exact ARN in the private rollback snapshot;
restore them only after the source is again the selected processing owner,
the destination owner is stopped, and queued/retried notifications are
reconciled. Wait for filter propagation on restoration as well.

The revised freeze plan requires this store-only rule, leaves SES enabled,
does not deny writes to the quarantine bucket, and pauses its lifecycle while
the normal raw bucket is frozen. It binds exact source account rule, topic,
subscription, queue, SES role, and bucket identities to a recent read-only
preflight. The source freeze executor still unconditionally rejects live
source AWS mutations; a separate safety review is required before executing
that plan. The source Lambda filter/concurrency hold is a separately
snapshotted operator control and is not automatically restored by that freeze
executor. The destination needs equivalent store-only mode during overlap.
SQS retention does not extend the old raw MIME bucket's seven-day expiry.

**Temporary retention exception:** the quarantine bucket's 14-day lifecycle
is longer than the normal seven-day raw MIME policy, and the freeze pauses
that lifecycle during the approved maintenance window. Record this exception,
its start and end times, and per-object original receipt times in a private
manifest. Keep the bucket private and its queue unconsumed until every
notification is classified. Before declaring cutover complete, verify each
selected MIME exists in the destination and that replay is durable; retain
only what is needed for the recorded rollback interval. Then delete
quarantine copies whose normal seven-day retention has elapsed, restore the
quarantine lifecycle, and verify no unclassified or held message is being
discarded. On rollback, preserve both quarantines until the source is the
sole processing owner and the same queue/object accounting passes. Never
allow the 14-day SQS expiry to act as a cleanup mechanism for unresolved mail.
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

### Destination capture owner handoff remains NO-GO

The destination standalone stack `HeyTimDestinationMailCapture` reached
`CREATE_COMPLETE` in account `820323452649` on September 30. A non-mail
SNS-to-SQS smoke message arrived in its capture queue and was removed after
verification. The destination receiver was then held at zero reserved
concurrency with the reviewed `MessageAttributes` filter, retaining its
CloudFormation-owned Lambda subscription. The inactive `HeyTimBotInbox` rule
was changed only to the standalone quarantine bucket, with its exact topic,
role, and recipient scope preserved. Private rollback inputs are
`/private/tmp/heytim-dest-mail-subscriber-before-hold-20260930.json`,
`/private/tmp/heytim-dest-mail-receiver-concurrency-before-hold-20260930.json`,
and `/private/tmp/heytim-dest-ses-bot-rule-rollback-20260930.json` (mode
`0600`). Destination SES remains inactive, and the old destination raw object
still needs private classification. Reactivate only after the 15-minute hold
proof, a full rule-set readback confirms there is no overlapping bounce, and
a controlled delivery is stored and queued. Keep source active until that
test passes. When source is disabled, disable only its bot rule; the source
active set also serves another recipient scope.

If this preparatory destination hold is abandoned while destination SES is
still inactive, use the private rollback rule to restore its original raw
bucket, verify the readback and inactive active-set state, then clear only the
recorded SNS filter and Lambda concurrency hold. Wait through SNS filter
propagation before any later destination activation. Keep the standalone
capture subscription and retained queue/bucket until a separate reviewed
cleanup proves they contain no unresolved mail.

The standalone destination stack is a temporary capture owner. Its queues
and bucket have `RETAIN`, but **deleting the stack removes the SNS
subscription**. Deleting it before another verified capture subscription
exists creates a notification gap even though retained objects remain.
The September 30 full-backend preview was `+9/~16/-0` with no replacements,
but remains **NO-GO**: it would create seven duplicate mail capture resources
and two unrelated AI sharing routes, update seven Lambda packages, change
file retention and IAM statements, and retarget the SES rule to a different
bucket. Keep the standalone stack and its bucket as the capture owner until
a separate review reconciles those resources; an ordinary Amplify deployment
could silently split mail capture between two owners.
Likewise, the production release workflow hardcodes normal mail processing
and requires release attestations and configuration that may still be bound
to the source account. It now fails closed while
`HeyTimDestinationMailCapture` exists; do not use it to switch capture owners.

The next destination Amplify deployment keeps the standalone stack as the
single capture owner. With `HEYTIM_BOT_EMAIL_STANDALONE_CAPTURE_BUCKET` set to
that stack's exact `BotEmailQuarantineBucketName` output, the backend imports
its bucket and does not synthesize a second capture queue, SNS subscription,
or quarantine bucket. The private preview resolves that output from
CloudFormation and rejects a mismatched supplied value. It requires
`CAPTURE_ONLY=true`, `AVAILABLE=false`, and
`HEYTIM_BOT_EMAIL_KEEP_HELD_SUBSCRIBER=true`: synthesis retains the existing
CloudFormation SNS-to-Lambda subscription with its exact
`heytim_cutover_capture_hold` filter, holds receiver concurrency at zero,
keeps `MAIL_PROCESSING_ENABLED=false`, and points the SES rule to the
standalone bucket. Do not delete the standalone stack or enable normal mail
processing as part of this deployment. A **read-only** private preview exists at
`scripts/preview_destination_mail_capture.sh`. It requires a named AWS
profile that STS resolves to destination account `820323452649`, verifies
Amplify app `d17sj7dvhx07c` and its `main` branch/root stack, requires
`HEYTIM_BOT_EMAIL_CAPTURE_ONLY=true` and
`HEYTIM_BOT_EMAIL_KEEP_HELD_SUBSCRIBER=true` with
`HEYTIM_BOT_EMAIL_AVAILABLE=false`, billing disabled with
`HEYTIM_FREE_ONLY_MODE=true`, and rejects account-mismatched ARNs. Set
`HEYTIM_LEGACY_TOKEN_VAULT_KMS_KEY_ARN` to the existing destination key
`arn:aws:kms:us-east-1:820323452649:key/4893a4c0-00e8-4381-823b-19c8bc8ed248`.
That key is enabled and carries the destination AgentCore Identity token-vault
grant in the deployed role. Its legacy FrogBot description is physical
metadata; no source-account key should be supplied.
Supply destination production configuration through the process environment;
do not copy source account secret values or GitHub release variables. From the
repository root, run `uv run --with boto3 bash
scripts/preview_destination_mail_capture.sh <destination-profile>` (or use a
Python environment with boto3 already installed). Before synthesis, a
read-only preflight checks the
CloudFormation-bound SNS topic/subscription and Lambda, the exact live filter,
zero reserved concurrency, inactive destination SES rule set, and CloudTrail
evidence that both holds have been stable for at least 15 minutes. Once the
destination rule set is active, the preflight instead requires its exact
store-only rule to point at the standalone quarantine bucket and topic.
Missing or recent hold events fail closed. It then bundles the full backend
locally, runs **only**
`cdk synth` and `cdk diff --method template`, and stores the assembly, diff,
and template hashes in a private `/private/tmp` directory. The template
method reads the live stack without creating a CloudFormation change set.
The preview returns `NO_GO` for duplicate capture resources, resource removal,
replacement, unrelated resource changes, unreviewed IAM statement changes,
or an unreadable diff; it
has **no deploy mode**. A
reviewed, destination-bound private deployment path is still missing.

A read-only September 30 preview using destination Lambda ARN/ID metadata and
the destination AgentCore memory key returned `NO_GO`: nine resource
additions, sixteen modifications, two removals (the current mail Lambda SNS
subscription and invoke permission), IAM changes, and zero replacements.
The held-subscriber mode retains the existing subscription and invoke
permission. A second read-only representative diff with destination ARN/ID
metadata showed nine additions, sixteen in-place changes, **zero removals and
zero replacements**. That preview predates the standalone-owner import and
Free-only mode. The destination hold was subsequently applied and verified;
rerun the private preview against the new synthesis. The unrelated UserFiles lifecycle,
deploy-role IAM, Lambda code, and API route changes remain `NO_GO` until
reviewed before any full backend deployment.
The preview's private diff is not an approval to deploy. The standalone
capture stack remains the capture owner through this deployment. On
rollback, preserve both destination and source quarantines and capture
subscriptions until one processing owner and every held notification are
accounted for.

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

This is **implemented capture infrastructure and a fail-closed freeze plan,
not a deployed or replayed mail handoff**. Deploy and smoke-test both account
queues and store-only rules, classify the destination's existing unique raw
object, then implement the reviewed idempotent replay path. The source
currently remains the sole active matching receiver; destination's active
rule set remains deactivated. Live source freeze writes remain disabled.
