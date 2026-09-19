# Private browser login handoff

HeyTim opens a live view of the **bot's AWS browser**, not an ordinary local
browser tab. Direct-chat web links now route into that bot browser. External
Safari/Chrome sign-ins still do not authenticate the bot.

## User flow

1. In an owned bot's direct chat, enable the browser tool and wait for its active
   response to finish, or stop that response.
2. Choose **Open bot browser** or a web link in the bot's response. The idle bot's
   private browser opens automatically. Sign in yourself.
3. Under **More**, optionally enable **Remember login for this bot only**. This
   is off by default. More also contains the mobile/desktop site preference.
4. Choose **Resume bot**. The viewing connection closes, automation is enabled,
   and one continuation goes through the existing message/tool-approval path.
5. **Disconnect** ends the browser session but keeps a previously saved profile.
   **Forget login** ends it and deletes that bot's saved profile. Both remain
   available in the bot menu's **Browser connection** after tool removal.

Do not paste passwords, cookies, or session tokens into chat. A login is not new
permission to submit forms, publish, purchase, merge, or perform other actions.

## Isolation and lifecycle

- Version one supports direct bot chats only. Groups still reject interactive
  tools. Use separate bot instances for personal and work identities.
- References are stored under the authenticated user's partition, keyed by user,
  bot, and direct-chat scope. Bot sharing does not export browser records.
- Profile cookies/local storage live in AWS's browser profile service. The app
  stores only profile/session identifiers and lifecycle metadata.
- Browser sessions last one hour; viewing URLs last five minutes. Refreshing a
  viewing connection does not extend the browser's lifetime. Websites can expire
  saved logins independently.
- Only an explicit Remember selection saves a profile. A later direct turn can
  restore that private profile into a new browser session.
- Human control disables AWS's automation stream. Direct-send preflight and
  worker/runtime checks fail closed while login or handoff is incomplete.
- Runtime attachment verifies the caller, bot artifact scope, expected session
  name, AWS READY status, and enabled automation stream. Runtime cleanup releases
  its driver without closing the user's remote page. The app owns termination.
- Bot/account deletion revokes the browser reference first and removes the
  session/profile; failed cleanup retains references for retry.

## Concurrency and failures

Open takes the same send lease as normal messages and checks all in-flight turns.
State transitions use conditional revisions. Browser/profile creation tokens are
stored before external calls; an uncertain result is recovered with that same
token rather than creating another resource. Resume enqueues at most once. A
lost enqueue acknowledgement is reported as uncertain, never automatically
replayed. Confirmed asynchronous profile saves may be polled with the same
Remember selection; the UI bounds that polling and never calls it completed
until a continuation turn ID is returned.

## Viewer and deployment

The web app uses a disposable same-origin iframe containing AWS's DCV live-view
component. Native uses an incognito WebView of that same static viewer. Signed
capabilities are passed in memory, not URLs, browser history, persistent storage,
chat, or application logs. Browser responses use `Cache-Control: no-store`.
The viewer build suppresses provider diagnostics that could contain credentials.
The pinned SDK wrapper has two guarded compatibility fixes: an optional display
layout promise cannot tear down a working stream, and DCV decoder assets use an
absolute app-origin URL. DCV otherwise resolves its leading-slash asset path
relative to `/bot-browser/`, leaving the remote display blank. The build fails
closed if an SDK update no longer matches the reviewed wrapper.

`npm run browser:build` generates the viewer and decoder assets; it runs before
web development/export. Generated assets are ignored in Git. WebView is a new
native dependency: iOS requires a new app build, not only a JavaScript update.
The native viewer origin uses the app host, `https://app.heytim.ai`, not the
separate marketing site, and can be set at
build time with `EXPO_PUBLIC_BROWSER_VIEWER_ORIGIN`.

The backend API timeout is 29 seconds; browser mutation clients wait 40 seconds.
IAM grants browser access only to application functions, not app users. Profile
access is scoped to managed profile tags. AWS requires CreateBrowserProfile on
`*`, constrained by the required request tag; other profile actions use profile
ARNs and resource tags.

The unrelated long-run recursion override remains off. Deploy browser changes
with `HEYTIM_ALLOW_RECURSIVE_POLLS=false` (or unset); the worker retains
`RecursiveLoop: Terminate`. The eight-hour polling-chain issue is not resolved
by this feature.

## Earlier release verification record — September 9, 2026

The mobile/browser/dictation refinement has a deployed, verified backend. See the
[frontend verification record](../apps/website/src/features/browser/README.md)
for current cloud checks and the remaining real-device verification. The
historical results below do not validate those newer edits.

- Runtime version 46 READY at 21:54 UTC; deployment changed only the code archive.
- Backend deployment completed at 22:01 UTC with five authenticated routes;
  the continuation-scope refinement deployed at 22:22 UTC.
- The corrected web viewer deployed at 22:22 UTC on `app.heytim.ai` and
  `heytim.expo.app`. Native source/bundling is implemented, but no new iOS
  binary was built or released in this change.
- 147 runtime tests plus five packaging tests passed. Packaging is pinned to the
  tested Strands 1.55.0 rather than silently resolving the new 1.55.1 release.
- All 236 backend tests passed with the runtime's AWS SDK environment, including SDK schema/signing
  validation, private ownership, failed/concurrent handoffs, cleanup, and worker
  integration. All 45 frontend tests, type checking, lint and source-size checks
  passed. Isolated UI checks covered desktop and 390/320-pixel widths, default
  no-save consent, expiry, busy conflicts, bounded save polling, uncertain
  network results, and cleanup after browser tool removal.
- GitHub Engineer read-only baseline turn
  `274472e0-d283-481e-b5b4-5ce1c239b45e` completed in about 31 seconds and confirmed
  example.com's heading. No Anthropic/GitHub changes were made.
- Live API open created a private session, set automation DISABLED, and rejected
  a message during human control. AWS recursion configuration remains Terminate.
- AWS saved an empty test profile at version 1 and restored that same profile
  into a new private session after Disconnect. Duplicate Resume returned the
  same turn `119d8d2a-1961-4134-926b-5ed767e5277a`, without another enqueue.
  Forget login removed the profile; AWS GetBrowserProfile confirmed NotFound.
- An early generic Resume selected an older task. The continuation instructions
  now explicitly preserve the most recent request and its read-only limits.
  This is prompt guidance, not deterministic task-ID binding or a general
  reliability guarantee. A later answer reused an earlier observation without
  a browser action and was not counted as end-to-end proof.
- Final live turn `d5eed2e3-8579-4110-b114-74a91ac35c08` recorded an actual browser
  action and completed in about 31 seconds. The production viewer independently
  displayed Example Domain in the same private session after the run, proving
  bot-to-human page continuity. No Anthropic/GitHub writes or submissions occurred.
- Test profiles were deleted and test sessions closed. No real authentication
  cookies were used: actual Anthropic login persistence still requires the user
  to sign in inside the bot browser. These tests do not prove an authenticated
  Anthropic submission. Test messages remain in the GitHub Engineer chat, so
  after signing in the user should explicitly request continuation of the
  Anthropic submission task instead of the completed verification task.

## Primary references

- [AWS browser live-view integration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-dcv-integration.html)
- [AWS browser profiles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-profiles.html)
- [AWS AgentCore IAM actions and conditions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html)
