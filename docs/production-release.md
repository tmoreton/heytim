# HeyTim production release gate

The repository is release-hardened, but a production release is not complete merely because the code passes locally.
The configured AWS account, third-party approvals, monitored alert destination, device evidence, and controlled
deployment are external release inputs. The **Deploy HeyTim production release** workflow fails closed until
they are present. Production temporarily shares management account `188757775631` with development while the dedicated
member account's Lambda quota increase is pending; target-scoped stacks, KMS keys, storage, and secrets remain separate.
AgentCore resources use the target-scoped `HeyTimProduction` physical project namespace in this temporary shared-account
posture; the platform API-key credential providers remain account-scoped.

## One-time production bootstrap

1. Use the configured production AWS account in `us-east-1` and do not rename either target. While production shares
   the management account, set `HEYTIM_ALLOW_SHARED_PRODUCTION_ACCOUNT=true`. Remove that variable when the target
   returns to dedicated member account `820323452649`.
2. Bootstrap CDK and the AgentCore token vault with a reviewed IAM Identity Center or administrator role. Create a
   rotating customer-managed KMS key for AgentCore memory and retain its ARN.
3. Perform the first AgentCore and Amplify bootstrap with that reviewed principal. The Amplify stack creates the
   recurring least-privilege GitHub OIDC deployment role; its trust subject is
   `repo:tmoreton@5090418/heytim@1356546597:environment:production`, using GitHub's immutable owner and repository
   IDs. Save the `githubDeployRoleArn` output as
   `AWS_DEPLOY_ROLE_ARN`, then use the workflow for every later release. Never use account-root access.
4. Create a production Amplify app and production/sandbox SNS APNs platform applications. Subscribe an accountable
   team or incident system to the generated service-alarm topic and confirm the subscription.
5. Configure the production environment to accept deployments only from `main` and require a reviewer if the GitHub
   plan supports environment reviewers.

## GitHub production environment

Set these non-secret variables:

- `AWS_DEPLOY_ROLE_ARN`, `AMPLIFY_APP_ID`, `HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN`
- `HEYTIM_ALLOW_SHARED_PRODUCTION_ACCOUNT=true` only while production and development share an AWS account
- `HEYTIM_APPLE_TEAM_ID`, `HEYTIM_APP_STORE_CONNECT_KEY_ID`, and
  `HEYTIM_APP_STORE_CONNECT_ISSUER_ID`
- `HEYTIM_APNS_APPLICATION_ARN` and optional `HEYTIM_APNS_SANDBOX_APPLICATION_ARN`
- `HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT` based on the verified Google project quota
- `HEYTIM_MONTHLY_BUDGET_USD`
- Optional Stripe launch variables: `HEYTIM_STRIPE_PLUS_PRICE_ID`, `HEYTIM_STRIPE_LIVE_MODE` (start with `false`),
  `HEYTIM_STRIPE_AUTOMATIC_TAX` (start with `false`), `HEYTIM_FREE_MONTHLY_CREDITS`,
  `HEYTIM_PLUS_MONTHLY_CREDITS`, and `HEYTIM_PLUS_PRICE_CENTS`
- `HEYTIM_GOOGLE_REVIEW_APPROVED`, `HEYTIM_SLACK_REVIEW_APPROVED`,
  `HEYTIM_X_REVIEW_APPROVED`, and `HEYTIM_NOTION_REVIEW_APPROVED` set to `true` only after the provider's
  production verification/distribution requirements are complete
- `HEYTIM_RELEASE_COMPLIANCE_APPROVED=true` only after privacy policy, terms, support and deletion disclosures,
  data-retention statements, and store metadata match the deployed behavior
- `HEYTIM_APNS_DEVICE_SMOKE_APPROVED=true` only after a production-signed build receives and opens a notification
  on a physical device

Set these environment secrets:

- `AGENTCORE_CREDENTIAL_FROGBOT_OPENROUTER`, `AGENTCORE_CREDENTIAL_FROGBOTXAPI`,
  `AGENTCORE_CREDENTIAL_FROGBOTYOUTUBEAPI`
- `HEYTIM_GOOGLE_OAUTH_SECRET_ARN`, `HEYTIM_GITHUB_APP_SECRET_ARN`, `HEYTIM_X_OAUTH_SECRET_ARN`,
  `HEYTIM_SLACK_OAUTH_SECRET_ARN`, `HEYTIM_NOTION_OAUTH_SECRET_ARN`
- Optional: `HEYTIM_MICROSOFT_OAUTH_SECRET_ARN`, `HEYTIM_HUBSPOT_OAUTH_SECRET_ARN`,
  `HEYTIM_JIRA_OAUTH_SECRET_ARN`, `HEYTIM_ZOOM_OAUTH_SECRET_ARN`
- Optional until subscriptions are enabled: `HEYTIM_STRIPE_SECRET_KEY` and
  `HEYTIM_STRIPE_WEBHOOK_SECRET`. Set both only with the Stripe Price variable. The release workflow stores them in
  the production account's `heytim/stripe/production` Secrets Manager secret and passes only its ARN to Lambda.
- `FROGBOT_APP_STORE_CONNECT_PRIVATE_KEY`, containing the App Store Connect `.p8` key
- `FROGBOT_APPLE_DISTRIBUTION_CERTIFICATE_BASE64`, containing a base64-encoded Apple Distribution `.p12`, and
  `FROGBOT_APPLE_DISTRIBUTION_CERTIFICATE_PASSWORD`
- `FROGBOT_APPLE_DEVELOPMENT_CERTIFICATE_BASE64`, containing a base64-encoded Apple Development `.p12`, and
  `FROGBOT_APPLE_DEVELOPMENT_CERTIFICATE_PASSWORD`

