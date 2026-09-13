# FroggyBot application backend

This service owns the Amplify Gen 2 application backend: Cognito, the HTTP API, persistence, queues, schedules, workers, and operational tests. It is deployed independently from the clients. The primary SwiftUI app and preserved Expo browser client use the same API contract and AWS resources.

```bash
npm install
npm run contract:generate
npm run outputs:apple
npm run verify
npm run sandbox -- --once --identifier frogbot --profile YOUR_AWS_PROFILE
```

Run commands from this directory. Resource construct names in `amplify/backend.ts` are stable deployment identities and must not be renamed as part of source reorganizations.

`contract:generate` emits both the TypeScript route map and the Swift route map. `outputs:apple` copies only public Cognito/API configuration from the generated Amplify browser-client output into the Apple app; it deliberately excludes infrastructure names and ARNs.

## Native Apple notifications

Create production and sandbox APNs platform applications in Amazon SNS using the Apple signing key owned by the release account. Set their ARNs as `FROGBOT_APNS_APPLICATION_ARN` and `FROGBOT_APNS_SANDBOX_APPLICATION_ARN` before the Amplify deployment. The API then creates per-device endpoints and the worker delivers directly through SNS. Existing Expo registrations continue to work unchanged.

Local Amplify sandboxes default to same-account SNS platform applications named `FroggyBot` when those variables are omitted. This keeps repeated sandbox deployments from silently removing native notification delivery. Set the variables explicitly when an account uses different application names; production still requires the production ARN.

Never store an Apple `.p8` key, APNs token, or signing certificate in this repository. CI should supply the two platform application ARNs as environment variables.
