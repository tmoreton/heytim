# FroggyBot production release gate

The repository is release-hardened, but a production release is not complete merely because the code passes locally.
The configured AWS account, third-party approvals, monitored alert destination, device evidence, and controlled
deployment are external release inputs. The manual **Deploy FroggyBot production release** workflow fails closed until
they are present. Production temporarily shares management account `188757775631` with development while the dedicated
member account's Lambda quota increase is pending; target-scoped stacks, KMS keys, storage, and secrets remain separate.
AgentCore resources use the `FrogBotProduction` physical project namespace in this temporary shared-account posture;
the platform API-key credential providers remain account-scoped.

## One-time production bootstrap

1. Use the configured production AWS account in `us-east-1` and do not rename either target. While production shares
   the management account, set `FROGBOT_ALLOW_SHARED_PRODUCTION_ACCOUNT=true`. Remove that variable when the target
   returns to dedicated member account `820323452649`.
2. Bootstrap CDK and the AgentCore token vault with a reviewed IAM Identity Center or administrator role. Create a
   rotating customer-managed KMS key for AgentCore memory and retain its ARN.
3. Perform the first AgentCore and Amplify bootstrap with that reviewed principal. The Amplify stack creates the
   recurring least-privilege GitHub OIDC deployment role; its trust subject is
   `repo:tmoreton@5090418/frogbot@1356546597:environment:production`, using GitHub's immutable owner and repository
   IDs. Save the `githubDeployRoleArn` output as
   `AWS_DEPLOY_ROLE_ARN`, then use the workflow for every later release. Never use account-root access.
4. Create a production Amplify app and production/sandbox SNS APNs platform applications. Subscribe an accountable
   team or incident system to the generated service-alarm topic and confirm the subscription.
5. Configure the production environment to accept deployments only from `main` and require a reviewer if the GitHub
   plan supports environment reviewers.

## GitHub production environment

Set these non-secret variables:

- `AWS_DEPLOY_ROLE_ARN`, `AMPLIFY_APP_ID`, `FROGBOT_AGENTCORE_MEMORY_KMS_KEY_ARN`
- `FROGBOT_ALLOW_SHARED_PRODUCTION_ACCOUNT=true` only while production and development share an AWS account
- `FROGBOT_APPLE_TEAM_ID`, `FROGBOT_APP_STORE_CONNECT_KEY_ID`, and
  `FROGBOT_APP_STORE_CONNECT_ISSUER_ID`
- `FROGBOT_APNS_APPLICATION_ARN` and optional `FROGBOT_APNS_SANDBOX_APPLICATION_ARN`
- `FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT` based on the verified Google project quota
- `FROGBOT_MONTHLY_BUDGET_USD`
- `FROGBOT_GOOGLE_REVIEW_APPROVED`, `FROGBOT_SLACK_REVIEW_APPROVED`,
  `FROGBOT_X_REVIEW_APPROVED`, and `FROGBOT_NOTION_REVIEW_APPROVED` set to `true` only after the provider's
  production verification/distribution requirements are complete
- `FROGBOT_RELEASE_COMPLIANCE_APPROVED=true` only after privacy policy, terms, support and deletion disclosures,
  data-retention statements, and store metadata match the deployed behavior
- `FROGBOT_APNS_DEVICE_SMOKE_APPROVED=true` only after a production-signed build receives and opens a notification
  on a physical device

Set these environment secrets:

- `AGENTCORE_CREDENTIAL_FROGBOT_OPENROUTER`, `AGENTCORE_CREDENTIAL_FROGBOTXAPI`,
  `AGENTCORE_CREDENTIAL_FROGBOTYOUTUBEAPI`
- `FROGBOT_GOOGLE_OAUTH_SECRET_ARN`, `FROGBOT_GITHUB_APP_SECRET_ARN`, `FROGBOT_X_OAUTH_SECRET_ARN`,
  `FROGBOT_SLACK_OAUTH_SECRET_ARN`, `FROGBOT_NOTION_OAUTH_SECRET_ARN`
- `FROGBOT_APP_STORE_CONNECT_PRIVATE_KEY`, containing the App Store Connect `.p8` key
- `FROGBOT_APPLE_DISTRIBUTION_CERTIFICATE_BASE64`, containing a base64-encoded Apple Distribution `.p12`, and
  `FROGBOT_APPLE_DISTRIBUTION_CERTIFICATE_PASSWORD`

Do not set a Microsoft secret unless Microsoft 365 is intentionally reviewed and enabled. Meta and LinkedIn remain
deferred and absent from the registry for this release.

## Provider evidence

- Google: production OAuth consent verification covers Gmail restricted scopes and the listed Workspace/YouTube
  scopes; any required security assessment is current; redirect URIs use the production API; YouTube quota is
  measured and the application limit does not exceed it.
- Slack: the app is approved for the intended external distribution model, token rotation is enabled, and only the
  documented read scopes are present.
- X: the paid/access tier supports expected traffic and the production callback and read-only scopes are approved.
- Notion: the public integration is approved, read-content is the only content capability, and revocation was tested.
- GitHub: the App uses selected repositories, documented permissions, no webhook, and the temporary user token is
  revoked after installation ownership is verified.

## Release and evidence

The workflow installs the checked-in `agentcore/cdk/package-lock.json` and disables the AgentCore CLI's automatic CDK
dependency rewriting. This keeps the audited repository lockfile authoritative during deployment. Because the CLI
requires its ignored `.env.local` file during credential provisioning, the workflow creates that file with owner-only
permissions from protected environment secrets immediately before deployment and deletes it when the step exits.

1. Merge a clean, reviewed commit to `main`; confirm application, backend, runtime, AgentCore, Apple, dependency,
   provider-contract, and security workflows pass.
2. Run **Deploy FroggyBot production release** from `main`. It validates the target/account and approvals, verifies and
   audits dependencies, deploys AgentCore then Amplify, generates the client outputs, hardens runtime logs, configures
   AgentCore alarms and APNs delivery feedback, seeds the private meme-template catalog when absent, verifies every
   referenced template image along with storage/PITR/alerts/public API, and preserves the exact production client
   configuration. A dependent macOS job then verifies the native suites once and uploads matching iPhone and Mac
   builds to TestFlight. Expo is neither built nor published by this release.
   The default `full` scope requires the protected Apple API key and Distribution certificate. When an authorized
   release operator must use the Apple account already signed into Xcode, select `backend-only`; every AWS, provider,
   compliance, and device approval remains enforced, but the TestFlight job is skipped. Download the preserved
   production client-configuration artifact, place its two files at their recorded repository paths, then run
   `APPLE_TEAM_ID=GVXC5FQ2RP ./scripts/apple-app.sh testflight all` from a clean checkout of the same commit.
3. Confirm both builds complete App Store Connect processing and complete the App Store/TestFlight compliance forms.
   The preserved configuration artifact remains available for local reproduction and incident review.
4. Run an authenticated disposable-user workflow and the agreed concurrency test against production. Verify OAuth
   connect/read/revoke for every enabled provider and confirm logs contain neither content nor tokens.
5. Run `scripts/aws-recovery-drill.sh` against the production outputs, record the restore evidence, and verify an alarm
   notification reaches the accountable destination.
6. Record commit SHA, workflow run, deployed resource IDs, smoke/load results, provider evidence, recovery evidence,
   and rollback owner in `docs/verification-history.md`. Release invitations gradually and monitor the objectives in
   `docs/operations.md`.

Rollback uses the last known-good commit through the same workflow. Never rename or manually replace retained stateful
resources during an incident.
