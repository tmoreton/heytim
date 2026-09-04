# FrogBot mobile app

This Expo SDK 57 app is the iOS-first FrogBot client. It includes a responsive local preview and an
Amplify Gen 2 backend for native Cognito SMS OTP authentication, persisted chats, bot configuration, and sharing.

## Run the interface locally

```bash
npm install
npm run ios
```

Choose **Preview the app** when AWS has not been connected yet.

## Connect AWS

Deploy the AgentCore runtime first. Cognito uses AWS End User Messaging SMS to deliver phone codes, so configure
an origination identity, verify test destinations while sandboxed, and request production access before launch.
Then deploy:

```bash
nvm use
npm run backend:install
export FROGBOT_AGENT_RUNTIME_ARN='arn:aws:bedrock-agentcore:us-east-1:ACCOUNT_ID:runtime/RUNTIME_ID'
npm run sandbox -- --once --identifier frogbot --profile YOUR_AWS_PROFILE
```

The sandbox replaces the placeholder values in `amplify_outputs.json`. See the repository-level
`README.md` for the complete deployment order and checks.

## Build iOS

The app is linked to the `@reactnativenerd/frogbot` EAS project. Use the simulator profile for an
unsigned installable test build, or production for an App Store archive:

```bash
nvm use
EAS_PROJECT_ROOT="$PWD" EAS_NO_VCS=1 npx eas-cli@latest build --platform ios --profile preview-simulator
EAS_PROJECT_ROOT="$PWD" EAS_NO_VCS=1 npx eas-cli@latest build --platform ios --profile production
```

`EAS_PROJECT_ROOT` keeps the upload scoped to this app when FrogBot lives inside a larger Git repository.
