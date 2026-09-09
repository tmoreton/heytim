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
- The Live View viewport is **1440×900**, matching the backend browser session.
  The target website is navigated inside the remote browser, not by copying chat
  links or sharing the user's external Safari/Chrome login.

## Privacy and handoff behavior

Only Open / Refresh asks for a short-lived signed Live View URL. It stays in
component/frame memory, is never placed in a route, chat, logs or storage, and is
discarded on expiry, handoff, disconnect or component unmount. DCV logging is
disabled in the pinned SDK's wrapper during the isolated build, and displayed
connection exceptions use fixed safe wording. Destroying the iframe/WebView also
destroys the SDK's module-level auth cache. Before importing the SDK, both storage
APIs are shadowed with memory-only stores in the viewer document; AWS's settings
and data caches cannot persist to the device or change the parent app's login.
The native viewer is incognito, blocks
navigation outside its exact shell URL, and does not share device cookies.

Remember login is unchecked each time the dialog opens. It saves only after an
explicit Resume. Disconnect and Forget require confirmation; Forget removes this
bot's saved profile and closes its session, not another bot's login. The backend
label is displayed verbatim so users can identify their private context.

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
