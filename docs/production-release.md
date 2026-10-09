# HeyTim production release gate

The repository is release-hardened, but a production release is not complete merely because the code passes locally.
The configured AWS account, third-party approvals, monitored alert destination, device evidence, and controlled
deployment are external release inputs. The **Deploy HeyTim production release** workflow fails closed until
they are present. Production uses dedicated member account `820323452649`; stacks, KMS keys, storage, credentials, and
service quotas are isolated from development.

## Production account launch scope

Changing the configured account provisions independent resources; it does not move the production state previously
hosted in management account `188757775631`. Choose exactly one explicit launch path:

- **Fresh content:** Set `HEYTIM_DATA_LAUNCH_MODE=fresh` and, after recording the owner's choice and the destination
  checks below, `HEYTIM_FRESH_ACCOUNT_LAUNCH_APPROVED=true`. Set `HEYTIM_DESTINATION_ACCOUNT_ID=820323452649` and
  verify `AWS_DEPLOY_ROLE_ARN` belongs to that account and `AMPLIFY_APP_ID` resolves through that role. New users and
  content start in the destination; this path does not copy legacy users, memory, files, provider tokens, or billing
  state. Record an empty destination baseline, client and sign-in behavior, and a rollback plan for the new client.
  The source service is not frozen or retired by this launch. Keep its resources and records intact until a separately
  reviewed retirement or data disposition decision. Leave `HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED` unset or `false`.
  The fresh release passes destination AgentCore Identity KMS key
  `arn:aws:kms:us-east-1:820323452649:key/4893a4c0-00e8-4381-823b-19c8bc8ed248` to the runtime and API;
  it never passes the protected legacy source-account token-vault key.
- **State migration:** Set `HEYTIM_DATA_LAUNCH_MODE=migrate` and use the preservation plan below. Set
  `HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED=true` only after its pre-cutover checks pass. Leave
  `HEYTIM_FRESH_ACCOUNT_LAUNCH_APPROVED` unset or `false`.

For a migration launch, before setting
`HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED=true`, approve and record a migration plan that:

1. Inventories the legacy and destination AgentCore runtimes, memory, credentials, DynamoDB tables and recovery
   points, S3 objects and versions, Cognito users and clients, queues and schedules, KMS keys, Secrets Manager values,
   API/domain bindings, provider webhooks, APNs applications, logs, alarms, budgets, and deployment roles.
2. Defines data movement and validation for every retained stateful resource. Include item/object counts and checksums,
   the Cognito user migration or reauthentication path, memory retention decisions, secret rotation, signing assets,
   queue draining, and a bounded write-freeze because the application does not dual-write across accounts.
3. Bootstraps and verifies the destination without directing production traffic to it, then captures a final recoverable
   source backup, drains work, copies the approved state, and exercises authentication, provider callbacks, the managed
   evaluation, and the authenticated release workflow.
4. Defines the API/domain and client-configuration cutover, named owners, maintenance window, acceptance evidence, and
   rollback to the retained legacy environment. Keep the old resources read-only and recoverable through the agreed
   rollback window.
5. Deletes or disables legacy resources only in a separately reviewed cleanup after rollback expires and data-retention,
   audit, signing, and recovery obligations have been verified.

Neither launch mode itself performs a migration or authorizes cleanup of the legacy account.

## One-time production bootstrap

1. Use dedicated production AWS account `820323452649` in `us-east-1` and do not rename either target.
2. Bootstrap CDK and the AgentCore token vault with a reviewed IAM Identity Center or administrator role. Create a
   rotating customer-managed KMS key for AgentCore memory and retain its ARN.
3. Create the account-wide GitHub Actions OIDC provider in destination IAM before using the recurring deploy role.
   The provider ARN is `arn:aws:iam::820323452649:oidc-provider/token.actions.githubusercontent.com`, its URL is
   `https://token.actions.githubusercontent.com`, and its only audience is `sts.amazonaws.com`. The provider was
   created on 2026-09-30 as a one-time account bootstrap resource outside the Amplify stack; IAM resolved its TLS
   thumbprint. Verify the provider and the deploy role trust with
   `AWS_PROFILE=frogbot-production-org ./scripts/check-production-oidc.sh` before dispatching production. A new
   account needs its own provider. The provider grants no AWS permissions by itself; the deploy role below restricts
   access to the production environment of the immutable HeyTim repository identity.
4. Perform the first AgentCore and Amplify bootstrap with that reviewed principal. The Amplify stack creates the
   recurring least-privilege GitHub OIDC deployment role; its trust subject is
   `repo:tmoreton@5090418/heytim@1356546597:environment:production`, using GitHub's immutable owner and repository
   IDs. Save the `githubDeployRoleArn` output as
   `AWS_DEPLOY_ROLE_ARN`, then use the workflow for every later release. Never use account-root access.
