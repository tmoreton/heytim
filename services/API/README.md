# HeyTim application backend

This service owns the Amplify Gen 2 application backend: Cognito, the HTTP API, persistence, queues, schedules, workers, and operational tests. It deploys independently from the shared SwiftUI app in `apps/iOS`. The public Vite website is marketing-only and does not authenticate or call private chat APIs.

```bash
npm install
npm run contract:generate
npm run outputs:apple
npm run verify
npm run sandbox -- --once --identifier heytim --profile YOUR_AWS_PROFILE
```

Run commands from this directory. Resource construct names in `amplify/backend.ts` are stable deployment identities and must not be renamed as part of source reorganizations.

`contract:generate` emits both the TypeScript route map and the Swift route map. `outputs:apple` copies only public Cognito/API configuration from the generated Amplify browser-client output into the Apple app; it deliberately excludes infrastructure names and ARNs.

## Native Apple notifications

Create production and sandbox APNs platform applications in Amazon SNS using the Apple signing key owned by the release account. Set their ARNs as `HEYTIM_APNS_APPLICATION_ARN` and `HEYTIM_APNS_SANDBOX_APPLICATION_ARN` before the Amplify deployment. The API then creates per-device endpoints and the worker delivers directly through SNS. Existing Expo registrations continue to work unchanged.

Local Amplify sandboxes default to same-account SNS platform applications named `HeyTim` when those variables are omitted. This keeps repeated sandbox deployments from silently removing native notification delivery. Set the variables explicitly when an account uses different application names; production still requires the production ARN.

Never store an Apple `.p8` key, APNs token, or signing certificate in this repository. CI should supply the two platform application ARNs as environment variables.

## Apple device tools

Signed-in Apple clients register short-lived capability leases at `/devices/{deviceId}/capabilities` and poll only calls assigned to that device. Bot configuration, a live lease, a non-paused client, and a client-side per-bot grant must all agree before the worker exposes a device tool to AgentCore. Tool arguments and identity are digest-bound to the saved runtime interrupt; callbacks conditionally resume the owning turn once. Calls expire after five minutes, leases after three minutes, and health or screen results are not copied into the device-call record. A stale lease cannot bypass a local pause: the client rejects the call even before its next heartbeat removes the advertised capability.

Device tools are disabled for schedules, inbound email, and group runs because those contexts cannot guarantee that an authorized foreground device is present. Do not turn the device endpoints into generic remote procedure calls or accept coordinates, scripts, accessibility selectors, HealthKit sample types, or unsigned callback payloads from a model.

## Plaid transaction sync

Plaid Link creates an initial `PLAID_SYNC` job and registers the signed webhook at `/public/webhooks/plaid`. The webhook verifies Plaid's ES256 signature and exact request-body hash before looking up the Item owner and queueing another job. Existing Items receive their webhook URL on their next manual sync. The connection detail screen exposes `POST /connections/{connectionId}/plaid-sync` for an owned manual refresh and shows the status returned by `GET /connections`.

The worker calls `/transactions/sync` from the saved cursor, finishes all pages, and restarts the window if Plaid reports a pagination mutation. It merges additions, modifications, and removals into a private, versioned S3 ledger under the user's actor prefix; only then does it conditionally checkpoint the final cursor in DynamoDB. Bot transaction reads use that ledger and enforce the bot's selected account IDs. The raw cursor tool is intentionally not exposed to bots. Old snapshots are retained for in-flight readers for 48 hours, then pruned; disconnect queues deletion of every ledger object version. Failed jobs go through the worker queue and DLQ. `needs_reconnect` indicates an invalid Item grant; `waiting_for_plaid` indicates Plaid has not made transactions ready yet.

Before enabling production traffic, deploy the API/worker and the AgentCore runtime together, confirm the Plaid secret grants for both roles, then exercise initial history, a new transaction, a pending-to-posted replacement, an Item login-required error, manual retry, and disconnect cleanup against a non-production Plaid Item. Do not use the transaction snapshot alone as an accounting ledger without reviewing transfers, pending items, and category rules.
