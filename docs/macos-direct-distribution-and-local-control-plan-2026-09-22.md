# macOS direct distribution and local control plan

Date: 2026-09-22

## Decision

HeyTim's iPhone app remains an App Store/TestFlight product. The Mac app moves to a
Developer ID signed, Apple-notarized direct download. This is a deliberate platform
split: a general Mac accessibility controller cannot run inside the App Sandbox,
while the iPhone app should retain its existing sandbox and store distribution.

The first Mac release uses Laya as a local, advisory decision router in the chat
send path. Mac app access is enabled in Settings and shown as an inline review
card only after an explicit Mac-app request, not a separate window or composer
button. When that route is offered, Laya receives a
bounded semantic accessibility snapshot and chooses between known visible
controls or `use_cloud_model`. It does not generate clicks, coordinates, text,
or permissions. HeyTim remains the policy authority.

## Safety invariants

- Accessibility access is opt-in through macOS and can be checked or requested from
  Hey Tim Settings. The in-app capability is off by default and can be disabled
  independently of the macOS permission. Returning from System Settings refreshes
  status and offers to quit and reopen after a permission request, even when
  macOS already reports access as granted.
- Secure text fields and arbitrary field values are never included in model state.
- The accessibility walk has fixed depth, element, string, and action limits.
- Every control is resolved to an in-memory accessibility element from the current
  snapshot; the model cannot invent an element or application identifier.
- Send, submit, purchase, delete, publish, share, install, permission, and similar
  high-impact controls always escalate and cannot be pressed by the local route.
- A safe Laya result is still a preview. A person must approve the exact app and
  control before HeyTim invokes the accessibility action.
- Low confidence, truncation, model errors, and missing assets all fail closed to
  the larger model.
- A local preflight may suggest the Mac action in any conversation, but cannot
  silently suppress a bot turn. A user can always send the draft to the bot.
- The bundled multilingual base checkpoint is not yet validated for general tool
  routing. Its own [model card](https://huggingface.co/convaiinnovations/laya)
  warns of weak zero-shot performance on typed-decision tasks. Calibration and a
  held-out HeyTim dataset are required before direct tool execution can ship.
- The model is bundled into the Mac app from an immutable revision. The build
  verifies every asset's pinned size and SHA-256 digest before packaging it.

## Delivery phases

### 1. Distribution boundary

- Keep the shared SwiftUI target and iOS entitlements.
- Build macOS without the App Sandbox and with the hardened runtime.
- Remove macOS from the TestFlight scripts and production upload path.
- Add a Developer ID archive/export, notarization, stapling, and
  drag-to-Applications DMG pipeline, with a separate ZIP for Sparkle updates.
- Preserve the existing `ai.heytim.app` identity and other deployed identifiers.

Acceptance: iOS archives for TestFlight, macOS exports as a Developer ID app, both
destinations pass the shared Apple build and verification gates.

### 2. Sparkle 2

- Pin Sparkle 2.10.0 for macOS only.
- Add a Mac-only update controller and **Check for Updates…** command.
- Require an HTTPS appcast and EdDSA public key in release builds.
- Generate a signed appcast beside the notarized ZIP and publish both as immutable
  GitHub Release assets.

Acceptance: a release build refuses packaging without update configuration; a
signed older build can discover, verify, install, and relaunch into a newer build.

### 3. Local desktop decisions

- Pin FluidUse to commit `e9e95935075b626a203bb20c0645975be23f15b1` and the
  Laya Core ML assets to revision
  `7b8d7a2b7e28e746c6ecaad44bbcd5cf251a4fcc`.
- Bundle only the multilingual int8 128-token bucket for the initial release.
- Add an accessibility inspector, bounded action catalog, Laya decision adapter,
  risk classifier, preview, and explicit execution control.
- Keep `use_cloud_model` as an ordinary candidate and the universal fallback.

Acceptance: with Accessibility permission, a user can ask for a Mac app action in
any conversation, select a running app, inspect the captured
controls, receive a local recommendation, and approve a safe button press. Risky
or uncertain actions do not execute. The conversation draft remains available
for ordinary bot send. Mac text sends run an advisory Laya preflight first; only
an explicit Mac UI request with a strong model result offers the local action.
Attachments bypass this text-only preflight. `use_cloud_model` currently means a
safe handoff indication, not an automatic invocation of the remote agent.

### 4. Integration and calibration

- Record opt-in, privacy-preserving decision telemetry: route, latency, confidence,
  fallback reason, and whether the recommendation was accepted. Never record UI
  values or the raw accessibility snapshot.
- Build a reviewed desktop task dataset, fine-tune/calibrate Laya for HeyTim's
  action taxonomy, and compare it with deterministic and cloud baselines.
- Connect cloud fallback through a signed, expiry-bounded action proposal returned
  to the same local approval surface.
- Expand beyond button presses only after per-action policy and end-to-end tests.

Home Assistant is the first non-desktop fast-path candidate. The offline fixture
in `apps/iOS/scripts/evaluate-laya-home.sh` uses the packaged Core ML checkpoint
and five synthetic requests. On 2026-09-22, the model selected the correct
turn-on and turn-off actions and correctly sent an out-of-scope weather question
to the main model. It incorrectly selected `turn_on` for a read-state question,
but its confidence was 0.415, below the fixture's 0.75 action gate. A bedroom
status question also fell back to the main model. This is a useful safety test,
not evidence of general accuracy.

The ordinary Home Assistant integration is restored separately from that
experimental fast path. It is a user-scoped Assist MCP connection, configured
with a public HTTPS instance URL and a long-lived token stored in Secrets
Manager. It appears under Connectable Tools and can be assigned to selected
bots. Runtime access is limited to `/api/mcp/assist`, Home Assistant's exposed
Assist entities, and HeyTim's exact-action approval. A private LAN-only URL
cannot be reached by the server. This restores the regular bot tool path, not
Laya-driven automatic execution.

Before a real Home Assistant fast path can bypass the main model, implement a
server-side tool broker. Home Assistant credentials and MCP connections remain
on the server; the Mac app must never receive them. The broker must return a
bounded catalog of permitted tool choices and exact entity IDs, validate the
selected tool and arguments against the bot's grants, require approval for
state-changing actions, execute only one idempotent bounded call, and persist its
result as a conversation turn. Unknown devices, ambiguous language, low scores,
or unavailable connections go to the main model. Add replay fixtures and
end-to-end tests before enabling the broker in production.

Acceptance: the local route meets agreed accuracy and false-action limits on a
held-out set before it can become the default fast path.

## Release configuration

The direct Mac pipeline requires:

- Developer ID Application certificate and password;
- Sparkle EdDSA private key for appcast signing;
- matching Sparkle public key stored as a non-secret Xcode build setting; and
- an HTTPS feed URL (the default points at the latest GitHub Release appcast).

Local notarization can use a validated `notarytool` Keychain profile via
`NOTARY_KEYCHAIN_PROFILE`; CI can use a team App Store Connect API key. The
Sparkle private key must never be committed or written to a release artifact.
