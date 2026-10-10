# HeyTim secure browser viewer

The native app loads the static viewer, then injects a short-lived AWS capability
through `window.heytimSetBrowserSession(url, width, height)`. Capabilities stay in
memory. The viewer connects using the DCV SDK bundled with pinned
`bedrock-agentcore`; it does not own the remote browser, saved login, or bot turn.

A connection is ready only after DCV's `firstFrame` callback. Authentication,
connection, disconnect, and startup timeout errors show a recovery control and
send a sanitized status to the native app. Reconnect requests a fresh capability
from HeyTim. Disconnecting the viewer preserves the remote page and login.

The decoder base URL must be absolute at the app origin's
`/nice-dcv-web-client-sdk/dcvjs-esm` path. Pages publishes those assets alongside
`/browser-viewer/`. Do not log SDK errors, authentication tokens, or signed URLs.
See the [AWS connection API](https://docs.aws.amazon.com/dcv/latest/websdkguide/establish-connection.html).

## Verification

- `npm ci && npm run verify`: connection failure/lifecycle tests, TypeScript, and production build.
- `npm run test:ui`: headless Chrome checks of real React UI at five viewport sizes,
  light/dark mode, reduced motion, keyboard focus, scaled input, and reconnects.
  Uses the repository's locked Python/Playwright environment through `uv`.
- From the repository root, `HEYTIM_TEST_BROWSER=1 uv run --project services/runtime --frozen pytest -q services/runtime/tests/test_browser_chromium.py`
  exercises the shipped tool against a disposable local Chrome/CDP browser and
  loopback website, including streaming pages, navigation/history, forms, tabs,
  screenshot capture, bad-address recovery, and persistent context across reconnects.

`./scripts/verify.sh application` runs all three checks. Chrome must already be
installed. Test fixtures live under `tests/` and are not in Vite's production build.
They stub the AWS SDK transport or ownership response; passing them does not
verify AWS IAM, signed streaming access, DCV decoding, or native WebKit input.

For an AWS/native release check, use a disposable browser with a public test page,
verify a real first frame and native mouse/touch/keyboard/clipboard behavior,
then test handoff, saved-profile completion, and continuation exactly once.
Deploy the API's optional `profileSavePending` field before releasing native
polling. Clients must never repeat an uncertain continuation enqueue.