5. Create a production Amplify app and production/sandbox SNS APNs platform applications. Subscribe an accountable
   team or incident system to the generated service-alarm topic and confirm the subscription.
6. Configure the production environment to accept deployments only from `main` and require a reviewer if the GitHub
   plan supports environment reviewers.

## GitHub production environment

Set these non-secret variables:

- `AWS_DEPLOY_ROLE_ARN`, `AMPLIFY_APP_ID`, `HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN`
- `HEYTIM_APPLE_TEAM_ID`, `HEYTIM_APP_STORE_CONNECT_KEY_ID`, and
  `HEYTIM_APP_STORE_CONNECT_ISSUER_ID`
- `HEYTIM_APNS_APPLICATION_ARN` and optional `HEYTIM_APNS_SANDBOX_APPLICATION_ARN`
- `HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT` based on the verified Google project quota
- `HEYTIM_MONTHLY_BUDGET_USD`
- Explicit `HEYTIM_DATA_LAUNCH_MODE` (`fresh` or `migrate`), `HEYTIM_DESTINATION_ACCOUNT_ID` for a fresh launch,
  and the matching `HEYTIM_FRESH_ACCOUNT_LAUNCH_APPROVED` or `HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED` flag
- Explicit `HEYTIM_BILLING_MODE=free` for a free launch. The workflow passes empty Stripe API key, webhook secret,
  Price ID, and secret ID to Amplify, with live mode and automatic tax disabled, even if protected Stripe values remain
  stored for a later decision. `HEYTIM_BILLING_MODE=stripe` requires the API key, webhook secret, and Price ID together.
  Related variables are `HEYTIM_STRIPE_PLUS_PRICE_ID`, `HEYTIM_STRIPE_LIVE_MODE`,
  `HEYTIM_STRIPE_AUTOMATIC_TAX`, `HEYTIM_FREE_MONTHLY_CREDITS`, `HEYTIM_PLUS_MONTHLY_CREDITS`, and
  `HEYTIM_PLUS_PRICE_CENTS`.
- `HEYTIM_GOOGLE_REVIEW_APPROVED`, `HEYTIM_SLACK_REVIEW_APPROVED`,
  `HEYTIM_X_REVIEW_APPROVED`, and `HEYTIM_NOTION_REVIEW_APPROVED` set to `true` only after the provider's
  production verification/distribution requirements are complete
- `HEYTIM_GOOGLE_WORKSPACE_CONNECTIONS_ENABLED` defaults to `false`. Set it to `true` only after
  declaring and reviewing Workspace's additional Google scopes, verifying the Workspace tools, and setting
  `HEYTIM_GOOGLE_WORKSPACE_REVIEW_APPROVED=true`. The regular Google gate must also be enabled and approved.
- `HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED=true` only for the reviewed state-migration path; use the fresh-launch
  flag for an empty destination instead
- `HEYTIM_RELEASE_COMPLIANCE_APPROVED=true` only after privacy policy, terms, support and deletion disclosures,
  data-retention statements, and store metadata match the deployed behavior
- `HEYTIM_APNS_DEVICE_SMOKE_APPROVED=true` only after a production-signed build receives and opens a notification
  on a physical device

Set these environment secrets:

- `AGENTCORE_CREDENTIAL_FROGBOT_OPENROUTER`, `AGENTCORE_CREDENTIAL_FROGBOTXAPI`,
  `AGENTCORE_CREDENTIAL_FROGBOTYOUTUBEAPI`
- `HEYTIM_RELEASE_TEST_REFRESH_TOKEN`, issued only to a dedicated production synthetic user. Keep that user free of
  personal data and third-party connections. The release test deletes every temporary bot it creates but deliberately
  retains the account so the refresh token can be reused and rotated independently.
  In the dedicated free-launch destination, only the pinned release fixture identity receives a 300-credit monthly
  test allowance. Its usage remains metered and subject to monthly, per-user, global-rate, and circuit limits;
  ordinary free accounts retain their configured allowance. The authenticated check requires four remaining
  credits before creating temporary resources, so an exhausted fixture fails before any test turns start.
- `HEYTIM_GOOGLE_OAUTH_SECRET_ARN`, `HEYTIM_GITHUB_APP_SECRET_ARN`, `HEYTIM_X_OAUTH_SECRET_ARN`,
  `HEYTIM_SLACK_OAUTH_SECRET_ARN`, `HEYTIM_NOTION_OAUTH_SECRET_ARN`
