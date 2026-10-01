# Google OAuth verification draft and privacy review

**Status (October 1, 2026):** Draft for product/legal review. Google's live
Verification Center now marks the HeyTim branding **verified** and shows it;
data access remains **unverified**. The center lists `youtube.readonly`,
`gmail.readonly`, and `gmail.compose` as unverified and still needs the scope
justifications, intended-use description, and demonstration video for a
submission. A registered destination callback and verified branding do not
remove Google's unverified-app screen or constitute data-access approval.
The live `https://heytim.ai/privacy/` page returns HTTP 200 and includes
Google-connection and OpenRouter disclosures. Its completeness and policy
compliance still require review before submission.

## Scope inventory and proposed Google form answers

The backend starts each Google service as a separate user-selected connection
through one Web OAuth client. The authorization request uses a one-time state,
PKCE, offline access, and the destination HTTPS callback. A refresh grant is
stored per connected account in AWS Secrets Manager; selected bots receive
access to only the connection IDs the user assigns. This describes the code
path, not a claim of Google's approval.

| Scope requested by current code | Use and proposed justification | Why a narrower scope does not currently work |
| --- | --- | --- |
| `https://www.googleapis.com/auth/youtube.readonly` | “When a user connects a YouTube account and assigns it to a bot, HeyTim searches videos and reads that user's channel profile, statistics, and uploaded-video list for requested research and summaries. It does not upload, edit, or delete YouTube content.” | Public video search could use a project API key, but the implemented `mine=true` channel and uploads calls require a user grant. No YouTube write scope is requested. `openid` and `email` are requested for account identification. |
| `https://www.googleapis.com/auth/gmail.readonly` | “When a user connects Gmail and assigns that connection to a bot, HeyTim searches mail, reads message/thread content and labels, and summarizes or uses selected messages to answer the user's request. HeyTim cannot send, delete, archive, or relabel mail.” | Metadata-only scopes do not provide message bodies needed for the implemented `get_message` and `get_thread` tools. The `gmail.readonly` scope gives the required read access without Gmail modification rights. |
| `https://www.googleapis.com/auth/gmail.compose` | “HeyTim creates a new Gmail draft, including optional reviewed HTML and inline images, for the user to inspect in Gmail. The app does not expose a send operation; the user chooses whether to send the draft in Gmail.” | The product is a standalone app using Gmail REST drafts across the user's mailbox; the add-on-only compose scope is not a substitute for this flow. The broader `gmail.modify` or full-mail scope is unnecessary. Google's consent wording for `gmail.compose` includes the ability to send, even though this application implements only draft creation; do not describe the *scope itself* as incapable of sending. |

The actual Gmail adapter exposes `search_threads`, `get_thread`,
`get_message`, `list_labels`, `list_drafts`, `get_draft`, and `create_draft`.
Its `create_draft` calls Gmail's drafts endpoint and returns
`draft_created_not_sent`; no send/delete/modify endpoint is exposed.
The YouTube adapter exposes search, own-channel details, and uploads.

## Workspace scopes missing from Data Access

The same OAuth client can request these five additional scopes when a user
connects **Google Workspace**:

- `https://www.googleapis.com/auth/drive.readonly`
- `https://www.googleapis.com/auth/documents.readonly`
- `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
- `https://www.googleapis.com/auth/calendar.events.freebusy`
- `https://www.googleapis.com/auth/calendar.events.readonly`

Google says to declare **all scopes used by the app** in Data Access. Add and
justify all five if Workspace will be enabled for this submission. This branch
adds a separate Workspace connection gate that defaults off, so Gmail and
YouTube can be reviewed without offering these undeclared Workspace scopes.
The gate must be deployed and verified before relying on it; production's
existing global Google flag currently disables Gmail, YouTube, and Workspace
together. Keep Workspace's separate enable and review flags false until its
scopes and feature are ready. The Workspace MCP tools are
documented as Developer Preview, so verify that this Google project is
admitted and the feature works before claiming it in the review video.
`drive.readonly` is also restricted; `documents.readonly` is sensitive.
Google recommends considering per-file `drive.file` with Picker as a narrower
alternative to broad Drive access, but the current product searches and reads
across an account and has no Picker grant flow. Do not claim a narrower scope
is technically impossible without a reviewed product decision.

