# macOS direct distribution and local control plan

> Historical design note: the Laya model, its Home Assistant fast path, and
> the evaluation scripts mentioned below have since been removed. Current
> Home Assistant Assist access uses an assigned MCP connection.

Date: 2026-09-22

## Decision

HeyTim's iPhone app remains an App Store/TestFlight product. The Mac app moves to a
Developer ID signed, Apple-notarized direct download. This is a deliberate platform
split: a general Mac accessibility controller cannot run inside the App Sandbox,
while the iPhone app should retain its existing sandbox and store distribution.

The current Mac implementation uses Laya only as a local, advisory matcher when
an explicit click/press request names an app but no visible control has an exact
label match. It is not a general message router. There is one global
Settings switch and a per-bot toggle in the existing Tools & Skills list. An
eligible action stays in the conversation, not a separate window, card, or
composer button. An exact low-risk navigation match or explicit note with known
text can execute immediately; other proposals use the normal approval bubble.
For eligible button actions, Laya
receives only the request and at most four filtered button labels, and chooses
between those known controls or `main_model`. It does not generate clicks, coordinates, text,
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
- A Laya-only result is still a preview requiring approval. Model confidence
  alone never authorizes execution. Only exact, unique, low-risk matches may
  execute immediately, after rechecking the live accessibility element.
- Low confidence, truncation, model errors, and missing assets all fail closed to
  the larger model.
- A local preflight runs only for explicit click/press messages to a direct bot
  with its Mac tool on, and only after an exact-match lookup fails.
  Unclear or unavailable app actions fall through to the ordinary bot turn.
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

Acceptance: with Accessibility permission and a bot's tool toggle on, a user
can ask that bot for an explicit Mac app action. Exact low-risk actions run in
the normal chat flow without another click; uncertain actions use the existing
approval surface. A narrow Apple Notes case can create a note with exact
user-specified text; other supported actions are visible button presses.
Risky or uncertain actions do not execute. Exact Apple Notes requests do not
need a model. Attachments bypass the text-only preflight. `main_model` means no
local action is proposed; it does not bypass the bot's normal tool grants.

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
status question also fell back to the main model. The rerun with the bundled
model selected the same routes and passed all five offline fixtures. This is a useful safety test,
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
