# FroggyBot for Apple

This is FroggyBot's primary client and the only supported source for iPhone and Mac builds. The single native SwiftUI target uses the same Cognito account, HTTP API, data, bots, groups, schedules, skills, connections, files, and browser sessions on both platforms. The Expo application is archived outside the repository; `apps/website` is the public marketing site and skills library.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the code-sharing boundary, backend-first decisions, feature surface, and verification model. The native-first Apple design direction and the small set of FroggyBot brand elements shared with Expo are recorded in [DESIGN_PARITY.md](DESIGN_PARITY.md).

The app is one multiplatform Xcode target. Shared models, state, networking, and SwiftUI views compile for both Apple platforms; small adapters handle application lifecycle, notifications, secure storage, file picking, windows, and web views. The folder is named `iOS` but still includes the native macOS app.

## Open and run

From the repository root, use the supported entry point for a repeatable build and launch:

```bash
./scripts/apple-app.sh run ios
./scripts/apple-app.sh run macos
```

Use `build` instead of `run` to compile without launching, or `./scripts/apple-app.sh open` to open `FroggyBotApple.xcodeproj` in Xcode. Select the `FroggyBotApple` scheme and choose either an iPhone simulator or My Mac. The minimum versions are iOS 17 and macOS 14.

The root build commands prepare the checksum-pinned transcription frameworks and model automatically. To prepare
them without building:

```bash
./apps/iOS/scripts/prepare-transcription.sh
```

The Xcode project is generated from its checked-in Ruby definition. After adding or removing a Swift source file,
regenerate it from the repository root with:

```bash
GEM_HOME=/opt/homebrew/Cellar/cocoapods/1.17.0/libexec ruby apps/iOS/scripts/generate-project.rb
```

The generator uses the `xcodeproj` Ruby gem bundled with Homebrew CocoaPods. Ordinary Xcode use does not require Ruby or CocoaPods.

## Configuration and release setup

Run `npm --prefix services/API run outputs:apple` whenever Amplify produces a new
`services/API/amplify_outputs.json`. The Apple copy contains public client configuration only. Before external
TestFlight or App Store distribution, confirm that the source file came from the production Amplify deployment and
run the sync command. The TestFlight script runs `outputs:apple:production:check` automatically and refuses sandbox,
stale, or unknown outputs. Download the production client-configuration artifact from the successful production
release workflow before creating the archive.

Before installing on physical devices or distributing the app:

1. Select the Apple Developer team for the app target.
2. Register `com.frogbot.app` for iOS and macOS with Push Notifications enabled.
3. Use the included development APNs entitlements for Debug and production entitlements for Release.
4. Configure the matching SNS platform application ARNs in the backend environment.
5. Capture App Store screenshots before archive submission; the shared FrogBot icon is already configured for both platforms.

No Apple signing key belongs in source control.

From the repository root, create a signed SwiftUI archive with an explicit Apple Developer team:

```bash
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh archive ios
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh archive macos
```

The script gives each archive a UTC timestamp build number, prepares the transcription dependencies, and writes the result under the ignored `Archives/` directory. It deliberately does not upload. To supply a known build number instead:

```bash
APPLE_TEAM_ID=YOURTEAMID FROGGYBOT_BUILD_NUMBER=202609130200 ./scripts/apple-app.sh archive ios
```

To archive and upload directly for TestFlight processing:

```bash
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh testflight ios
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh testflight macos
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh testflight all
```

The TestFlight entry point requires a clean working tree except for the two generated production output files, checks
the bundled public backend configuration, and runs the shared iPhone/Mac verification suite before archiving. The
`all` form verifies once and uploads matching iPhone and Mac builds with the same build number. The manual production
workflow uses this path after its backend deployment succeeds; its signing material is injected from the protected
GitHub production environment and removed from the runner afterward. Local runs use the developer account signed
into Xcode by default. Publishing a stable GitHub Release tagged `vMAJOR.MINOR.PATCH` deploys the backend and runs
this same TestFlight path automatically. The tag sets `MARKETING_VERSION` for both archives, while a single numeric
build number is shared by the iPhone and Mac builds. The tag must point to a commit on `main`.
For unattended uploads, set `APP_STORE_CONNECT_KEY_PATH`, `APP_STORE_CONNECT_KEY_ID`, and
`APP_STORE_CONNECT_ISSUER_ID` together; never commit the `.p8` key. Add `--dry-run` before the platform to inspect
the selected archive path and build number without signing or uploading.

## Verification

From the repository root:

```bash
./scripts/apple-app.sh verify
```

Verification builds the same target for Mac and iPhone, runs unit and iPhone UI tests serially on an isolated temporary
simulator, and runs the on-device transcription package tests. UI tests use `--ui-testing`, which never contacts AWS,
alters real user data, or reuses a developer's simulator.

For Mac navigation and resize changes, also run the `FroggyBotAppleUI` scheme on
My Mac with development signing enabled. The Mac tests cover bot/group Details
over the full chat area, a stationary sidebar, actual window and divider drags,
draft preservation, and feature-page dismissal. Do not run Mac UI tests with
`CODE_SIGNING_ALLOWED=NO`: the test runner must be re-signed after Xcode embeds
the test bundle, otherwise macOS rejects it as damaged. The unsigned Mac unit
test host used by the standard verification script is a separate case.

Use an isolated fixture-only bundle identifier while TestFlight is open. This
keeps test launches separate from the installed app. These offline UI builds do
not need push, microphone, or file-access entitlements; the overrides below are
only for UI testing and must not be used for release archives.

```bash
xcodebuild test -project apps/iOS/FroggyBotApple.xcodeproj \
  -scheme FroggyBotAppleUI -destination 'platform=macOS' \
  -parallel-testing-enabled NO \
  -only-testing:FroggyBotAppleUITests/FroggyBotAppleUITests/testMacDetailsCoverChatAndRemainStableWhenResizing \
  -only-testing:FroggyBotAppleUITests/FroggyBotAppleUITests/testMacFeaturePagesCoverChatWithoutMovingSidebar \
  -only-testing:FroggyBotAppleUITests/FroggyBotAppleUITests/testMacSavingRootBotEditorReturnsToChat \
  DEVELOPMENT_TEAM="$APPLE_TEAM_ID" CODE_SIGN_STYLE=Automatic \
  CODE_SIGN_IDENTITY='Apple Development' \
  PRODUCT_BUNDLE_IDENTIFIER=com.frogbot.app.uitesting CODE_SIGN_ENTITLEMENTS=
```
