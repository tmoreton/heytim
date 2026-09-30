# Provider delivery reconciliation for the account cutover

**Status: NO-GO for webhook movement.** This is the replay and evidence companion
to [the provider webhook switch plan](provider-webhook-cutover-2026-09-29.md)
and [the source write-freeze runbook](source-write-freeze-runbook.md). It does
not authorize changing a provider URL or accepting customer traffic.

The window needs an immutable inventory of every provider delivery, every
attempt, its owner account, and the application effect. A successful HTTP
response only proves that an endpoint acknowledged a request. It does not
prove that a Stripe entitlement was updated, a GitHub routine ran, or a Plaid
sync job was queued. Keep [SES inbound mail](source-write-freeze-runbook.md)
in its own durable quarantine and replay ledger; this provider ledger does
not cover mail.

## Current read-only inventory

At **2026-09-30 02:18 UTC**, `provider_delivery_inventory.py` confirmed the
AWS account through STS before reading a projection of only `entity`,
`provider`, and `eventType` from each application table. It did not read
customer content, webhook bodies, secret values, or queue messages.

| Metadata | Source `188757775631` | Destination `820323452649` |
| --- | ---: | ---: |
| Application table item count reported by DynamoDB | 662 | 0 |
| Stripe event markers | 2 | 0 |
| Stripe billing rows | 1 | 0 |
| GitHub routine subscription indexes | 0 | 0 |
| GitHub event group messages | 0 | 0 |
| Plaid connections | 1 | 0 |
| Plaid Item mappings | 0 | 0 |
| Plaid sync rows | 0 | 0 |

The table item count is DynamoDB's approximate metadata; the projected scan
is live and is not a point-in-time snapshot. These counts are planning
evidence only. The source Plaid connection must be classified as active,
disconnected, or stale from protected state before traffic moves. Its missing
Item mapping means the current handler returns HTTP 200 without queuing a
sync for a transaction webhook. The one Stripe billing row and two event
markers must be matched to a destination owner and imported state in the
protected migration evidence. The zero GitHub indexes are a current-state
observation, not proof that the App receives no webhooks.

## Private ledger and read-only inventory

Use [provider_delivery_ledger.py](../scripts/provider_delivery_ledger.py)
for a mode-`0600` append-only, hash-chained JSONL ledger in a protected
operator directory outside the repository. Use
[provider_delivery_inventory.py](../scripts/provider_delivery_inventory.py)
to read only projected DynamoDB metadata and optional SQS queue counts. The
inventory first checks the exact AWS account and table ARN. SQS counts are
approximate and cannot identify individual jobs. Both tools reject raw
webhook bodies and arbitrary fields.

1. Before the outage starts, choose a protected directory and create the
   ledger with the actual UTC start. For example:

   ```bash
   umask 077
   python scripts/provider_delivery_ledger.py /private/tmp/heytim-provider-window.jsonl init --started-at 2026-09-30T03:00:00Z
   ```

2. Append metadata records from separate mode-`0600` JSON files with
   `record --json <private-file>`. Record `source-stopped`,
   `destination-started`, and `ended` boundaries only after each has been
   independently observed. Boundaries are immutable; an incorrect boundary
   requires a fresh ledger and review. Record complete or partial coverage
   for each provider and each of `provider`, `source-ingress`, and
   `destination-ingress` over the exact window. Coverage gaps remain blockers.

3. For each Stripe event use the immutable `evt_...` ID. For each GitHub
   delivery use its `guid` / `X-GitHub-Delivery`; keep its numeric App delivery
   ID as the attempt ID for the redelivery API. Plaid's Transactions webhook
   does not provide a stable provider delivery ID to this handler, so use
   `sha256:<hex>` of the exact verified raw body as a local identity, mark
   `identityKind=body-digest`, and retain the protected ingress evidence.
   Never copy the body into the ledger. If no body digest was captured, record
   provider coverage as unknown and do not invent an ID.

4. Each delivery record requires `expectedOwner` and `effectExpected`. Use
   `unknown` when the source/destination user mapping is unproved. For a
   non-actionable event, use `effectExpected=false` only after a protected
   review proves that the deployed handler intentionally ignores that event;
   then record `non-actionable-reviewed` evidence. Missing Plaid Item mapping
   alone is **not** such proof.

5. Record every HTTP attempt under the account that actually received it.
   Record downstream destination evidence as separate `evidence` records.
   A source-processed event may resolve as `migrated` only after its source
   HTTP acknowledgement and its destination state evidence are both proved.
   A replay requires a destination acknowledgement and destination effect.
   `accepted-exception` remains unresolved in the tool's report and needs an
   explicit owner decision outside this ledger.

6. Run `python scripts/provider_delivery_ledger.py <ledger> report` after
   ending the window. `NO_GO` lists missing coverage, ownership, attempts,
   or effects. `EVIDENCE_REVIEW_REQUIRED` means the metadata is internally
   complete but a human must inspect the protected evidence and the full
   cutover checklist. The tool never returns a cutover approval.

