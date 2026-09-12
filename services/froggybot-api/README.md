# FroggyBot application backend

This service owns the Amplify Gen 2 application backend: Cognito, the HTTP API, persistence, queues, schedules, workers, and operational tests. It is deployed independently from the Expo view application while writing the generated `amplify_outputs.json` runtime configuration back to `apps/froggybot`.

```bash
npm install
npm run contract:generate
npm run verify
npm run sandbox -- --once --identifier frogbot --profile YOUR_AWS_PROFILE
```

Run commands from this directory. Resource construct names in `amplify/backend.ts` are stable deployment identities and must not be renamed as part of source reorganizations.
