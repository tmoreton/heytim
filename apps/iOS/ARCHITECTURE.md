# Apple client architecture

## Decision

HeyTim for Apple is one SwiftUI application target with iPhone and macOS destinations. Models, authentication, API access, state, navigation, feature screens, on-device transcription, and tests are shared. Platform adapters cover application lifecycle, notifications, files, external URLs, `WKWebView`, read-only HealthKit access on iPhone, and Accessibility plus local Vision OCR on Mac.

The Expo source is preserved and continues to own the browser build, but its native build, submit, and update paths are deprecated and blocked. SwiftUI has no supported web deployment target, so attempting to make the SwiftUI view tree the web client would replace a supported product with a compatibility experiment. Both clients instead share the server API and generated route contract.

## Backend boundary

The server is the source of truth for permissions, constraints, bot/group state, message orchestration, schedules, memory, skills, sharing, OAuth connections, private browser sessions, file tickets, invitations, account deletion, and notification delivery. Those rules should not be reimplemented in either client.

Two client-neutral pieces were added during the Apple conversion:

- The existing API contract generator now emits both TypeScript and Swift route maps. Either generated file drifting from `api-contract.json` fails verification.
- Push registrations now carry a provider. Existing Expo tokens retain their original delivery path, while Apple device tokens are converted to Amazon SNS endpoints and delivered through APNs. Ownership, expiry, deduplication, invalid-token cleanup, and least-privilege IAM remain server-side.

Public Cognito and API configuration is synchronized from Amplify output with `npm run outputs:apple`. Secrets and Apple signing credentials are never copied into the app.

## Device tool boundary

Apple-only capabilities use the same catalog/tool vocabulary as cloud tools, but execute on a currently authorized client:

1. An active app publishes a three-minute capability lease containing its platform, supported operations, and explicit per-bot grants. A lease advertises availability; it is not a durable bearer credential.
2. The worker exposes only the intersection of the bot's catalog tools, the live device manifest, and that bot's local grant.
3. A model tool call interrupts the AgentCore turn. The runtime saves an S3 snapshot and signs the exact tool-use ID, operation, arguments, platform, and tool ID with a digest.
4. The worker binds the request to one live device and marks the turn `AWAITING_DEVICE`. Only the owning account and assigned device ID can retrieve it.
5. The client rechecks its local grant, performs the narrow operation, durably caches the outcome before acknowledgement, and returns the exact digest. This prevents a lost response from repeating a Mac action.
6. The backend conditionally consumes that result once and resumes the same saved turn. Expired, altered, reassigned, or replayed calls fail closed.

Mac control is semantic-first. Accessibility supplies app/window identity, supported control actions, scroll containers, and stable-in-snapshot target IDs; action calls revalidate the process, focused window, target label, enabled state, and 60-second snapshot revision. State waits use Accessibility notifications instead of blind polling. Secure fields and consequential labels are excluded or blocked. Optional ScreenCaptureKit screenshots feed Vision locally only when requested, are held in memory, and are never sent to the server. Every action returns a fresh observation rather than assuming success. Keyboard, mouse, or trackpad input while a snapshot is active pauses computer use, and the user must explicitly resume it in the app.

Website work remains browser-first through AgentCore Browser because structured page state is more reliable than driving a local browser with pixels. The Mac Operator skill uses Accessibility only for native/local surfaces or when browser control is unavailable, treats content inside apps and pages as untrusted, and stops on stale state, takeover, ambiguity, or a consequential control. Arbitrary shortcuts, terminal execution, and unrestricted coordinates are outside this boundary.

iPhone does not attempt general cross-app control. Apple Health is an explicit, read-only adapter with per-bot consent and Apple's per-type authorization. The adapter returns daily or period summaries and deliberately omits routes, clinical records, writes, background delivery, and raw samples.

## Shared Apple surface

The shared target includes:

- invitation-only email OTP authentication, refresh, secure Keychain storage, and token revocation;
- bot and group conversations, group reply targeting, message polling, stop and approval actions, saved decisions, Markdown, attachments, and on-device dictation;
- bot templates/editing, group editing and membership, schedules and run history;
- personal and group memory, skills, OAuth connections, shares, documents, account deletion, and browser handoff;
- native APNs registration and notification routing;
- adaptive `NavigationSplitView` presentation for compact iPhone and wide Mac windows.

## Verification boundary

`scripts/verify.sh apple` prepares the checksum-pinned transcription assets, runs the transcription package tests, builds the Mac destination, and runs the Swift unit and iPhone UI suites. The UI smoke test uses in-memory demo data and cannot contact AWS or mutate customer data.

Release signing and a real APNs delivery test require credentials that intentionally do not live in the repository. The repository includes separate development and production entitlements and accepts the two SNS platform application ARNs through deployment environment variables.
