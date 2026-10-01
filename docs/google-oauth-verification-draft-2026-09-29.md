# Google OAuth verification draft and privacy review

**Status:** Draft for product/legal review. At the last Google Cloud Console
check, HeyTim's OAuth audience was **External / In production** and the Branding
and Verification Center pages both said **“Your branding has been verified and
is being shown to users.”** Search Console showed `https://heytim.ai/` as a
verified property. The existing Web client, **HeyTim Gmail**, includes the new
destination callback
`https://srrkqsqrqd.execute-api.us-east-1.amazonaws.com/public/oauth/google/callback`
alongside the legacy callbacks. None of this is approval for Google user-data
access. Data Access still listed `youtube.readonly`, `gmail.readonly`, and
`gmail.compose` as **not yet verified**. `Prepare for verification` was enabled,
but no data-access verification form was submitted from this work. Google may
still show the unverified-app warning to a user who attempts those scopes, and
the unverified-user cap was 1/100 at that check. The deployed
`HEYTIM_GOOGLE_REVIEW_APPROVED=false` and
`HEYTIM_GOOGLE_CONNECTIONS_ENABLED=false` gates keep Google connections hidden.
Keep both gates false until the declared scopes, policy, demo, assessment, and
Google approval are complete. The live Verification Center still needs scope
justifications, an intended-use description, and a demonstration video for a
data-access submission. A registered destination callback and verified branding
do not remove Google's unverified-app screen.
The live `https://heytim.ai/privacy/` page returns HTTP 200 and includes
Google-connection and OpenRouter disclosures. Its completeness and policy
compliance still require review before submission.

## Scope inventory and proposed Google form answers

The backend starts each Google service as a separate user-selected connection
through one Web OAuth client. The authorization request uses a one-time state,
PKCE, offline access, and the destination HTTPS callback. A refresh grant is
stored per connected account in AWS Secrets Manager; selected bots receive
access to only the connection IDs the user assigns. This is the implemented
path **if Google connections are enabled**, not a claim of Google's approval.
The Google Data Access page currently declares the three scopes in this table;
the code can additionally request the five Workspace scopes below if its
single Google connection gate is enabled.

| Scope requested by current code | Use and proposed justification | Why a narrower scope does not currently work |
| --- | --- | --- |
| `https://www.googleapis.com/auth/youtube.readonly` | “When a user connects a YouTube account and assigns it to a bot, HeyTim searches videos and reads that user's channel profile, statistics, and uploaded-video list for requested research and summaries. It does not upload, edit, or delete YouTube content.” | Public video search could use a project API key, but the implemented `mine=true` channel and uploads calls require a user grant. No YouTube write scope is requested. `openid` and `email` are requested for account identification. |
| `https://www.googleapis.com/auth/gmail.readonly` | “When a user connects Gmail and assigns that connection to a bot, HeyTim searches mail, reads message/thread content and labels, and summarizes or uses selected messages to answer the user's request. HeyTim exposes no tool to send, delete, archive, or relabel mail.” | Metadata-only scopes do not provide message bodies needed for the implemented `get_message` and `get_thread` tools. The `gmail.readonly` scope gives the required read access without Gmail modification rights. |
| `https://www.googleapis.com/auth/gmail.compose` | “HeyTim creates a new Gmail draft, including optional reviewed HTML and inline images, for the user to inspect in Gmail. The app does not expose a send operation; the user chooses whether to send the draft in Gmail.” | The product is a standalone app using Gmail REST drafts across the user's mailbox; the add-on-only compose scope is not a substitute for this flow. The broader `gmail.modify` or full-mail scope is unnecessary. Google's consent wording for `gmail.compose` includes the ability to send, even though this application implements only draft creation; do not describe the *scope itself* as incapable of sending. |

The actual Gmail adapter exposes `search_threads`, `get_thread`,
`get_message`, `list_labels`, `list_drafts`, `get_draft`, and `create_draft`.
Its `create_draft` calls Gmail's drafts endpoint and returns
`draft_created_not_sent`; no send/delete/modify endpoint is exposed.
The YouTube adapter exposes search, own-channel details, and uploads.

## Five Workspace scopes implemented but absent from Data Access

The same production OAuth client is configured to request these five scopes
when a user connects **Google Workspace**. They were **not listed** on the
Google Data Access page at the last check:

- `https://www.googleapis.com/auth/drive.readonly`
- `https://www.googleapis.com/auth/documents.readonly`
- `https://www.googleapis.com/auth/calendar.calendarlist.readonly`
- `https://www.googleapis.com/auth/calendar.events.freebusy`
- `https://www.googleapis.com/auth/calendar.events.readonly`

