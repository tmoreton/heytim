# Provider webhook cutover: Stripe and GitHub App

**Status:** Prepared, not executed. Use inside the bounded maintenance window in
[`account-isolation-cutover-2026-09-25.md`](account-isolation-cutover-2026-09-25.md).
The source API and its provider endpoints remain active until the migration
acceptance checks pass. Keep the source configuration available for the 30-day
rollback period.

Before either endpoint changes, complete the immutable event, attempt, owner,
and downstream-effect checks in
[`provider-delivery-reconciliation-2026-09-29.md`](provider-delivery-reconciliation-2026-09-29.md).
Its current read-only inventory is **NO-GO**: destination billing/event state
is empty, the source has one Plaid connection without an Item mapping, and no
bounded provider delivery ledger exists. SES inbound mail has a separate
quarantine and replay gate.

## Read-only inventory, 2026-09-29

| Provider | Current live configuration | Destination requirement |
| --- | --- | --- |
| Stripe | Endpoint `we_1UHW7fA7YzCs1pRZGFtVDD4J` is enabled at `https://twrxzanvwg.execute-api.us-east-1.amazonaws.com/public/webhooks/stripe`. It is live, uses API version `2026-08-26.dahlia`, and subscribes to `checkout.session.completed` and `customer.subscription.{created,updated,deleted}`. Source secret `heytim/stripe/production` exists in account `188757775631`. | The same endpoint must point to `https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com/public/webhooks/stripe` after destination billing is ready. Secret `heytim/stripe/production` has now been copied through process memory into account `820323452649` and verified by readback without exposing values. Destination Lambda wiring and live-mode behavior still need validation. |
| GitHub App | App ID `4931494`, displayed as **FroggyBot by tmoreton**, slug `froggybot-by-tmoreton`, has one JSON webhook at `https://twrxzanvwg.execute-api.us-east-1.amazonaws.com/public/webhooks/github`; TLS verification is on. | Keep the existing App and signing secret. Move only its webhook URL to `https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com/public/webhooks/github` once destination connections and routines have been validated. The destination `frogbot/oauth/github-production` secret's App ID, client ID/secret, private key, and webhook secret have been compared in memory and match the source; this legacy secret name is an existing physical identifier. |

The GitHub App's public homepage now points to `https://heytim.ai/`; it was
changed independently of the webhook on 2026-09-29 and verified on the public
App page. The destination OAuth callback was added alongside the source
callback; the setup URL and webhook are unchanged. Its display name and slug are still FroggyBot
branded. Treat those as separate user-facing branding changes. Changing the
slug can affect installation URLs;
review existing installations and redirects before doing so. GitHub's `GET
/app` response does not expose the OAuth callback or post-installation setup
URL, so inspect both in the App settings UI before enabling destination
connections. The Google OAuth client's newly authorized destination callback
does not imply approval of the application's sensitive-scope consent review.

## Invariants before either webhook moves

1. The destination API, Cognito reauthentication, migrated state, protected
   provider secrets, and authenticated connection tests must pass. Record the
   source and destination user IDs in the protected migration evidence, not in
   this repository.
2. Freeze source writes and paid-work admission, drain jobs, and appoint the
   rollback owner. Take the final source data backup and record destination
   counts/checksums as required by the account cutover plan.
3. Validate the one existing live Stripe subscription directly against its
   source `BILLING` row: customer, subscription, Price, status, period, and
   `metadata.userId`. The destination `BILLING` row must have the destination
   Cognito user ID and the same customer/subscription/Price entitlement.
4. Do not create a second live Stripe endpoint in parallel: it could deliver
   the same subscription event twice. Do not create a second subscription or
   use a live payment as a test. Use test-mode objects for checkout and failure
   scenario evidence.
5. The destination GitHub App secret must contain the same `webhookSecret` as
   the live App configuration. Do not print or persist the secret outside
   Secrets Manager or the protected GitHub environment.
6. Existing GitHub issue routines and their `GITHUB_EVENT#.../ROUTINE#...`
   subscription rows are preserved with application data, while provider
   connections are deliberately excluded. Reconnect the GitHub App in the
   destination and inspect each routine's connection ID, installation,
   repository, and connection update timestamp. Re-save a routine when these
   values differ so its subscription index is rebuilt. Validate the index
   before the URL switch, then require one signed issue event to prove the
   routine matches before unfreezing webhook traffic.

## Prepare without moving traffic

