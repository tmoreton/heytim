# Apple client architecture

## Decision

FroggyBot for Apple is one SwiftUI application target with iPhone and macOS destinations. Models, authentication, API access, state, navigation, feature screens, on-device transcription, and tests are shared. The only platform-specific code is the small adapter layer for application lifecycle, notification registration, files, external URLs, and `WKWebView`.

The Expo application remains unchanged and continues to own the browser build. SwiftUI has no supported web deployment target, so attempting to make the SwiftUI view tree the web client would replace a supported product with a compatibility experiment. Both clients instead share the server API and generated route contract.

## Backend boundary

The server is the source of truth for permissions, constraints, bot/group state, message orchestration, schedules, memory, skills, sharing, OAuth connections, private browser sessions, file tickets, invitations, account deletion, and notification delivery. Those rules should not be reimplemented in either client.

Two client-neutral pieces were added during the Apple conversion:

- The existing API contract generator now emits both TypeScript and Swift route maps. Either generated file drifting from `api-contract.json` fails verification.
- Push registrations now carry a provider. Existing Expo tokens retain their original delivery path, while Apple device tokens are converted to Amazon SNS endpoints and delivered through APNs. Ownership, expiry, deduplication, invalid-token cleanup, and least-privilege IAM remain server-side.

Public Cognito and API configuration is synchronized from Amplify output with `npm run outputs:apple`. Secrets and Apple signing credentials are never copied into the app.

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