- `HEYTIM_MAC_DEVELOPER_ID_PROFILE_BASE64` for direct Mac distribution. This is the Apple-issued Developer ID
  provisioning profile for `ai.heytim.app`, signed for the same Developer ID Application certificate imported by CI.
  The release script checks the team, bundle ID, profile signature, and certificate before exporting the Mac app.
- Optional: `HEYTIM_MICROSOFT_OAUTH_SECRET_ARN`, `HEYTIM_HUBSPOT_OAUTH_SECRET_ARN`,
  `HEYTIM_JIRA_OAUTH_SECRET_ARN`, `HEYTIM_ZOOM_OAUTH_SECRET_ARN`,
  `HEYTIM_QUICKBOOKS_OAUTH_SECRET_ARN`, `HEYTIM_PLAID_SECRET_ARN`
- `HEYTIM_STRIPE_SECRET_KEY` and `HEYTIM_STRIPE_WEBHOOK_SECRET` remain protected for a future billing decision. In
  `free` mode, the release workflow passes neither secret nor a Price ID to the deployment and does not provision a
  new Stripe billing secret. In `stripe` mode, set both with the Price variable; the workflow stores them in the
  production account's `heytim/stripe/production` Secrets Manager secret and passes only its ARN to Lambda.
- `FROGBOT_APP_STORE_CONNECT_PRIVATE_KEY`, containing the App Store Connect `.p8` key
- `FROGBOT_APPLE_DISTRIBUTION_CERTIFICATE_BASE64`, containing a base64-encoded Apple Distribution `.p12`, and
  `FROGBOT_APPLE_DISTRIBUTION_CERTIFICATE_PASSWORD`
- `FROGBOT_APPLE_DEVELOPMENT_CERTIFICATE_BASE64`, containing a base64-encoded Apple Development `.p12`, and
  `FROGBOT_APPLE_DEVELOPMENT_CERTIFICATE_PASSWORD`
- `HEYTIM_INTERNAL_TESTER_EMAIL`, containing the intended owner's exact App Store Connect/TestFlight email. The
  first internal upload compares it privately against Apple's internal tester groups and never prints the email.
  The read-only inventory can instead compare Apple's unique Account Holder without an email secret. Set the secret
  only after the owner identifies the intended Apple account; Account Holder membership alone does not prove that
  the intended device tester is ready.

The three `AGENTCORE_CREDENTIAL_FROGBOT_*` keys and the currently configured
`FROGBOT_APP_*` Apple signing secret keys are compatibility names for protected
values that GitHub cannot reveal or rename. The workflow maps them into HeyTim's
runtime variables. Keep those protected names until their values are deliberately
rotated into new `HEYTIM_*` secrets. Likewise, retain AgentCore resource names, Cognito logical IDs, storage bucket
names, KMS aliases, and deployed-state records within each account. The dedicated-account cutover is a separately
reviewed infrastructure and data migration; it does not authorize branding-driven renames or early deletion of the
legacy resources.

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

For a launch that omits a provider while its external review is pending, set that provider's protected production
environment variable to `false` before deploying: `HEYTIM_GOOGLE_CONNECTIONS_ENABLED`,
`HEYTIM_SLACK_CONNECTIONS_ENABLED`, `HEYTIM_NOTION_CONNECTIONS_ENABLED`, or `HEYTIM_X_CONNECTIONS_ENABLED`.
These four provider switches default to `true`; the separate Google Workspace switch defaults to `false`.
Disabling Google covers Gmail, YouTube account access, and Google Workspace together. When Google is enabled but
Workspace remains disabled, Gmail and YouTube can be offered without the Workspace authorization path. The
destination backend then omits those connection cards, rejects new authorization and pending callbacks, and excludes
any retained connection tools from bot selection and execution. Independent public catalog tools remain available.
The release gate requires a provider's review attestation only while its connections are enabled. Keep an unapproved
provider's review attestation `false`; enable its connections and redeploy only after its external review is verified.
Workspace also requires its own review attestation before that separate switch may be enabled.

### Fresh-launch protected variable reconciliation (2026-09-30)

Before a fresh release or internal device-smoke upload, read back these **production environment** variables by name
and target. The workflow rejects source-account APNs values and a source-account deployment role. The destination APNs
applications are named `HeyTim` and use the `ai.heytim.app` bundle ID. Keep the legacy `FrogBot` applications for
rollback; do not use them for new device registrations.