## Restricted-scope implications

Google classifies **both** Gmail scopes above as restricted. Its policy says
restricted Google data accessed through a third-party server requires a
security assessment by a Google-approved assessor, with recurring review.
HeyTim exchanges and stores grants on AWS and processes message content in a
server-side agent, so plan for that requirement rather than assuming a
redirect/brand update removes the warning. Google's policy expressly lists
user-benefiting productivity features such as generative email summaries as
an eligible Gmail use case, subject to review and Limited Use.

Google requires a publicly accessible privacy policy on the verified home
domain describing how Google data is accessed, used, stored, and shared. The
live [`Privacy` page](../apps/website/src/pages/privacy.tsx) now mentions
connected Gmail/YouTube/Workspace data, refresh grants, agent processing of
connected-service content, and OpenRouter. It was confirmed reachable at
`https://heytim.ai/privacy/` on October 1. Review whether this wording fully
satisfies Google's Limited Use and restricted-scope requirements. Confirm
model-provider data retention/training terms, deletion timing, and
shared-content behavior before making definitive promises about those items.

### Data path confirmed in current code

- Google data returned by an authorized tool is given to the bot's model
  context. The runtime routes inference through **OpenRouter**, ordinarily to
  DeepSeek V4.1 Flash and with GLM 5.3 as fallback; model IDs can be changed
  by deployment configuration. A new code change requests
  `provider.zdr: true` and `provider.data_collection: "deny"` on both routes.
  These are routing requests, not proof that a live request used a particular
  eligible endpoint or that HeyTim itself retains no data. Per-request ZDR does
  not itself disable OpenRouter response-cache eligibility; verify the account's
  cache/privacy settings and live routing before making a firm retention claim.
- The OpenRouter Image API does not document per-request ZDR or data-collection
  controls. The runtime therefore does not offer image generation to a bot
  while it has any Google OAuth connection, including mixed-provider bots.
  This is a current product limitation, not proof that historical Google
  content can never reach an image prompt after a connection is removed;
  content provenance is not tracked across old conversation text.
- Large tool results can be saved in full under a user- or group-scoped S3
  `tool-results` prefix. The file bucket currently expires noncurrent object
  versions after 30 days but has no expiration rule for the current object;
  these transient results can therefore persist until explicit cleanup.
  Bot answers can quote or summarize Google data and are saved in
  DynamoDB direct or group message history. Completed turns send the user and
  assistant text to AgentCore Memory, where long-term facts, preferences, and
  summaries can be derived. `record_completed_turn` does not itself send the
  raw tool result to AgentCore, but content reproduced in an answer can enter
  memory. Generated files can also contain Google-derived material.
- Disconnect attempts to revoke the Google grant, schedules its Secrets
  Manager credential for deletion with a seven-day recovery window, and
  removes the connection record. It does **not** erase past conversations,
  AgentCore memories, generated files, or offloaded tool results. Account
  deletion initiates a worker that removes user-owned DynamoDB records, all
  versions under the user's S3 prefix, AgentCore user events/records, and
  connection secrets; it also handles owned groups. Material intentionally
  shared to a group owned by someone else requires an explicit review of what
  remains in that group's history or files.

Before restricted-scope submission, review the transient tool-result retention
against Google's prohibition on permanent copies of Workspace user data.
Preserve user-requested exports separately from intermediate tool results and
do not claim that disconnect erases historical content.

### Proposed privacy-policy section for review