The optional inventory identity file has only allowlisted lookup keys:
`stripeEvents`, `stripeBilling`, `githubIndexes`, `githubMessages`,
`plaidItems`, and `plaidSync`. Store it outside Git with mode `0600` and
delete it under the retention policy. The output includes only booleans,
counts, and sync status/revision. The exact DDB checks are:

| Provider | Source/destination evidence |
| --- | --- |
| Stripe | `SYSTEM#STRIPE_EVENT` / `EVENT#<evt_id>` marker and `USER#<mapped_user>` / `BILLING` row, plus a fresh live subscription read confirming customer, subscription, Price, period, status, and destination `metadata.userId`. |
| GitHub | `GITHUB_EVENT#<installation>#<repository>` / `ROUTINE#...` subscription index, matching `EVENT_GROUP_ROUND` queue enqueue evidence, and a `GROUP_MESSAGE` with the delivery GUID as `eventId` and the expected routine ID. Queue depth by itself is not job evidence. |
| Plaid | `PLAID_ITEM#production#<item>` / `CONNECTION` mapping, `USER#<owner>` / `PLAID_SYNC#<connection>` row with advancing revision, and a completed authorized destination `/transactions/sync`. An HTTP 200 with no Item mapping is unprocessed. |

## Provider-specific reconciliation

**Stripe.** Preserve endpoint `we_1UHW7fA7YzCs1pRZGFtVDD4J` and its
signing secret. Use the protected Stripe API/dashboard to enumerate all
relevant events and endpoint delivery attempts for the window, including
unsuccessful attempts, without exporting payloads into ordinary files. Stripe
lists Events for up to 30 days; `delivery_success=false` identifies events
that failed or are still pending, but still needs endpoint-specific checking.
Record all `evt_...` IDs and reconcile each marker and entitlement. Old event
snapshots can still carry the source Cognito `metadata.userId`; do not replay
those into a destination row with a new subject. Reconcile that event by its
current subscription state and record an explicit reviewed outcome. Generate
a fresh signed subscription update after the URL and metadata switch, then
prove the destination marker and entitlement. See [Stripe Events listing](https://docs.stripe.com/api/events/list)
and [undelivered-event handling](https://docs.stripe.com/webhooks/process-undelivered-events).

**GitHub App.** Use an App JWT in the protected operator environment to
paginate `GET /app/hook/deliveries` for App `4931494`; record each returned
numeric `id`, GUID, delivery time, event/action, status code, and endpoint
ownership, without storing request or response payload. GitHub retains
redeliverable deliveries for only three days and does not automatically
redeliver failures. Rebuild/verify connection and routine indexes before
redelivery. For each failed actionable delivery, use its numeric ID with
`POST /app/hook/deliveries/{id}/attempts`, then inspect the new attempt and
destination group message/deduplication marker. A successful `issues.opened`
acknowledgement with `matchedRoutines=0` is not a successful routine run.
See [GitHub App delivery API](https://docs.github.com/en/rest/apps/webhooks)
and [redelivery limits](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/redelivering-webhooks).

**Plaid.** The user approved copying the application credential only;
end-user Item access tokens must not be moved. The existing source connection
must be classified before enabling destination Plaid ingress. Plaid retries
failed webhooks for up to 24 hours, but the current handler's unknown-mapping
HTTP 200 suppresses those retries. Plaid's
[`/beta/webhook_events/list`](https://plaid.com/docs/api/webhooks/webhook-events/)
excludes `TRANSACTIONS`; reconstruct transaction changes with
[`/transactions/sync`](https://plaid.com/docs/transactions/webhooks/) after
the owner reconnects an Item. Until Item ownership, webhook URL, mapping,
cursor, and sync completion are proved, mark Plaid delivery coverage and
replay outcome unknown. See [Plaid webhook retries](https://plaid.com/docs/api/webhooks/)
and [Item webhook update](https://plaid.com/docs/api/items/).

## Current blockers

- The source is live; no immutable provider delivery window or provider-side
  enumeration has been captured. Neither table count nor CloudWatch request
  count proves zero missing deliveries.
- Destination state has not been imported, so Stripe billing/markers and
  Plaid connection ownership cannot be reconciled there.
- The source has one Plaid connection and no Item mapping or sync row. Its
  active/disconnected status and required reconnect are unresolved.
- GitHub App delivery listing requires the protected App JWT; no three-day
  delivery inventory or signed destination routine outcome has been recorded.
- The source/destination job queue, in-flight messages, and DLQ need a
  per-message drain or archive ledger. SQS approximate depth cannot prove
  every immutable event ID reached a destination effect.
- SES inbound mail needs its separate durable quarantine/replay proof before
  disabling the source receipt rule or moving MX.
