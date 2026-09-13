# FroggyBot for Apple

This is the native SwiftUI client for iPhone and macOS. It lives alongside the Expo app and uses the same Cognito account, HTTP API, data, bots, groups, schedules, skills, connections, files, and browser sessions.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the code-sharing boundary, backend-first decisions, feature surface, and verification model. The native-first Apple design direction and the small set of FroggyBot brand elements shared with Expo are recorded in [DESIGN_PARITY.md](DESIGN_PARITY.md).

The app is one multiplatform Xcode target. Shared models, state, networking, and SwiftUI views compile for both Apple platforms; small adapters handle application lifecycle, notifications, secure storage, file picking, windows, and web views. The existing Expo app remains the web client because SwiftUI does not provide a supported browser target.

## Open and run

Open `FroggyBotApple.xcodeproj`, select the `FroggyBotApple` scheme, and choose either an iPhone simulator or My Mac. The minimum versions are iOS 17 and macOS 14.

On a fresh checkout, prepare the checksum-pinned transcription frameworks and model first:

```bash
./scripts/prepare-transcription.sh
```

The checked-in project is generated deterministically. After adding or removing a Swift source file, regenerate it with:

```bash
GEM_HOME=/opt/homebrew/Cellar/cocoapods/1.17.0/libexec ruby scripts/generate-project.rb
```

The generator uses the `xcodeproj` Ruby gem bundled with Homebrew CocoaPods. Ordinary Xcode use does not require Ruby or CocoaPods.

## Configuration and release setup

Run `npm run outputs:apple` in `services/froggybot-api` whenever Amplify produces a new `apps/froggybot/amplify_outputs.json`. The Apple copy contains public client configuration only.

Before installing on physical devices or distributing the app:

1. Select the Apple Developer team for the app target.
2. Register `com.frogbot.app` for iOS and macOS with Push Notifications enabled.
3. Use the included development APNs entitlements for Debug and production entitlements for Release.
4. Configure the matching SNS platform application ARNs in the backend environment.
5. Capture App Store screenshots before archive submission; the shared FrogBot icon is already configured for both platforms.

No Apple signing key belongs in source control.

## Verification

```bash
./scripts/verify.sh
```

Verification builds the same target for Mac and iPhone, runs unit tests, runs the iPhone UI launch/send smoke test, and runs the existing on-device transcription package tests. UI tests use `--ui-testing`, which never contacts AWS or alters real user data.