1. The existing live Stripe API key and endpoint signing secret have already
   been copied into destination Secrets Manager, with exact in-memory readback
   verification. Verify the destination Lambda points to this secret and that
   the protected GitHub production values used by the release workflow will
   not overwrite it with a different key or signing secret; GitHub does not
   expose secret values, so require a signed delivery after deployment. Keep
   `HEYTIM_STRIPE_PLUS_PRICE_ID` and `HEYTIM_STRIPE_LIVE_MODE` consistent with
   the existing live subscription and Price. The destination backend's billing
   availability and `STRIPE_LIVE_MODE` must be true only when this is ready.
2. Verify the destination GitHub Lambda references the destination account's
   App secret and that an invalid signature is rejected. Check the App's
   callback and setup URL in GitHub settings; update them to the destination
   callback only when destination OAuth connect/read/revoke tests are ready.
   Keep the source callback among allowed URLs where the provider permits it
   during the rollback window.
3. Record the Stripe endpoint ID, URL, enabled event set, API version, and
   status and the GitHub App webhook URL/content type/TLS setting. Record
   destination function health and alarms. Verify credentials without
   displaying their contents.

## Switch in the write-freeze window

1. Import and validate the destination `BILLING` row under the destination
   user's key. Change **only** the existing Stripe subscription's
   `metadata.userId` from the source Cognito ID to the destination Cognito ID,
   preserving every other metadata key and all billing parameters. This can
   create an extra source webhook event or orphaned source row while the source
   endpoint is still active; record it as a migration-only exception, keep the
   source frozen, and do not import it as an additional entitlement. Read the
   subscription again and verify the new ID, customer, Price, period, and
   status. If the metadata update fails, stop.
2. Change only the URL on Stripe endpoint
   `we_1UHW7fA7YzCs1pRZGFtVDD4J` to the destination URL. Leave the same
   endpoint ID, enabled event set, API version, status, and signing secret.
   Read it back. A URL update on the same endpoint avoids introducing a second
   signing secret; nevertheless require a new signed delivery to prove the
   destination accepts it.
3. Change only the GitHub App webhook URL using its App JWT and the [GitHub
   App webhook configuration API](https://docs.github.com/en/rest/apps/webhooks#update-a-webhook-configuration-for-an-app).
   Preserve JSON content type, TLS verification, and the signing secret. Read
   back the new URL and verify delivery status. App display name, slug,
   homepage, callback, and setup settings are separate changes.
4. Generate a fresh, legitimate Stripe subscription update after the new URL
   is active, with the destination `metadata.userId`, and confirm the signed
   event is acknowledged and the destination entitlement remains correct. Do
   not replay an old event snapshot whose metadata still names the source
   user. Use an authorized test repository and destination GitHub connection
   to produce one `issues.opened` delivery, then verify the signed delivery,
   expected routine match, and deduplication on redelivery. GitHub documents
   that failed deliveries are [not automatically retried](https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries).
5. Observe billing, GitHub delivery, destination Lambda, queue, and alarm
   health through the agreed observation period. Unfreeze only when the wider
   cutover plan's acceptance checks pass.

## Rollback before unfreezing

1. Restore the Stripe endpoint's source URL and GitHub App webhook's source
   URL. Read both back; do not delete either endpoint or rotate its signing
   secret as part of URL rollback.
2. Restore the subscription's `metadata.userId` to the source Cognito ID,
   preserving other metadata. Retrieve the subscription from Stripe and
   reconcile the source `BILLING` row against its current status and period;
   remove or document any migration-only orphan row and event marker through a
   reviewed data repair.
3. Restore source client/API bindings and provider callback settings, inspect
   failed deliveries, and redeliver only events whose owner mapping is correct
   for the restored endpoint. Keep the destination frozen until differences are
   investigated. Resume source paid work only after its entitlement and
   provider deliveries validate.

## References

- [Stripe webhook endpoint API](https://docs.stripe.com/api/webhook_endpoints)
  documents endpoint URL updates and notes that a *new* endpoint's signing
  secret is returned only at creation.
- [Stripe subscription update API](https://docs.stripe.com/api/subscriptions/update)
  supports a metadata-only update; no Price, quantity, or billing-cycle field
  should be sent for this migration.
- [GitHub App webhook API](https://docs.github.com/en/rest/apps/webhooks)
  uses an App JWT for configuration reads and URL updates.
- [GitHub webhook redelivery](https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/redelivering-webhooks)
  supports recovering recent failed App deliveries.