Google says to declare **all scopes used by the app** in Data Access. Add and
justify all five if Workspace will be enabled for this submission. The new
separate Workspace connection gate defaults off, so Gmail and YouTube can be
reviewed without offering these undeclared Workspace scopes. Deploy and verify
the gate before relying on it; production's existing global Google flag still
disables all three services together. Keep Workspace's separate enable and
review flags false until its scopes and feature are ready. The Workspace MCP
tools are documented as Developer Preview, so verify that this Google project
is admitted and each feature works before claiming it in the review video.
`drive.readonly` is restricted; `documents.readonly` is sensitive. Verify each
Calendar scope's current classification in the Console when added.
Google recommends considering per-file `drive.file` with Picker as a narrower
alternative to broad Drive access, but the current product searches and reads
across an account and has no Picker grant flow. Do not claim a narrower scope
is technically impossible without a reviewed product decision.

### Data Access form still to prepare

The three scopes already listed remain unverified. Google asks how the
**sensitive** YouTube scope will be used and why a narrower permission will not
work. For the **restricted** Gmail scopes, the form asks which feature category
applies (the present draft-creation and summarization flow fits **Email
productivity**) and how each scope is used. The form also requests an unlisted
YouTube demonstration link. The text fields observed in the Console have a
1,000-character limit. Use the scope table above as source material, then
write concise answers that match the final production code and the video.
Do not claim Workspace is covered by the three existing Data Access entries.

## Restricted-scope implications

Google classifies **both** Gmail scopes above as restricted. Its policy says
restricted Google data accessed through a third-party server requires a
security assessment by a Google-approved assessor (CASA), with recurring
review after the assessor's letter of assessment. Merely removing
`gmail.compose` would remove the draft feature but would **not** avoid this
requirement while `gmail.readonly` and server-side message processing remain.
HeyTim exchanges and stores grants on AWS and processes message content in a
server-side agent, so plan for that requirement rather than assuming a
redirect/brand update removes the warning. Google's policy expressly lists
user-benefiting productivity features such as generative email summaries as
an eligible Gmail use case, subject to review and Limited Use.

Google requires a publicly accessible privacy policy on the verified home
domain describing how Google data is accessed, used, stored, and shared. The
current website [privacy source](../apps/website/src/pages/privacy.tsx)
**already names** optional Gmail, YouTube, and Workspace connections, assigned
bots, AWS Secrets Manager, OpenRouter and downstream model providers, saved
conversations/files/memory/tool results, group sharing, and what disconnect
does not erase. It does **not** yet contain an affirmative statement that
HeyTim's use and transfer of Google Workspace API data adheres to the Google
API Services User Data Policy, including Limited Use. Add that accurate
statement after policy review and confirm that the published
`https://heytim.ai/privacy/` page contains the final text before submission.
Check that the in-app disclosure immediately before Google authorization
clearly covers the requested access and third-party AI processing; a privacy
page alone cannot serve as that step. Confirm model-provider privacy settings,
deletion timing, and shared-content behavior before making definitive
promises about them.

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
  `tool-results` prefix. The current source tags these objects
  `heytim-retention=transient-tool-result` and configures S3 lifecycle
  expiration of the **current version after seven days** and noncurrent
  versions after one day. Verify the lifecycle rule is deployed on each bucket
  and that every offloaded result is tagged. Other object types have a
  30-day noncurrent-version expiration and are not covered by this transient
  current-version rule.
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

Before restricted-scope submission, verify the deployed transient-result
lifecycle and review the retention of conversations, memory, generated files,
and shared group content against Google's Limited Use and retention rules.
Preserve user-requested exports separately from intermediate tool results and
do not claim that disconnect erases historical content.

### Proposed policy addendum and copy check

The present privacy source already covers most of this draft. The shortest
missing addition is an affirmative Limited Use sentence, subject to product
and legal review:

> HeyTim's use and transfer of information received from Google Workspace
> APIs adheres to the Google API Services User Data Policy, including its
> Limited Use requirements.

The following longer copy is a **review aid**, not text to publish wholesale;
reconcile it with the current page and the implemented features to avoid
duplicate or contradictory promises:

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

Before publishing any addendum, verify exact retention and deletion schedules,
OpenRouter account-level privacy settings and actual model-provider routing,
whether Google-derived content in other owners' shared groups remains after
account deletion, and whether the service can promise that no Google data is
used to train a general-purpose AI model. The app's provider card copy is
narrower than the website privacy policy and cannot replace the in-app
pre-authorization disclosure.

## Demonstration video outline

Use a dedicated test account with fabricated mail, a test YouTube channel, and
test Workspace files/calendar events if those scopes remain. Arrange a
reviewer-accessible build or restricted test environment that exercises the
same Web OAuth client and final feature flow while public Google connections
remain disabled. Record the actual iPhone or Mac app and browser flow in
English, with the consent browser address bar visible and the OAuth client ID
legible. Google asks for
an **unlisted YouTube video** showing the grant and actual use of **each**
requested sensitive or restricted scope. Capture separate segments or clearly
marked timestamps for each feature.

1. Open the public `heytim.ai` homepage and final privacy policy. In the
   signed-in iPhone or Mac app, show the **Connections** screen and the clear
   disclosure shown immediately before requesting Google permission. Show the
   optional Gmail and YouTube choices, plus Workspace only if retained.
