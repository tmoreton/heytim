# FroggyBot mobile app

This Expo SDK 57 app is the iOS-first FroggyBot client. It includes a responsive local preview and an
Amplify Gen 2 backend for native Cognito email OTP authentication, persisted direct and group chats, bot configuration, sharing,
and push notifications when an agent reply is ready. On Apple devices, the composer also supports on-device dictation.

Each FroggyBot can also own simple daily or weekly tasks. EventBridge Scheduler starts the selected bot through the
same durable agent queue, so the task uses the bot's current prompt, tools, skills, memory, chat history, and final-only
notification flow. Tasks can be paused, edited, run immediately for testing, or deleted without removing past replies.

Groups can include several people and several FroggyBots. Invite links grant access to the live room, each message shows
whether it came from a person or a bot, and the sender can keep a message human-only, choose one bot, or run an ordered
team round. Every bot receives the group roster and shared transcript; later bots build on replies already made.
The first bot coordinates the round and returns after the specialist turns with one final team answer.

## Run the interface locally

```bash
npm install
npm run ios
```

Choose **Preview the app** when AWS has not been connected yet.

## Connect AWS

Deploy the AgentCore runtime first. FroggyBot currently uses Cognito email codes so TestFlight users can sign in while
the registered AWS toll-free SMS sender is under carrier review.
Then deploy:

```bash
nvm use
npm run backend:install
export FROGBOT_AGENT_RUNTIME_ARN='arn:aws:bedrock-agentcore:us-east-1:ACCOUNT_ID:runtime/RUNTIME_ID'
npm run sandbox -- --once --identifier frogbot --profile YOUR_AWS_PROFILE
```

The sandbox replaces the placeholder values in `amplify_outputs.json`. See the repository-level
`README.md` for the complete deployment order and checks. Run all Expo, EAS, Amplify, and npm commands
from this `apps/froggybot` directory.

Reply notifications use Expo Push Notifications. The app registers each signed-in physical device with the
authenticated API, and the worker checks delivery receipts and removes stale tokens. The microphone uses Apple's
on-device Speech framework with `requiresOnDeviceRecognition`; FroggyBot does not save the recording or fall back to
cloud transcription.

## Publish over-the-air updates

Production builds listen to the EAS Update `production` channel and use Expo's fingerprint runtime policy so an
update is never sent to a binary with incompatible native code. Every push to `main` runs
`.github/workflows/eas-update.yml`, including pull-request merges, and publishes the JavaScript and asset changes.
The repository keeps the required Expo access token in the `EXPO_TOKEN` GitHub Actions secret.

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
EAS_PROJECT_ROOT="$PWD" EAS_NO_VCS=1 npx eas-cli@latest build --platform ios --profile preview-simulator
EAS_PROJECT_ROOT="$PWD" EAS_NO_VCS=1 npx eas-cli@latest build --platform ios --profile production
```

`EAS_PROJECT_ROOT` keeps the upload scoped to this app when FroggyBot lives inside a larger Git repository.
Push notifications and dictation require a development or production build on a physical device and do not run in
Expo Go or the web preview.

## Verify changes

```bash
npm run verify
npm run build:web
```

The first command checks the app, Amplify infrastructure, backend unit tests, and Expo project health.