> **Connected Google accounts.** Connecting Gmail, YouTube, or Google Workspace
> is optional. You choose which Google account to connect and which HeyTim bots
> may use it. For Gmail, those bots can search and read message headers, bodies,
> threads, labels, and drafts and can create new drafts for you to review. HeyTim
> does not provide a tool to send, delete, archive, or relabel your Gmail
> messages. For YouTube, connected bots can search videos and read your channel
> details and uploads; they cannot change your channel. If you connect Google
> Workspace, assigned bots can read the Drive files, Docs, Sheets, and Calendar
> information allowed by your grant. They cannot edit those resources.
>
> HeyTim stores a connection record and the Google refresh grant needed to
> maintain the connection. The grant is held in AWS Secrets Manager. When an
> assigned bot uses a Google connection for your request, relevant Google data
> is processed by HeyTim's AWS-hosted agent service, OpenRouter, and the model
> inference provider selected for that request to produce the answer or draft.
> Larger retrieved results can be stored in HeyTim's protected file storage.
> Information from a result may appear in your saved bot conversations,
> generated files, or bot memory. We do not sell Google user data or use it for
> advertising. You can remove a connection in HeyTim to stop future access or
> revoke HeyTim in your Google Account. Removing a connection does not remove
> earlier conversations, files, or memories that contain information already
> used by a bot; use the available content controls or account deletion for
> those records. Content you deliberately shared with other people may remain
> available to them, subject to the sharing feature's controls.
>
> HeyTim's use and transfer of information received from Google Workspace
> APIs adheres to the Google API Services User Data Policy, including its
> Limited Use requirements.

This is a **draft**, not a verified statement of every downstream data flow.
Before publishing, verify exact retention and deletion schedules, OpenRouter
account-level privacy settings and actual model-provider routing, whether
Google-derived content in other owners' shared groups remains after account
deletion, and whether the service can promise that no Google data is used to
train a general-purpose AI model. The app's provider card copy is narrower
than the present website privacy policy and cannot replace the policy itself.

## Demonstration video outline

Use a dedicated test account with fabricated mail, a test YouTube channel, and
test Workspace files/calendar events. Record the complete app and browser flow
in English, with the consent browser address bar visible and the OAuth client
ID legible. Google asks for an unlisted YouTube video showing the grant and
actual use of **each** requested sensitive or restricted scope.

1. Open the public `heytim.ai` homepage and privacy policy, then the signed-in
   iPhone or Mac **Connections** screen. Show Gmail, YouTube, and (if retained)
   Google Workspace as separate optional connections.
2. Start Gmail authorization. Show the HeyTim consent name, the Google URL and
   client ID in the browser address bar, the requested Gmail permissions, and
   the return to HeyTim. Assign only this connection to a test bot.
3. Ask that bot to search a fabricated message and read/summarize its body.
   Show the source message in the test Gmail account and the bot response.
   Then request a draft reply/newsletter, show the draft in Gmail **Drafts**,
   and show that it was not sent.
4. Connect YouTube separately. Show its read-only consent, search results,
   own-channel details, and recent uploads. The public-search step alone does
   not demonstrate why a user-scoped grant is needed; show `mine=true` data.
5. If Workspace scopes remain in production, connect Workspace separately and
   demonstrate each declared access class with fabricated Drive/Docs/Sheets
   and Calendar data. If Developer Preview access or the UI is not ready,
   remove that connection from the production authorization path and Data
   Access request for this submission.
6. Show disconnect/revocation in HeyTim and, if possible, the grant removal in
   Google Account settings. Do not display OAuth tokens, client secrets, real
   email content, or personal data in the recording.

## Submission gates

- [x] The live Verification Center marks HeyTim branding verified and shows it
  (October 1); confirm the submitted consent screen's displayed state before
  recording the review video.
- [ ] Every scope the production code can request is declared in Data Access;
  scope justification matches the demonstrated feature.
- [ ] The live Google-data privacy section is reviewed for accuracy and policy
  sufficiency at the URL on the OAuth consent screen.
- [ ] The demonstration video covers each requested scope, with current app
  name and OAuth client ID visible.
- [ ] Restricted-scope security assessment requirements, assessor evidence,
  and Google follow-up are tracked to completion. Only Google can grant the
  final approval that removes the unverified-app screen.

## Google references

- [Restricted-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
- [Gmail scope classification](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Google Workspace user data and developer policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy)
- [Sensitive-scope submission and video requirements](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)
- [Docs and Drive scope classification](https://developers.google.com/workspace/docs/api/auth)
- [OpenRouter ZDR and data-collection routing controls](https://openrouter.ai/docs/guides/get-started/sovereign-ai)
- [OpenRouter image API routing options](https://openrouter.ai/blog/tutorials/image-generation-models/)
- [OpenRouter response caching and account-level ZDR](https://openrouter.ai/docs/guides/features/response-caching)
