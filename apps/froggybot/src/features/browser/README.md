# Private bot browser handoff (frontend)

V1 is owned **direct chat only**. The toolbar appears for a bot with the `browser`
tool. Every owned direct bot also has **Browser connection** in its actions menu,
so a removed browser capability cannot hide Disconnect / Forget login. Groups do
not expose this UI; their browser credentials must never fall back to a personal
session. The server is the authorization authority.

## Viewer and native support

- Uses the official `bedrock-agentcore/browser/live-view` React component, pinned
  to 0.4.3, in a disposable iframe on web and a real `react-native-webview` 13.16.1
  on native (the version specified by Expo 57 docs).
- `npm run browser:build` compiles the isolated viewer and copies AWS's decoder
  assets, including license notices, to ignored `public/` build output.
  `npm start`, `npm run web`, and `npm run build:web` run it automatically.
- **Deploy the web export before testing native.** Native's viewer shell defaults
  to `https://app.froggybot.com/bot-browser/index.html`. Set
  `EXPO_PUBLIC_BROWSER_VIEWER_ORIGIN` to an HTTPS preview host for a preview build;
  localhost HTTP is allowed for development. It must host the matching viewer and
  `/nice-dcv-web-client-sdk/dcvjs-esm/` decoder files. No URL query carries tokens.
- **A new native build is required** to include WebView; do not ship this as an
  OTA-only update to an older installed app. No physical iOS authentication flow
  is claimed verified until that build is installed and tested.
- New sessions opened on a phone use **390×780**; desktop sessions use
  **1440×900**. The viewer receives the session's actual dimensions. Do not
  assume DCV can resize an existing session: its optional display channel may
  be unavailable. Existing desktop sessions show migration guidance on mobile.
- Direct-chat Markdown links open the bot browser automatically and navigate in
  the same private profile. Long-press copies a link. Groups retain external link
  behavior: group credentials must not silently use a personal browser profile.
- Mobile chrome is near full screen, with privacy/help/maintenance controls under
  **More**. The desktop conversation's message widths are unchanged.

## Privacy and handoff behavior

Opening the dialog now automatically performs Open if the bot is idle and has
the browser capability; no second tap is needed. Open / Refresh asks for a
short-lived signed Live View URL. It stays in
component/frame memory, is never placed in a route, chat, logs or storage, and is
discarded on expiry, handoff, disconnect or component unmount. DCV logging is
disabled in the pinned SDK's wrapper during the isolated build, and displayed
connection exceptions use fixed safe wording. Destroying the iframe/WebView also
destroys the SDK's module-level auth cache. Before importing the SDK, both storage
APIs are shadowed with memory-only stores in the viewer document; AWS's settings
and data caches cannot persist to the device or change the parent app's login.
The native viewer is incognito, blocks
navigation outside its exact shell URL, and does not share device cookies.

Remember login lives under More and is unchecked each time the dialog opens. It saves only after an
explicit Resume. Disconnect and Forget require confirmation; Forget removes this
bot's saved profile and closes its session, not another bot's login. The bot name
remains visible; the private scope and saved-login status appear under More.

## Persistent mobile sites

The API runs bounded, fixed CDP setup commands under the direct-send lease. It
enables automation only for setup, then disables it in a `finally` block before
signing human access. No CDP endpoint or AWS credentials are given to the client.
The small pinned WebSocket dependency ships as an unmodified vendored wheel.

An app-owned Chromium extension sets mobile request headers using declarative
rules. Unlike temporary CDP emulation, they survive driver disconnects and later
navigation. More includes a desktop-site override. The extension reads no page
content/cookies and sends no telemetry. IAM grants access to its exact ZIP only.
Sites can still insist on desktop layouts; this is a mobile-site request, not an
ability to rewrite arbitrary sites. A site already open may need a reload after
changing mode; the app never reloads an unfinished form automatically.

Sessions created before the extension was deployed, or started with a desktop
viewport, are not silently destroyed. Save any wanted login with explicit
Remember/Resume, then disconnect and reopen from mobile. Deployment order:
backend and extension asset, web viewer, then compatible native update. Build 20
already includes WebView; no new native dependency was added by this refinement.

## Mobile refinement release verification — September 9, 2026

- 48 frontend and 240 backend tests passed, plus lint, type checks, source size,
  web export, and native iOS export. Device-microphone behavior still needs an
  on-device check; late transcript/permission/cross-chat events have regression tests.
- UI fixture checks passed at 320px/390px and desktop, including real Markdown
  link routing, no implicit login saving, expiry, busy conflicts and lost replies.
- Real isolated Chromium tests exercised the production CDP commands, same-profile
  navigation/cookie retention, and mobile/desktop headers after the setup tab and
  control connection closed.
- Earlier root-created AWS disposable-session checks were blocked by automation WebSocket HTTP 404
  (`Required resources not found`) despite GetBrowserSession reporting READY.
  The unchanged official SDK desktop baseline also failed with 404 after a
  20-second startup allowance. This does not identify the cause as a service
  outage. All test sessions and temporary
  S3 extension versions were cleaned up. No existing bot session was touched.
- Backend and exact-object extension asset deployed successfully at 01:00 UTC
  September 10 (September 9 Eastern). No stateful resources were replaced and
  the deployed template retained `Terminate`. A post-deploy read found the live
  worker set to `Allow` despite that template; the drift was corrected and a
  second read confirmed `Terminate`. The cause of the drift was not established.
- A fresh disposable bot through the deployed API passed mobile setup, navigation
  to example.com, signed human handoff, and desktop-site override. The API role
  did not reproduce the root-created-session 404. The test browser and bot were
  removed; existing user browsers and logins were untouched. This verifies the
  deployed backend path, not the earlier root-session failure's cause.
- Full repository verification passed: 48 app, 240 backend, 152 runtime and two
  infrastructure tests, plus builds, lint, security checks and Expo Doctor.
- iOS fingerprint `60bd93f332c3736742c467f19ad348128dc0404d` matches TestFlight
  1.0.0 (20). The main release workflow publishes the web viewer before the
  compatible production OTA. This refinement requires no new native binary.
- Real-device microphone and native browser interaction still require a phone
  check. Do not interpret backend success as an on-device verification result.

Browser mutations have a 40-second client timeout, above the 29-second API limit.
The bot must be idle before opening; a 409 asks the user to wait or stop in chat.
The frontend never stops an active bot automatically or resumes it while the
person is entering credentials.

`resuming` means pending, not success. Only an acknowledged `resuming` result
permits another `/resume` with the same consent, bounded to eight attempts and a
30-second polling window. The last request can still take its network timeout.
Afterward, **Continue handoff** is explicit. A network error is never auto-retried;
GET reconciles status. Only `ready` plus `resumedTurnId` closes the modal and
refreshes the conversation. Demo mode cannot create or claim a real login.

Primary references: [AWS Live View](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-dcv-integration.html),
[SDK source](https://github.com/aws/bedrock-agentcore-sdk-typescript/tree/main/src/tools/browser/live-view),
[Expo 57 WebView](https://docs.expo.dev/versions/v57.0.0/sdk/webview/).

## AWS 0.4.3 runtime compatibility

The SDK's optional `requestDisplayLayout` returns a promise. AgentCore may reject
it with "Display channel is not available"; the SDK's synchronous try/catch does
not handle that rejection. The build wraps this advisory call with a promise
catch. Other background failures show a safe warning rather than destroying an
otherwise working stream. Neither change bypasses authentication or licensing.
