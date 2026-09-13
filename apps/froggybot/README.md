# FroggyBot browser client and legacy Expo source

This Expo SDK 57 project is deprecated for native application development. Its source is intentionally preserved as
FroggyBot's browser client at `app.froggybot.com` and as a migration reference. All supported iPhone and Mac builds,
archives, and TestFlight uploads now come from `apps/froggybot-apple`. Native EAS builds are deliberately blocked and
the production workflow no longer publishes Expo over-the-air updates.

The separate `services/froggybot-api` package owns the Amplify Gen 2 backend shared by the browser and SwiftUI clients.

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

## Run the browser interface locally

```bash
npm install
npm run web:preview
```

Choose **Preview the app** when AWS has not been connected yet. Normal `start`, `web`, and production web builds omit
the local preview engine. `npm run ios` and `npm run ios:mac` intentionally hand off to the primary SwiftUI app.

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

The sandbox replaces the placeholder values in `amplify_outputs.json`. See the repository-level `README.md` for the
complete deployment order and checks. Run browser npm/EAS Deploy commands here; run backend commands from
`services/froggybot-api` and all Apple build commands from the repository root.

The preserved native implementation used Expo Push Notifications and bundled on-device dictation. The primary SwiftUI
app registers directly for APNs through Amazon SNS and owns current Apple notification and transcription behavior.

## Deprecated native source

The old iOS, Designed-for-iPad Mac, and Android implementation remains in this directory so history can be inspected
and behavior can be compared during migration. Its commands are explicit: `legacy:ios`, `legacy:ios:preview`,
`legacy:ios:native`, `legacy:ios:mac`, and `legacy:android`. They are unsupported reference paths, not release paths.

EAS native build profiles are archived by name, the native build hook rejects them, the submit profile was removed,
and the main-branch workflow no longer publishes EAS Update. This keeps an accidental Expo binary or JavaScript update
from becoming a new Apple release while preserving every source file.

For supported Apple work, run these from the repository root:

```bash
./scripts/apple-app.sh run ios
./scripts/apple-app.sh run macos
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh testflight ios
APPLE_TEAM_ID=YOURTEAMID ./scripts/apple-app.sh testflight macos
```

## Publish the browser client

Every push to `main` verifies this preserved code and uses EAS Deploy for the static browser app only. It does not
build, submit, or update a native Expo app. For an intentional manual browser deployment, use `npm run deploy:web`.
The marketing homepage, public skill library, legal pages, and contribution guide live in the separate
[`frogbot-skills`](https://github.com/tmoreton/frogbot-skills) repository and publish independently with GitHub Pages.

## Verify changes

```bash
npm run verify
npm run build:web
```

These commands check the preserved view boundary, tests, types, lint, Expo project health, browser viewer, and static
web export. Run `./scripts/apple-app.sh verify` from the repository root for the primary iPhone and Mac client.