2. Start Gmail authorization. Show the HeyTim consent name, Google URL and
   client ID in the browser address bar, the `gmail.readonly` and
   `gmail.compose` permissions, and the return to HeyTim. Assign only this
   connection to a test bot.
3. For `gmail.readonly`, ask that bot to search a fabricated message and read
   and summarize its body; show the source message and result. For
   `gmail.compose`, request a draft reply/newsletter, show the created item in
   Gmail **Drafts**, and show that it was not sent. Do not imply the granted
   compose scope itself lacks send permission.
4. Connect YouTube separately. Show its `youtube.readonly` consent, then the
   own-channel profile, statistics, and uploads. Public video search can be
   included, but by itself it does not demonstrate the user grant; show the
   `mine=true` result.
5. If Workspace scopes remain in production, connect Workspace separately
   and show account-wide Drive search/read, a Doc, a Sheet, calendar list,
   event read, and free/busy use against fabricated data. Ensure every one of
   the five declared scopes maps to a visible action and the Developer Preview
   MCP integration actually works in the production configuration. Otherwise
   keep Workspace out of the production authorization path and this request.
6. Show disconnect/revocation in HeyTim and, if possible, the grant removal in
   Google Account settings. Do not display OAuth tokens, client secrets, real
   email content, or personal data in the recording.

## Restricted Gmail and CASA evidence to prepare

Google must first accept the exact scope declarations and feature explanation;
its verification team then guides the restricted-scope security assessment.
Prepare a factual evidence packet before starting that external process:

- The production architecture and data-flow diagram from OAuth grant through
  AWS Secrets Manager, the Gmail tools, S3/DynamoDB/AgentCore Memory, and
  OpenRouter/model providers, including the user-assignment control and the
  disconnect/account-deletion paths.
- Public, same-domain homepage and privacy-policy URLs; the in-app disclosure
  and consent screenshots; the unlisted demo with timestamps; the OAuth Web
  client ID and exact production redirect URI; and a test account with
  synthetic data for reviewer access. Never put credentials or live user data
  in the video or evidence packet.
- Deployed S3 lifecycle and encryption settings, credential access controls,
  logging/incident-response procedures, third-party data-processing terms,
  OpenRouter privacy settings, and evidence supporting any no-training or
  retention claim. Validate prompt-injection defenses for Google content
  before asserting that model output cannot misuse private data.
- A scope-by-scope least-privilege explanation: why message bodies require
  `gmail.readonly`, why draft creation requires `gmail.compose`, and why the
  application does not expose Gmail send, delete, or modify tools. Include the
  narrower-scope analysis for YouTube and, if retained, Drive and Calendar.

Google's restricted-scope process may require an independent assessor, fixes,
and recurring assessment; approval timing and the final letter of assessment
are external dependencies. Do not represent prepared evidence as CASA
completion or Google approval.

## Submission gates

- [x] HeyTim branding is verified and shown to users in Google Cloud Console;
  `heytim.ai` ownership and the destination Web callback were checked.
- [ ] Deploy and verify the separate Workspace gate so Gmail and YouTube can be
  reviewed without offering the five undeclared Workspace scopes. If Workspace
  is included in this submission, declare and justify all five scopes.
- [ ] Review the current privacy text, add the affirmative Limited Use
  statement, verify the final page is publicly live at the exact consent
  screen URL, and check the app disclosure immediately before authorization.
- [ ] Provide a reviewer-accessible test flow using the final scope set and
  synthetic accounts without enabling Google connections for public users.
- [ ] Confirm OpenRouter/model-provider settings, Google-data retention,
  transient-result lifecycle deployment, deletion behavior, and sharing claims.
- [ ] Record the unlisted video for each requested scope with the current app
  name, consent permissions, OAuth client ID, and resulting feature visible.
- [ ] Submit the accurate Data Access explanations and video, answer Google's
  follow-up, complete any required restricted-scope security assessment, and
  obtain Google approval for the **final production scope set**.
- [ ] Only after approval, review a separately scoped rollout of the Google
  connection flags. Until then keep
  `HEYTIM_GOOGLE_REVIEW_APPROVED=false` and
  `HEYTIM_GOOGLE_CONNECTIONS_ENABLED=false`. Neither verified branding nor
  pressing `Prepare for verification` removes the unverified-app warning.

## Google references

- [Restricted-scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
- [Gmail scope classification](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Google Workspace user data and developer policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy)
- [Sensitive-scope submission and video requirements](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification)
- [Drive scope classification and narrower per-file option](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [YouTube own-channel authorization](https://developers.google.com/youtube/v3/guides/implementation/channels)
- [Docs and Drive scope classification](https://developers.google.com/workspace/docs/api/auth)
- [OpenRouter ZDR and data-collection routing controls](https://openrouter.ai/docs/guides/get-started/sovereign-ai)
- [OpenRouter image API routing options](https://openrouter.ai/blog/tutorials/image-generation-models/)
- [OpenRouter response caching and account-level ZDR](https://openrouter.ai/docs/guides/features/response-caching)
