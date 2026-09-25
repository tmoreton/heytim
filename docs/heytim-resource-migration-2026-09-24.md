# HeyTim production resource migration

Date: 2026-09-24

## Objective

Move production-facing AWS resource identities from the legacy FrogBot names to HeyTim without losing customer data, bot history, files, OAuth grants, signing configuration, or a working rollback path.

## Pre-cutover inventory

- AWS account: `188757775631`, region: `us-east-1`
- AgentCore stack: `AgentCore-FrogBot-production`
- AgentCore runtime: `FrogBotProduction_FrogBot-WAhqXM7v63`
- AgentCore memory: `FrogBotProduction_FrogBotMemory-FWrlGD61iY`
- Application data table: `amplify-d1tu46ki1836w1-main-branch-6ca713cbb2-FrogBotAppE7B48881-JFCXVU7AR8CZ-Data666C94C7-11QZBY5HST87M`
  - 580 items and 962,584 bytes at inventory time
- User files bucket: `frogbot-production-user-files-188757775631-us-east-1`
  - versioning enabled
  - 249 current objects and approximately 62.1 MiB at inventory time
- Cognito user pool: `us-east-1_N22obdhLi` (`FrogBotEmailUserPool-zoTVUvkMT1vr`)
  - deletion protection active
  - one registered user at inventory time
- OAuth provider and user-grant secrets existed in both legacy `frogbot/...` and current `heytim/...` namespaces.

## Backup and rollback boundary

- DynamoDB on-demand backup: `heytim-pre-resource-migration-20260924`
- Backup ARN: `arn:aws:dynamodb:us-east-1:188757775631:table/amplify-d1tu46ki1836w1-main-branch-6ca713cbb2-FrogBotAppE7B48881-JFCXVU7AR8CZ-Data666C94C7-11QZBY5HST87M/backup/01790299270512-a1b8a7ce`
- The original AgentCore stack, memory, S3 bucket, Cognito pool, KMS keys, and Secrets Manager entries must remain intact until the HeyTim runtime and application smoke tests pass.
- A rollback switches the API and worker environment back to the recorded FrogBot runtime, memory, and file bucket. Connection records can be restored from the DynamoDB backup or conditionally pointed at the retained legacy secrets.
- No retained legacy resource may be deleted in the same deployment that first cuts production traffic over to its HeyTim replacement.

## Migration sequence

1. Deploy a parallel `AgentCore-HeyTim-production` stack with the `HeyTim` runtime, `HeyTimMemory`, `HeyTimTools`, HeyTim credential providers, evaluator, and online evaluation resources.
2. Copy AgentCore memory actors, sessions, and events to `HeyTimMemory`; compare actor/session/event counts before cutover.
3. Verify the HeyTim runtime directly, including chat, Gmail, Google Workspace failure isolation, browser/search tools, and scheduled-bot execution.
4. Provision the versioned HeyTim file bucket and KMS alias, copy all object versions needed by the application, compare object counts and bytes, then update stored attachment references.
5. Deploy the API and worker with the new runtime ARN, memory ID, gateway ID, credential provider names, and file bucket. Keep database and Cognito identities stable during this cutover so existing sessions and ownership keys continue to work.
6. Verify iOS and macOS together, then run authenticated API, email reply, tool, bot, attachment, and scheduled-run smoke tests.
7. Migrate the DynamoDB table and Cognito pool only as a separate identity/data cutover. Cognito passwords are not exportable, so this phase requires an explicit user migration or sign-in reset plan and ownership-key rewrite before the old pool can be retired.
8. After an observation window, remove legacy IAM access, archive retained resources, and delete only resources whose HeyTim replacements and backups have been verified.

## Signing and release checks

- Preserve the current Apple bundle identifiers, App Store Connect records, certificates, profiles, APNs topics, and keychain groups. Product display naming does not require replacing those signing identities.
- Run `./scripts/apple-app.sh verify` for both iOS and macOS before a release.
- Verify APNs production and sandbox delivery after the backend cutover.

## Completion criteria

- New resources expose only HeyTim product names and `heytim/...` secret namespaces.
- Existing user, bots, conversations, schedules, email threads, tool settings, OAuth connections, files, and memory remain usable.
- Healthy tools still load when an unrelated connection has expired credentials.
- Direct runtime, backend, email, authenticated app, iOS, and macOS checks pass.
- Legacy resources remain recoverable until the final cleanup review.