| Variable | Required fresh/free target |
| --- | --- |
| `HEYTIM_DATA_LAUNCH_MODE` | `fresh` |
| `HEYTIM_FRESH_ACCOUNT_LAUNCH_APPROVED` | `true` only after the recorded fresh-content decision and destination checks |
| `HEYTIM_ACCOUNT_ISOLATION_CUTOVER_APPROVED` | unset or `false` |
| `HEYTIM_DESTINATION_ACCOUNT_ID` | `820323452649` |
| `AWS_DEPLOY_ROLE_ARN` | role ARN in account `820323452649` |
| `AMPLIFY_APP_ID` | `d17sj7dvhx07c`, confirmed by `amplify get-app` under that role |
| `HEYTIM_APNS_APPLICATION_ARN` | `arn:aws:sns:us-east-1:820323452649:app/APNS/HeyTim` |
| `HEYTIM_APNS_SANDBOX_APPLICATION_ARN` | `arn:aws:sns:us-east-1:820323452649:app/APNS_SANDBOX/HeyTim` |
| `HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT` | `100`, matching the destination worker's current limit and protected environment inventory |
| `HEYTIM_BILLING_MODE` | `free`; the workflow passes no Stripe triad and disables live mode |

At the 2026-09-30 checkpoint, the protected APNs variables still contained source-account ARNs. On 2026-10-01,
the destination production and sandbox applications were created with Apple token authentication for team
`GVXC5FQ2RP` and bundle `ai.heytim.app`; the protected variables were updated and read back. Verify their
current values again before release. The protected
`HEYTIM_LEGACY_TOKEN_VAULT_KMS_KEY_ARN` may still name the source key, but fresh mode overrides it with the verified
destination AgentCore Identity key above. Do not copy the source key ARN into the destination deployment.

## Release and evidence

Before publishing a destination client, dispatch **Build destination iOS candidate without upload** from the current
`main` commit with the next marketing version (for example `1.0.13` after `v1.0.12`). The workflow pins the committed
destination candidate to account `820323452649`, stages it only on the Apple runner, runs the iPhone and Mac verification
gate, and exports a signed iPhone IPA locally. It verifies the destination configuration inside that IPA, records its
SHA-256 and build details in a 30-day Actions receipt, then deletes the signed IPA and archive from the runner. The
repository is public, so the IPA is never uploaded as an Actions artifact. This preflight does not upload to App Store
Connect, deploy AWS resources, create a GitHub Release, or publish a Mac/Sparkle update.
Dispatch **Build private destination Mac candidate** from the same `main` commit and version. It verifies both Apple
platforms, signs and notarizes the Mac app and disk image, checks the Sparkle ZIP and appcast, records nonsecret
checksums, and deletes the signed files and isolated build directory from the runner. Its Actions artifact contains
only the receipt; the live Sparkle feed and GitHub Release remain unchanged.
For an owner-requested installation on the signing Mac, set `retain_local_installer=true`. After notarization,
the workflow retains only the DMG and checksum receipt under
`~/Library/Application Support/HeyTim/Internal Installers/<build-number>/`, with owner-only permissions.
Download or copy that installer directly from the signing Mac and verify its checksum against the receipt before
installing. This opt-in does not upload binaries to the public repository, publish a release, change the Sparkle
feed, or mark the public-release approval checks complete. The default still deletes all signed binaries.
The Mac export uses the protected Developer ID profile with local manual signing. A new profile requires the
`ai.heytim.app` App ID and the existing Developer ID Application certificate; creating a replacement certificate
also requires updating its matching certificate bundle in the protected production environment.
[Apple says](https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-testers-to-builds/)
that eligible builds can be made available automatically to the **App Store Connect Users** internal group. The
preflight receipt is therefore evidence of a local signed build, not a TestFlight build. An operator must review that
group before the first internal-only upload. A migration launch waits for the write-frozen customer-state transfer;
a fresh-content launch instead verifies the destination's empty baseline and new-user path without freezing the
independent source service.

### First destination internal TestFlight handoff

For `migrate`, the migration operator inspects the **private** final DynamoDB, versioned-S3, and AgentCore-memory
manifests and apply/verification output while the source write freeze is active. The source snapshot digests must
remain stable; destination counts and content digests must match the plan; identity remapping and preservation
exceptions must be recorded; and live destination reads must show the migrated records, files, and memory. Keep the
source frozen and rollback available through this handoff.

For `fresh`, record the approved no-transfer choice, empty destination baseline, destination app/role/APNs identifiers,
current `main` commit, expected new sign-in behavior, and rollback owner in `docs/verification-history.md`. This
handoff does not freeze, retire, or clean up the source account. Confirm free billing is selected and the destination
backend is ready before installing a new client.

