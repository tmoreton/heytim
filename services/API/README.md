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

## External webhooks and the local Mac router

Create a webhook source in the Apple app’s Webhooks settings. The account owns its URL and bot allowlist; create and credential rotation reveal the bearer credential and signing secret once. Disabling or deleting a source stops new ingestion and queued execution. Accepted transcripts remain in the account inbox for 90 days. Raw multipart audio is bounded and authenticated, then discarded; a transcript is required.

Pebble Index sources accept the official `multipart/form-data` payload with `transcription` and `recordedAt`. Signed deliveries verify the exact version 1 `X-Index-*` headers and canonical prefix plus raw body, with a five-minute timestamp window. Older device firmware can use `Authorization: Bearer <credential>`; choose `hmac` authentication through the source API to require signing exclusively. Test events appear in the inbox and never run a bot.

Generic sources accept a JSON object containing `text`, `transcript`, or `transcription`. Configure the optional `textPath` source field when a provider sends a different shape—for example, `event.message.text` extracts the string from `{"event":{"message":{"text":"A question"}}}`. Paths contain at most eight literal object keys, each at most 64 UTF-8 bytes. Arrays, expressions, prototype keys and control characters are rejected. Missing or non-string message fields return HTTP 422; fields such as `userId`, `botId`, or model settings in the provider payload never grant authority. Text is limited to 8,000 characters and 16,000 UTF-8 bytes.

Generic authentication supports bearer credentials or `X-Webhook-Timestamp` (Unix seconds) plus `X-Webhook-Signature: sha256=<lowercase hex>`, computed as HMAC-SHA256 with the signing secret over the timestamp, a literal period, and the exact raw JSON bytes. Provide a stable JSON `eventId` or `id` for retry deduplication; otherwise the exact body hash supplies an identity. Unbound HTTP event ID headers are ignored. A request presenting signed metadata must pass signature validation and cannot fall back to bearer authentication.

Local routing remains pending while the authorized Mac app is unavailable. The Mac claims one bounded request, runs the pinned local decider, and submits a leased result; it does not expose a public listener. Ambiguous bot choices stay in review. Uncertain reasoning predictions preserve the chosen bot’s saved effort. Fixed and manually routed events use the same durable dispatcher, conversation and existing APNs reply notifications. External events wait for a busy bot rather than interrupting its current task. A sparse DynamoDB outbox and the existing five-minute watchdog recover failed queue handoffs, including when the Mac is offline.
