# Texting bots, bot email, and external voice notes — proposal

Updated September 18, 2026. This is a design proposal; no messaging or webhook service is configured by this document.

## Decision to review

Use **one shared HeyTim texting number** for all users and bots. A person first signs in with the existing email code, then links one phone number from account settings by completing a verification code and explicitly opting into conversational SMS. This makes a verified phone number required for *texting bots*, without making it required for every HeyTim account or changing the current Cognito user pool.

Incoming texts from a linked number go to that person's private Chief conversation by default. A first-line `@Bot Name` address sends a text directly to one of that person's bots. The server resolves exact bot names and confirms ownership; it does not let message text choose an arbitrary bot ID. Start with this explicit routing. A later Chief dispatch feature can choose a specialist, invoke it, and synthesize the answer, but direct Chief chat today can recommend a bot and does not itself dispatch to another direct conversation.

One number per bot would make the recipient obvious, but it would grow with every custom bot, require number management and ongoing fees, and make changing a bot's identity harder. A shared number keeps the public contact stable while bots change.

## Current HeyTim fit

- Direct bot messages already become pending turns and SQS work. The worker invokes AgentCore and stores the final reply in the same conversation.
- Group rounds already have a Chief-first coordination path, but group messages can be shared with room members. SMS should start in private direct conversations to avoid unintentionally sharing a personal text.
- The backend already accepts a signed GitHub webhook and runs an idempotent group routine from it. External inputs can reuse its authenticate → normalize → deduplicate → queue pattern, while keeping provider-specific verification at the edge.
- Action tools can require in-app approval. An SMS reply must not count as approval. If a turn pauses for approval, text a short notice and deep link to the app; the action remains pending there.

## Two-way SMS flow

1. The signed-in user opts into a verification code, verifies the phone number with Twilio Verify, and separately opts into **texting bots**. They can later revoke or change the linked number. Store a unique E.164 phone-to-account mapping, verified timestamp, both consent records (text/version/timestamp), and SMS preferences. Keep the current email sign-in. Update the public SMS program and privacy/terms pages before launch because they currently describe verification codes only.
2. A Twilio Programmable Messaging number receives a text and posts it to a public HeyTim webhook. Verify Twilio's request signature against the exact configured URL and request fields. Validate the destination number, and use `MessageSid` as the deduplication key.
3. Resolve `From` only against an active, linked, consented account. Unknown or unlinked numbers never receive account content. Handle STOP/START/HELP as messaging controls, not bot prompts.
4. Resolve the target as Chief or an explicit `@Bot Name`. Reject ambiguous or unavailable names with a safe reply. Persist the message as a channel-tagged direct turn and enqueue the existing bot worker. Acknowledge Twilio promptly with an empty TwiML response rather than waiting for model work.
5. After the worker saves the final answer, send a short text from the same number. Keep the complete answer, sources, artifacts, and activity in the app and link to that conversation when needed. Record Twilio's outbound ID and delivery callback; retries must not create a second bot turn or duplicate reply.
6. Apply per-number and account rate limits, budget limits, and an SMS-safe tool policy. Let users choose which bots are textable. Do not expose sensitive connected data, secrets, artifacts, account-management functions, or approval actions over SMS. A changed or revoked phone mapping immediately stops routing to the old account.

**Carrier prerequisite:** Twilio Verify handles one-time codes through managed senders, but it does not supply a replyable bot number. Sending bot replies from a US local number requires Twilio A2P 10DLC brand/campaign registration; a toll-free number has its own verification. A sole proprietor can apply through Twilio's sole-proprietor path if eligible. Choose and register the conversational sender before promising a launch date. This is a separate approval from Twilio's account compliance profile and from Verify itself.

## Voice notes and later webhooks

If “Pebble” means **Pebble Index 01**, its app can POST each recording to one HTTPS webhook. It can send transcription, `audio/mp4`, or both as multipart form data, and supports a configured `Authorization` header. The webhook has a configurable button trigger. For a first version, use transcription-only delivery on a deliberate trigger, such as double-click, to a public HeyTim endpoint protected by a user-scoped capture token.

Each user creates a revocable, random, narrowly scoped capture token in the HeyTim app. The server stores only its hash and associates it with that user. The endpoint validates the token, limits size, parses the transcript as untrusted content, deduplicates retries (Pebble documents `recordedAt` but no unique delivery ID), and queues a private Chief turn or saves an inbox note according to the user's chosen setting. If audio is enabled later, store it privately in S3 with explicit size/type limits and the user's retention rules.