After the mode-specific evidence is complete, review the **App Store Connect Users** group membership. For `fresh`,
manually dispatch **Upload destination iOS build for internal device smoke** from current `main` with version `1.0.13` and
`internal_testers_reviewed=true`. This protected workflow requires the approved fresh/free destination, checks the
destination app and committed client configuration, and queries App Store Connect to prove the protected expected
owner email is accepted in an internal group with access to all builds before signing or uploading. It verifies both
Apple platforms and calls the existing
`ios-post-migration` export scope. Despite its historical name, that scope selects an App Store Connect upload with
`testFlightInternalTestingOnly=true`; the workflow retains only a nonsecret submission receipt. It does not publish
the Mac app or Sparkle feed. For `migrate`, retain the documented operator-controlled upload from a clean checkout
of the recorded commit with verified destination outputs using
`HEYTIM_RELEASE_SCOPE=ios-post-migration ./scripts/apple-app.sh testflight ios` while the source freeze remains active.
Capture the submitted build number and confirm App Store Connect processing. Install it
through TestFlight on a physical device, prove destination sign-in and APNs delivery, and set
`HEYTIM_APNS_DEVICE_SMOKE_APPROVED=true` only after recording that evidence. The later full release generates a new
build number and publishes the Mac/Sparkle artifacts.

The full production release workflow installs the checked-in `agentcore/cdk/package-lock.json` and disables the AgentCore CLI's automatic CDK
dependency rewriting. This keeps the audited repository lockfile authoritative during deployment. Because the CLI
requires its ignored `.env.local` file during credential provisioning, the workflow creates that file with owner-only
permissions from protected environment secrets immediately before deployment and deletes it when the step exits.

1. Merge a clean, reviewed commit to `main`; confirm application, backend, runtime, AgentCore, Apple, dependency,
   provider-contract, and security workflows pass. Create and publish a stable GitHub Release from that commit with a
   tag such as `v1.0.0`. Drafts and pre-releases do not deploy production; the tagged commit must be on `main`.
2. Publishing the release starts **Deploy HeyTim production release**. It validates the tag, target/account, and approvals, verifies and
   audits dependencies, deploys AgentCore then Amplify, generates the client outputs, hardens runtime logs, configures
   AgentCore alarms and APNs delivery feedback, seeds the private meme-template catalog when absent, verifies every
   referenced template image along with storage/PITR/alerts/public API, runs the managed five-scenario regression
   dataset with a minimum 0.80 score and no evaluation failures, executes the authenticated attachment/schedule/share/
   approval workflow with the synthetic user, and preserves the exact production client
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
   For a backend plus Mac-only release, first create a draft `vMAJOR.MINOR.PATCH` GitHub Release whose body contains
   `<!-- heytim-backend-macos-predeployed -->`, then dispatch `backend-macos` with that tag. The workflow deploys the
   backend, produces and attaches the notarized DMG, update ZIP, and signed appcast, and skips TestFlight. Publish the
   draft only after the workflow succeeds; the marker prevents the publication event from redeploying the release.
3. Confirm the iPhone build completes App Store Connect processing. Mount the Mac DMG on a clean machine, drag the app
   to Applications, verify Gatekeeper accepts it, and test an update from the previous release through the published
   appcast. The preserved
   configuration and Mac release artifacts remain available for reproduction and incident review.
4. Confirm the workflow's managed evaluation and authenticated production checks passed. Run the agreed concurrency
   test separately, verify OAuth connect/read/revoke for every enabled provider, and confirm logs contain neither
   content nor tokens. Rotate `HEYTIM_RELEASE_TEST_REFRESH_TOKEN` immediately if the synthetic user is disabled,
   its app client changes, or the token may have been exposed.
5. Run `scripts/aws-recovery-drill.sh` against the production outputs, record the restore evidence, and verify an alarm
   notification reaches the accountable destination.
6. Record commit SHA, workflow run, deployed resource IDs, smoke/load results, provider evidence, recovery evidence,
   and rollback owner in `docs/verification-history.md`. Release invitations gradually and monitor the objectives in
   `docs/operations.md`.

Rollback reverts `main` to the last known-good state and uses a reviewed manual workflow run. Never rename or manually
replace retained stateful resources during an incident.

For a targeted recheck of the deployed attachment/schedule/share/approval path, dispatch **Verify deployed HeyTim
production workflow** (`production-smoke.yml`) from current `main`. It uses the production deployment role and
synthetic account without redeploying infrastructure. It reports fixed failure categories and synthetic-account
credit counts, and reads only sanitized AgentCore terminal failure markers from the preceding hour. Message text,
credentials, user identifiers, and raw tracebacks are excluded from its diagnostic output. A successful targeted
recheck does not replace the full release gate or physical-device evidence.
