# Webhooks and local routing

HeyTim accepts Pebble Index voice transcripts and JSON messages through account-owned webhook sources.
Automatic bot and reasoning selection runs in the Apple silicon macOS application. The selected bot replies through
the existing AgentCore execution, conversation persistence, and final-answer APNs pipeline.

## Setup

1. Open HeyTim Settings → Webhooks. On the Mac, download the routing model and enable local routing.
2. Add a source, choose Pebble Index or JSON, and select the bots it may use. Fixed routing can target one bot without
   a local model. Automatic routing can optionally use a permitted bot you select under **When uncertain**; leaving
   it unset keeps uncertain messages for manual review. Automatic routing waits while no authorized Mac is available.
3. Save the endpoint, bearer credential, and signing secret when shown. Credentials are revealed once and can be
   replaced. Disabling or removing a source stops new requests and pending execution.
4. In the Pebble phone app, configure the desired Index gesture's webhook endpoint and Authorization header,
   select transcription delivery, and configure signing if the installed version supports it. Choose Webhook Only
   when available to avoid also running a native Pebble action. Send its connection test before a voice question.
5. Enable HeyTim notifications on the iPhone. A completed answer opens the selected bot's conversation.

The Index 01 is the recording ring; the phone sends the HTTP request. Its webhook response body does not display an
answer. HeyTim acknowledges accepted events, then delivers the answer through its own application and notifications.

## Generic JSON contract

POST to the source endpoint with `Content-Type: application/json` and `Authorization: Bearer <credential>`:

```json
{"eventId":"unique-source-event-1","text":"Compare these two plans and recommend the safer option."}
```

Use a stable event identity for retries and a new identity for each distinct message. Tests may set `test: true`;
they are acknowledged without asking a bot. Caller-provided owner, bot, reasoning, and tool grants are never authority.
For nested payloads, set the source's JSON text path, such as `data.message.text`. The path selects literal object
keys; arrays and expressions are not supported. Without a path, HeyTim checks `text`, `transcript`, and `transcription`.

Signed generic requests use `X-Webhook-Timestamp` (Unix seconds) and `X-Webhook-Signature` equal to `sha256=` followed
by the hex HMAC-SHA256 of `timestamp + "." + rawJSONBytes`, using the source's signing secret. Verification uses the
original bytes. Pebble uses its own `X-Index-*` canonical signing format, including delivery ID, trigger, test flag,
and raw multipart body. A bad supplied signature never falls back to bearer authorization.

Input is bounded by the application message and UTF-8 limits. The initial Pebble adapter requires a transcription;
an audio part may accompany it, but audio-only transcription is not offered by this webhook adapter. The app's
existing microphone dictation remains on-device through Parakeet.

## Routing and failure behavior

The API persists a source-bound event before acknowledgment. Mac routing requests have account/device ownership,
an expiring claim, a request digest, a snapshot of eligible bot metadata, and a pinned model identity. The server
revalidates the source and current bot catalog before accepting the result or executing a turn.

After a Mac abstains or rejects model input, a local source uses its explicitly configured fallback bot, if any.
The fallback must still belong to the account and remain permitted by the source. It uses that bot's saved reasoning
preference, never the uncertain model effort suggestion. Its decision is marked `local_fallback`, with the original
validated model decision retained separately for inspection. Removing or changing the fallback, disabling the source,
or removing the bot's permission stops pending execution and resumed turns. Credential rotation preserves accepted work.

Without a configured fallback, uncertain decisions and rejected model inputs remain visible for manual review in
Webhooks. Choose a permitted bot there to continue. The fallback does not run while the Mac is unavailable.
Automatic messages wait behind active bot work rather than steering it. The normal consent,
billing, resource grants, and action approvals still apply. Webhook turns do not gain bot-management or Mac-control
authority.

Automatic bot selection requires choice concentration of at least 0.60 and a probability margin of at least 0.15
over the next candidate, including the clarification option. Concentration is `(N * pmax - 1) / (N - 1)`, where `N`
includes every permitted bot and clarification. It measures how concentrated the model's distribution is around
its winner; it is not a calibrated probability that the destination is correct. The cutoff was selected using
development cases and real catalog projections, which are calibration evidence rather than a production accuracy estimate.

The reasoning classifier overrides the bot's saved Low, High, or Maximum preference only when its concentration reaches
0.60. Otherwise the turn keeps that preference. The raw suggestion, confidence, and effective effort are retained on
the turn for inspection; routing never edits the bot's saved preference. Pending dispatch has a recoverable outbox
so interrupted SQS handoffs can be retried.

## Local model and distribution

The model is `StrandsAgents/strands-decider-2B-qwen3.5-v1-2610`, revision
`216d1ccb46a9e9b036eb9187b248db98480f77d4`. The helper uses the pinned official Strands code and a hash-locked standalone
Python/Torch/MLX runtime. Model data lives in Application Support outside the signed application; routine inference
does not download models or contact an inference API. The classifier chooses a destination and effort; the selected
bot's normal provider generates the answer.

The macOS app owns the helper's lifecycle and communicates through private NDJSON pipes. MLX is preferred with MPS
fallback. The iPhone and Intel Mac builds share the inbox interface and can manually select a bot or use fixed routing.
The helper is not included in iOS.

The complete helper must be staged and signed before the app archive. Release libraries use the export's Developer
ID identity. `generate-project.rb` owns the generated Xcode project. See `packages/heytim-decider/README.md` for
installation, live evaluation, packaging, and artifact verification commands.

## Verification

Backend tests cover source authorization, exact signature bytes, replay identities, source revocation, stale catalog
and routing leases, queue handoff recovery, busy-bot ordering, per-turn reasoning, and existing notification behavior.
Native tests cover API requests, response decoding, model identity and result validation, and clarification handling.
The model evaluation uses the real pinned weights and retains original failures as well as final results; fixtures
used to tune a rubric are development evidence, not a held-out accuracy claim. Larger catalog acceptance sets have
shown correct rankings with insufficient automatic-routing coverage; optional owner-configured fallback keeps that
uncertainty explicit without changing classifier thresholds or claiming the model coverage gate passed.

Run the repository backend/runtime checks, the decider's unit and real-model gates, and both Apple destinations with
`./scripts/apple-app.sh build` and `./scripts/apple-app.sh verify`. Deployment uses the protected production GitHub
workflow; default local AWS credentials may belong to a different account. Actual ring capture and physical iPhone
APNs delivery require a device smoke check after deployment.