The three `AGENTCORE_CREDENTIAL_FROGBOT_*` keys and the currently configured
`FROGBOT_APP_*` Apple signing secret keys are compatibility names for protected
values that GitHub cannot reveal or rename. The workflow maps them into HeyTim's
runtime variables. Keep those protected names until their values are deliberately
rotated into new `HEYTIM_*` secrets. Likewise, the AgentCore resource names,
existing Cognito logical IDs, storage bucket names, KMS aliases, and deployed-state
records retain their original physical identifiers so this branding change updates
the live product in place instead of replacing accounts, memory, or user files.

The `production` environment must allow deployment from `main` and tags matching `v*`. The workflow still verifies
that a release tag has the exact `vMAJOR.MINOR.PATCH` form and points to a commit on `main`. A full release stops before
backend deployment if any Apple signing value above is missing.

Set optional provider secrets only after the corresponding OAuth app is configured and reviewed. Meta and LinkedIn remain
deferred and absent from the registry for this release.

Before enabling Stripe, create the monthly Plus Product/Price, configure the customer portal, register the deployed
`stripeWebhookUrl`, and exercise checkout, renewal/update, cancellation, webhook replay, account deletion, and a failed
payment in test mode. Confirm the app's Usage & Plan screen refreshes through `https://heytim.ai/billing`, that the
associated-domain entitlement is present in the signed build, and that the App Store listing and review notes describe
the U.S.-only external web purchase flow. Do not set `HEYTIM_STRIPE_LIVE_MODE=true` until this evidence is recorded.

## Provider evidence

- Google: production OAuth consent verification covers Gmail restricted scopes and the listed Workspace/YouTube
  scopes; any required security assessment is current; redirect URIs use the production API; YouTube quota is
  measured and the application limit does not exceed it.
- Slack: the app is approved for the intended external distribution model, token rotation is enabled, and only the
  documented read scopes are present.
- X: the paid/access tier supports expected traffic and the production callback and read-only scopes are approved.
- Notion: the public integration is approved, read-content is the only content capability, and revocation was tested.
- GitHub: the App uses selected repositories, documented permissions, a signed Issues webhook, and the temporary user token is
  revoked after installation ownership is verified. Confirm a delivery and replay against the production endpoint.

## Release and evidence

The workflow installs the checked-in `agentcore/cdk/package-lock.json` and disables the AgentCore CLI's automatic CDK
dependency rewriting. This keeps the audited repository lockfile authoritative during deployment. Because the CLI
requires its ignored `.env.local` file during credential provisioning, the workflow creates that file with owner-only
permissions from protected environment secrets immediately before deployment and deletes it when the step exits.

1. Merge a clean, reviewed commit to `main`; confirm application, backend, runtime, AgentCore, Apple, dependency,
   provider-contract, and security workflows pass. Create and publish a stable GitHub Release from that commit with a
   tag such as `v1.0.0`. Drafts and pre-releases do not deploy production; the tagged commit must be on `main`.
2. Publishing the release starts **Deploy HeyTim production release**. It validates the tag, target/account, and approvals, verifies and
   audits dependencies, deploys AgentCore then Amplify, generates the client outputs, hardens runtime logs, configures
   AgentCore alarms and APNs delivery feedback, seeds the private meme-template catalog when absent, verifies every
   referenced template image along with storage/PITR/alerts/public API, and preserves the exact production client
   configuration. A dependent job on the repository-scoped `frogbot-macmini` runner then verifies the native suites
   once, uploads iPhone to the HeyTim TestFlight listing, and creates a Developer ID signed and notarized Mac DMG
   for drag-to-Applications installation, plus a ZIP and signed Sparkle appcast for updates. All three attach to the
   GitHub Release. The release tag supplies the Apple marketing version
   (`v1.0.0` becomes `1.0.0`); a numeric build number is generated for each workflow run. Expo is
   neither built nor published by this release.
   The default `full` scope requires the protected Apple API key and Distribution certificate. When an authorized
   release operator must use the Apple account already signed into Xcode, manually run the workflow from `main` with
   `backend-only`; every AWS, provider,
   compliance, and device approval remains enforced, but the TestFlight job is skipped. Download the preserved
   production client-configuration artifact, place its two files at their recorded repository paths, then run
   `APPLE_TEAM_ID=GVXC5FQ2RP ./scripts/apple-app.sh testflight ios` and then the documented
   `distribute-macos` command from a clean checkout of the same commit. Manual
   runs remain available for recovery and use the version in the checked-in Xcode project unless an explicit
   `HEYTIM_MARKETING_VERSION` is supplied for a local archive.
3. Confirm the iPhone build completes App Store Connect processing. Mount the Mac DMG on a clean machine, drag the app
   to Applications, verify Gatekeeper accepts it, and test an update from the previous release through the published
   appcast. The preserved
   configuration and Mac release artifacts remain available for reproduction and incident review.
4. Run an authenticated disposable-user workflow and the agreed concurrency test against production. Verify OAuth
   connect/read/revoke for every enabled provider and confirm logs contain neither content nor tokens.
5. Run `scripts/aws-recovery-drill.sh` against the production outputs, record the restore evidence, and verify an alarm
   notification reaches the accountable destination.
6. Record commit SHA, workflow run, deployed resource IDs, smoke/load results, provider evidence, recovery evidence,
   and rollback owner in `docs/verification-history.md`. Release invitations gradually and monitor the objectives in
   `docs/operations.md`.

Rollback reverts `main` to the last known-good state and uses a reviewed manual workflow run. Never rename or manually
replace retained stateful resources during an incident.