The Index webhook is an input path, not a conversational reply channel. HeyTim can show the result in the app and notify the phone; texting a result is optional for users who enabled SMS. A future Pebble MCP integration could support more interactive requests through its cloud-only MCP sandbox, but it is a separate feature.

Future providers should have separate webhook adapters that verify their own signature or scoped token, map the source to an account, and emit a common internal event: `source`, `providerEventId`, `userId`, `target`, `text`, `attachmentRefs`, `receivedAt`. Only the normalized, authenticated event may start a bot turn or routine. GitHub issue events remain group-routine events; Pebble voice notes default to private capture.

## An inbox address for every bot

Give each bot a stable address such as `chief-k7m2q9p4@bots.heytim.ai`. Allocate the suffix when the bot is created; do not derive the address solely from its current name. Names can collide and change. Show the address in the bot's settings, allow the owner to disable or rotate it, and never reassign an old address to a different bot. An email address is a route to a bot, not a separate mailbox or a new login identity.

Use the dedicated `bots.heytim.ai` subdomain so incoming bot email remains isolated from root-domain mail. A single Amazon SES receipt rule for `bots.heytim.ai` can receive every bot address in `us-east-1`; it does not need one rule or purchased mailbox per bot. The inbound pipeline is: subdomain MX → SES spam/virus checks → private S3 raw message → parser/validator → deduplication by SES message ID plus envelope recipient → existing SQS bot work. Route using the SMTP envelope recipient from SES, not the `To:` header inside the email. Preserve subject, sender, `Message-ID`, and reply references for display and future threading. Ignore or safely reject unknown, disabled, or deleted bot addresses.

Treat received mail as **untrusted input**. A visible `From:` address alone is not proof of identity. Check SES authentication and spam verdicts, apply size and attachment limits, strip quoted history for the bot prompt, and keep the original MIME privately for inspection and retention controls. Initially accept instructions only from sender addresses that the account owner explicitly allows; mail from other people or services can land in a review inbox without automatically invoking tools. Imported email content never grants permissions or approves a bot action. Guard against auto-reply loops and repeated delivery.

For the first release, **receive only**: put the message in that bot's existing private conversation and notify the owner in the app. Optionally run the bot automatically for allowed senders under a limited tool policy; otherwise let the owner decide when to ask the bot to process it. HeyTim's current Gmail connection reads and drafts mail from a user's Gmail account; it does not provide bot-owned inboxes or send mail.

Outbound mail can come later. A verified HeyTim domain in SES would let the app send from bot addresses, with DKIM/DMARC, bounce/complaint handling, rate limits, and a sent-message record. Start with drafts or an explicit per-message approval before sending to anyone outside the account. Incoming replies to a sent message would return to the same bot address and conversation.

## Suggested rollout

1. Confirm which Pebble product is in use. A transcript-only capture endpoint and private inbox/Chief routing can be built and tested without SMS carrier approval. Add audio retention only after checking real recording sizes and user need.
2. Add the bot email subdomain and receive-only inbox routing. Keep externally received mail inert or limited until the owner chooses its allowed senders and automation settings.
3. In parallel, choose the SMS sender type and complete its carrier registration. Keep email sign-in as the default.
4. Build phone linking and separate consent records, then one shared-number SMS flow to Chief with explicit `@Bot Name` targeting. Test duplicate webhooks, unknown numbers, STOP, delayed replies, and approval pauses.
5. Consider automatic Chief-to-specialist dispatch, outbound bot email, and a Pebble MCP server after the basic flows are reliable.

## Sources

- [Twilio A2P 10DLC registration](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc)
- [Twilio sole proprietor registration](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/direct-sole-proprietor-registration-overview)
- [Twilio inbound messaging webhooks](https://www.twilio.com/docs/messaging/guides/webhook-request)
- [Twilio webhook signature validation](https://www.twilio.com/docs/usage/webhooks/webhooks-security)
- [Pebble Index 01 webhook and MCP settings](https://help.repebble.com/en/articles/15724406-index-advanced-features-mcp-webhook)
- [Amazon SES email receiving](https://docs.aws.amazon.com/ses/latest/dg/receiving-email.html)
- [Amazon SES recipient and authentication behavior](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-concepts.html)
- [Amazon SES receipt-rule domain matching](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-receipt-rules-console-walkthrough.html)
- [Amazon SES domain identities for sending](https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html)
