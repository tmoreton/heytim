# FroggyBot app

This Expo SDK 57 project powers the iOS client and the matching desktop web app at `app.froggybot.com`. A responsive local preview is available through an explicit development build and is excluded from production bundles. The separate
`services/froggybot-api` package owns the Amplify Gen 2 backend. On Apple devices, the composer also supports on-device dictation.

Each FroggyBot can also own hourly, daily, weekday, weekly, or monthly tasks. EventBridge Scheduler starts the selected bot through the
same durable agent queue, so the task uses the bot's current prompt, tools, skills, memory, chat history, and final-only
notification flow. Tasks can be paused, edited, run immediately for testing, or deleted without removing past replies.

Groups can include several people and several FroggyBots. Invite links grant access to the live room, each message shows
whether it came from a person or a bot, and the sender can keep a message human-only, choose one bot, or run an ordered
team round. Every bot receives the group roster and shared transcript; later bots build on replies already made.
The first bot coordinates the round and returns after the specialist turns with one final team answer.
Each group also has an owner-editable pinned notebook and its own isolated AgentCore memory actor. Bots recall
group preferences, facts, and summaries inside that room, but private user preferences and direct-chat summaries are never copied
into the group. Group members can review learned memory, while only the owner can add, correct, or forget it.

## Run the interface locally

```bash
npm install
npm run ios:preview
```

Choose **Preview the app** when AWS has not been connected yet. Normal `start`, `ios`, `android`, `web`, and production build commands omit the local preview engine; use the corresponding `:preview` command only for interface development.

For web development, install the separately built viewer once with `npm install --prefix ../froggybot-browser-viewer`. The Expo web build compiles that app and copies only its static output into `public/`.

## Connect AWS

Deploy the AgentCore runtime first. The backend writes the Expo runtime configuration into this directory. From the repository root:

```bash
cd services/froggybot-api
npm install
export FROGBOT_AGENT_RUNTIME_ARN='arn:aws:bedrock-agentcore:us-east-1:ACCOUNT_ID:runtime/RUNTIME_ID'
export FROGBOT_MEMORY_ID='FrogBot_FrogBotMemory-ID'
export FROGBOT_GOOGLE_OAUTH_SECRET_ARN='arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:frogbot/oauth/google-ID'
npm run sandbox -- --once --identifier frogbot --profile YOUR_AWS_PROFILE
```

The sandbox replaces the placeholder values in `amplify_outputs.json`. See the repository-level
`README.md` for the complete deployment order and checks. Run Expo and EAS commands here; run backend commands from
`services/froggybot-api`.

Reply notifications use Expo Push Notifications. The app registers each signed-in physical device with the
authenticated API, and the worker checks delivery receipts and removes stale tokens. On Apple devices, dictation uses
the bundled NVIDIA Nemotron 3.5 ASR Streaming 0.6B model through sherpa-onnx. FroggyBot does not save the recording or
fall back to cloud transcription.

## Run the iOS app on an Apple silicon Mac

The existing iOS app can run in macOS's **Designed for iPad** compatibility mode. This is the quickest desktop build:
it reuses the iOS Expo bridge and the same bundled Nemotron model rather than introducing a separate macOS UI target.

```bash
npm run ios:mac
```

The command prepares the native model, creates or refreshes the generated iOS workspace, opens Xcode, and starts
Metro. In Xcode, select **My Mac (Designed for iPad)** as the run destination and click **Run**. Xcode remembers the
destination for later runs. Expo's `run:ios` device picker does not currently expose this Mac compatibility
destination, so the final Run action must be performed in Xcode during development.

This produces a mobile-compatible Mac window, not a native AppKit application. A distributed build is installed from
the iOS App Store/TestFlight with Mac availability enabled. The app and Nemotron model run locally on Apple silicon;
web and Android continue to report local dictation as unavailable.

## Publish over-the-air updates

Production builds listen to the EAS Update `production` channel and use Expo's fingerprint runtime policy so an
update is never sent to a binary with incompatible native code. Every push to `main` runs
`.github/workflows/eas-update.yml`, including pull-request merges, and publishes the JavaScript and asset changes.
The repository keeps the required Expo access token in the `EXPO_TOKEN` GitHub Actions secret. The marketing
homepage, public skill library, legal pages, and contribution guide live in the separate
[`frogbot-skills`](https://github.com/tmoreton/frogbot-skills) repository and publish independently with GitHub Pages.

For an intentional manual update:

```bash
eas update --channel production --environment production --message "Describe the change" --non-interactive
```

Native dependency, permission, or configuration changes still require a new App Store build. Ordinary interface,
copy, and application-logic changes can ship over the air.

## Build iOS

The app is linked to the `@reactnativenerd/frogbot` EAS project. Use the simulator profile for an
unsigned installable test build, or production for an App Store archive:

```bash
nvm use
EAS_PROJECT_ROOT="$(cd ../.. && pwd)" EAS_NO_VCS=1 npx eas-cli@latest build --platform ios --profile preview-simulator
EAS_PROJECT_ROOT="$(cd ../.. && pwd)" EAS_NO_VCS=1 npx eas-cli@latest build --platform ios --profile production
```

`EAS_PROJECT_ROOT` includes the source-only workspace packages that the app consumes. The repository-level
`.easignore` keeps infrastructure, backend code, caches, and generated native artifacts out of the upload.
Push notifications and dictation require a development or production build on a physical Apple device, or the iOS
app running in Designed for iPad mode on an Apple silicon Mac. They do not run in Expo Go or the web preview.

## Verify changes

```bash
npm run verify
npm run build:web
```

The first command checks the app, Amplify infrastructure, backend unit tests, and Expo project health.
