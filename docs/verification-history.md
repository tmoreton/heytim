# HeyTim verification history

Names in dated entries are preserved exactly as they existed when the evidence
was recorded, including legacy repository, cloud-resource, secret, and bundle IDs.

This file records dated checks against deployed environments. It is evidence from a point in time, not a statement that
the current checkout or environment still has the same status.

## 2026-09-29 — isolated-account cutover preparation

- The source account `188757775631` remains live; no customer traffic, Apple clients, provider webhooks, or production
  GitHub environment variables have switched to destination account `820323452649`.
- The destination backend and AgentCore resource checks passed with the candidate outputs. A destination recovery drill
  restored and verified a DynamoDB point-in-time table and an S3 object version, then removed the temporary table.
- Read-only migration inventories found 638 current source application records, 1,012 file object versions and 13
  delete markers across both source buckets, and AgentCore memory with four actors, 16 sessions, 187 events, and 404
  long-term records. The destination application table and memory remain empty. Migration tools and private identity
  maps are prepared for a fresh write-frozen snapshot; these numbers are not final cutover checksums.
- After hardening the migration identity checks and provider-state exclusions, a new read-only DynamoDB plan again
  found 638 source rows, 625 retained rows, and 13 excluded connection/device/push rows. Its source and plan digests
  are checkpoints only; both must be regenerated after writes stop. The destination API Lambda currently points Google
  and GitHub callbacks at the destination API and uses `https://heytim.ai` as its public site. Stripe remains disabled
  in that Lambda until the subscription identity and webhook cutover is complete.
- A new read-only S3 plan, with Cognito-derived actor checks, again found 295 HeyTim source keys, 455 versions, and one
  delete marker for the canonical-and-archive pass. Separate dry runs of the transient-result retention backfill found
  nine untagged result versions in the HeyTim source bucket and none in the legacy source or destination bucket. No
  tags or lifecycle rules have been applied in AWS; review the backfill only after migration and rollback planning.
- Google saved the destination OAuth callback while retaining source callbacks. The consent app, OAuth client label,
  and Cloud project display name now show HeyTim. The website serves a Search Console tag that verified ownership of
  `https://heytim.ai/`. Google still reports branding and data access unverified. Its branding retry requires waiting
  24 hours after ownership verification; sensitive YouTube and restricted Gmail scopes require subsequent review.
  A warning-free Google sign-in is **not** verified.
- The destination `heytim/stripe/production` secret was created by an in-memory copy of the existing live credential
  bundle and verified by readback; no values were printed. The live Stripe webhook, subscription user metadata, and
  GitHub App webhook still point to the source. An attempt to remove Google's obsolete `froggybot.com` authorized
  domain was blocked by automatic approval review after Google said an OAuth client still uses that domain. The
  proposed removal was not saved.
- A fresh live audit found the source application table at 638 rows and the destination application table and memory
  still empty. The source table digest changed between two read-only scans despite stable row counts, confirming that
  customer writes are ongoing. No customer data migration or write freeze has begun. A read-only reconciliation found
  the one live Stripe subscription and its customer, Price, status, period, and source user mapping match the source
  billing record; the destination billing path is still disabled and no Stripe setting was changed.
- Google's Verification Center still marks HeyTim branding and data access unverified and does not offer submission
  until branding verification is complete. The authorized destination callback is saved, but it is not Google approval.
  On September 29 the protected GitHub production flags for Google review, physical-device APNs smoke, and release
  compliance were corrected from `true` to `false` and read back as `false`. The account-cutover flag remains absent.
- After explicit owner approval on September 29, the Plaid production application credential was copied in memory
  from the source account to protected destination Secrets Manager and read back for exact value parity. Only
  `clientId`, `secret`, and `environment=production` were transferred; no customer Plaid tokens moved. Destination
  Plaid access and webhooks remain disabled until cutover verification.
- A repository-wide hostname audit found no `froggybot.com` or `frogbot.com` URL in live app, website, API, catalog,
  AgentCore configuration, scripts, or workflows. Public web and in-app links use `heytim.ai`. The checked-in active
  API and Apple outputs still use the source AWS API endpoint; the destination endpoint is staged as a candidate,
  not live. The GitHub App homepage and Google's obsolete authorized-domain entry remained external settings to
  resolve at this checkpoint. Later on September 29, the GitHub App homepage alone was changed to
  `https://heytim.ai/` and verified on its public page. The destination GitHub OAuth callback was then added alongside
  the source callback; the setup URL and webhook still point to the source API. After explicit owner approval, the
  destination X OAuth callback was also added beside both existing X callback URLs. Neither provider webhook moved.
- The latest published Apple release remains `v1.0.12`. Local `./scripts/apple-app.sh build` passed for iPhone and Mac,
  and `./scripts/apple-app.sh verify` completed successfully on both platforms on September 29 after the new workflow
  and release-script changes. Destination-configured iPhone and Mac candidate workflows are being prepared without
  publishing TestFlight or the Mac Sparkle release. No new Apple version has been uploaded from this checkpoint.
- The first internal TestFlight dispatch, [run 36618354768](https://github.com/tmoreton/heytim/actions/runs/36618354768),
  was canceled while its sole job was queued, before signing or upload. Apple permits automatic distribution to
  internal groups and makes eligible builds available to App Store Connect Users; even an internal-only upload could
  expose the empty destination account before migration. The revised pre-cutover workflow builds and checks a signed
  candidate without uploading it to TestFlight. The repository is public, so signed binaries are not retained as
  downloadable Actions artifacts.
- Cutover-readiness and provider-gating code landed on `main` as `5adc721`, followed by the source-size correction
  `520df09`. The iPhone and Mac destination-only version `1.0.13` candidates from `520df09` are
  [run 36652160673](https://github.com/tmoreton/heytim/actions/runs/36652160673) and
  [run 36652172869](https://github.com/tmoreton/heytim/actions/runs/36652172869); both were queued at this
  checkpoint, with no TestFlight upload or Sparkle publication. The earlier iPhone candidate from `f4f24fb`
  signed and exported an IPA locally but failed its portable receipt parser; its replacement has that fix.
- Destination production flags for Google, Slack, Notion, and X connections and their review attestations were
  read back as `false`. This hides unverified or unconfigured connections after the destination backend is deployed;
  it does not change the live source service. The source remains writable and no customer-data copy has begun.
  A third source file bucket used by AgentCore contained 208 versions and six delete markers at read-only inventory.
  The main HeyTim source bucket continued gaining versions, so all file and table manifests need a frozen refresh.
- The source write-freeze preflight returned 39 checks and 30 blockers. A guarded read-only capture stopped at
  AgentCore Memory because its resource-policy response did not prove absence versus unsupported policy behavior.
  No source settings were changed. A local Apple verification on the concurrently edited shared workspace compiled
  both platforms and passed Mac tests, but its iPhone UI suite reached the 1,200-second timeout; the clean committed
  candidate jobs are the release check for this revision.
- The September 29 preparation checkout also passed 42 migration tests (plus three subtests), 66 focused runtime
  tests, the API verification gate (including 568 backend tests), all 10 AgentCore CDK tests, API typecheck, Python
  lint/format checks, and the Apple architecture/source-size gate. These local checks do not substitute for the
  protected CI and provider/device checks required before release.

## 2026-09-23 — Home Assistant backend-only rollout

- Merged [PR #58](https://github.com/tmoreton/heytim/pull/58) as commit `b029fd796c87cb1871c4b5643dd5d3d51be4038c`. The required application, runtime, AgentCore, Apple, dependency, and security checks passed.
- [Production run `35865295766`](https://github.com/tmoreton/heytim/actions/runs/35865295766) completed successfully from `main` with `release_scope=backend-only`. It updated the AgentCore runtime and Amplify backend and passed the protected production resource checks. This scope did not upload TestFlight builds or produce a new Mac DMG.
- Home Bot's Home Assistant connection is connected and its per-bot tool switch is on. The separate Mac app actions switch is also on, with Accessibility granted and the bundled local model reporting ready in the installed 1.0.3 app.
- Before this rollout, a direct Assist MCP test of the exact Bedroom Light succeeded: its initial `off` state was read, `HassTurnOn` returned success and state `on`, then `HassTurnOff` returned success and state `off`. The test restored the initial state. This proves the connection and exposed Assist actions, not the bot/Laya path.
- A read-only Home Bot request immediately after the rollout was rejected before agent invocation because the owner account had used all 30 of 30 free work credits; the app says the allowance resets September 30, 2026. Thus the deployed bot path, Laya route, and live on/off through HeyTim remain **unverified**. Do not treat the direct MCP check or the green deployment as evidence that those paths work end to end.

## 2026-09-18 — workflow, routine, workspace, and approval release

- Released commit `2bc8fed` as [`v6.2.5`](https://github.com/tmoreton/frogbot/releases/tag/v6.2.5).
  [Production run `35357358258`](https://github.com/tmoreton/frogbot/actions/runs/35357358258) passed its release
  gates, 454 API/worker tests, 266 runtime tests, dependency audit, AgentCore deployment, Amplify deployment, and
  production resource verification. Local AgentCore validation and Apple unit tests also passed; the native release
  runner passed the iPhone UI suite. Python and JavaScript/TypeScript CodeQL analysis passed.
- The separate website/catalog CI job identified a 600-line source-size gate in three touched backend modules.
  Commit `6845192` moved their functions into focused modules without changing behavior. The full hosted
  [verification run](https://github.com/tmoreton/frogbot/actions/runs/35361014024) and CodeQL passed. A
  [backend-only production run](https://github.com/tmoreton/frogbot/actions/runs/35361037087) deployed that exact
  commit and passed service checks, dependency audit, AgentCore/Amplify deployment, and resource verification.
  The signed webhook smoke check passed again against the updated API.
- The production API accepted a correctly signed synthetic GitHub `issues.opened` delivery and replay with HTTP 202
  (`matchedRoutines: 0`) and rejected a bad signature with HTTP 401. This verifies signature handling for the issue
  route, but no routine matched, so it does not verify routine deduplication. After account confirmation, the GitHub
  App webhook was activated at the production `/public/webhooks/github` URL with SSL verification enabled. Its secret
  was set to the matching 48-byte random value stored in `frogbot/oauth/github-production`, and the App was subscribed
  to Issues events. The GitHub App API confirmed the URL, JSON format, configured secret, and `issues` event. A real
  GitHub `installation.new_permissions_accepted` webhook delivery reached the production endpoint and received HTTP
  200 (`{"accepted":false}`), as expected for an event outside the issue routine trigger. A live `issues.opened`
  delivery with a matching routine remains untested.
- The release runner uploaded both iPhone and Mac TestFlight packages for version `6.2.5`, build `20260918145216`,
  to App Store Connect. Apple's processing and availability in TestFlight must still be checked there.
- The cloud computer remains deferred. Durable bot/room files use the existing encrypted S3 storage and explicit
  Code Interpreter sync; this release does not provision an always-on computer. Live room concurrency, one-use
  approval resume, and workspace sync still need a disposable production pilot before broad activation.

## 2026-09-14 — Mac message recovery and native TestFlight refresh

- Committed release revision `8cbe7ab`. CloudWatch tied the Mac desktop “Something went wrong” response to an old
  `connection_*` tool ID copied with the production bot while OAuth connections were intentionally excluded from the
  owner migration. Removed the four migrated bots' stale connection references and verified all 10 production bots now
  contain zero stale connection IDs. Runtime and API execution also filter unavailable stored tools so a revoked or
  non-migrated connection cannot make an otherwise ordinary message fail.
- Moved editable bot identity and prompt settings onto the main native Details page above its conversation controls,
  replaced the Edit Bot row with Tools & Skills, and switched Details and every native subpage to the compact centered
  navigation title. The focused iPhone Details-page UI regression and the macOS application suite passed.
- Enabled every bot to create and attach a private skill for itself during an explicit direct user conversation. The
  capability cannot grant new tools, run from a schedule, mutate another bot, or publish the skill. Installed
  `JOP Newsletter Voice & AI-Tell Review` as production skill `skill-0eeb70c63f964883afa0` on JOPbot; its review is
  explicitly heuristic and does not claim to determine authorship.
- AgentCore validation, Python lint, all 219 runtime tests, and all 378 backend tests passed. The full native wrapper
  completed its transcription and Mac suites, but the local Xcode 26.6 iOS runner again failed to materialize the test
  worker because its LLDB registry reported `DebuggerVersionStore.StoreError` / `no debugger version`. The focused
  iPhone regression had already passed on the same app change, and both signed Release archives subsequently compiled
  and passed store validation.
- Deployed the existing `AgentCore-FrogBot-production` runtime in place, preserving
  `FrogBotProduction_FrogBotMemory-FWrlGD61iY`, then updated Amplify app `d1tu46ki1836w1`. The runtime reports `READY`,
  the CloudFormation stacks report `UPDATE_COMPLETE`, the public catalog responds successfully, and all five AgentCore
  alarms remain present. The aggregate production verification remains blocked only by the already-recorded missing
  confirmed subscriber on the service-alarm topic.
- Uploaded matching iPhone and Mac TestFlight packages for version `6.0.0`, build `202609141145`, bundle
  `com.frogbot.app`, and team `GVXC5FQ2RP`. App Store Connect accepted the iPhone upload at 11:45 AM EDT and the Mac
  upload at 11:48 AM EDT and began processing both packages.

## 2026-09-14 — temporary management-account production deployment

- Temporarily retargeted production to management account `188757775631` in `us-east-1` while the dedicated member
  account Lambda quota request remains open. Deployments used the assumed `FrogBotDeploymentRole`, never AWS
  account-root credentials, and require the explicit `FROGBOT_ALLOW_SHARED_PRODUCTION_ACCOUNT=true` safeguard.
- Deployed `AgentCore-FrogBot-production` with the target-scoped `FrogBotProduction` physical namespace. Runtime
  `FrogBotProduction_FrogBot-WAhqXM7v63` and gateway
  `frogbotproduction-frogbottools-psxeb1nzdt` reported `READY`; encrypted memory
  `FrogBotProduction_FrogBotMemory-FWrlGD61iY`, all three memory strategies, and the continuous evaluation reported
  `ACTIVE`. Regression dataset version 1 published all five expected examples.
- Deployed Amplify app `d1tu46ki1836w1` and stack
  `amplify-d1tu46ki1836w1-main-branch-6ca713cbb2`. Its public API is
  `https://twrxzanvwg.execute-api.us-east-1.amazonaws.com`; both tracked Swift client configurations now identify the
  environment as `production` and use that API.
- Verified DynamoDB deletion protection and point-in-time recovery, versioned encrypted production storage, 30-day
  customer-key-encrypted AgentCore logs, worker reserved concurrency of 10, five `OK` AgentCore alarms, enabled APNs
  production/sandbox applications with delivery feedback, and a healthy public catalog containing 15 bots, 15 skills,
  and seven built-in tools. The aggregate deployment check remains correctly blocked because the new alarm topic has
  no confirmed accountable subscriber.
- Updated the GitHub production environment with the new Amplify app, generated least-privilege OIDC deployment role,
  production memory key, shared-account safeguard, quotas, APNs applications, Apple team, and AgentCore credentials.
  Human/provider/compliance/device approval flags were deliberately left unset.
- Updated the production Google secret callback metadata to
  `https://twrxzanvwg.execute-api.us-east-1.amazonaws.com/public/oauth/google/callback`. Google and the other provider
  consoles still require their production callback/distribution approvals before public release.
- Created a confirmed, email-verified production identity for the release owner and migrated its durable content from
  the development environment without changing the source account. The verified copy includes 10 bots, 45 direct-chat
  turns, two groups with 124 messages, 28 stored files (21.8 MB), one custom skill, three production-targeted schedules,
  161 AgentCore conversation events, and all 334 extracted long-term memory records. Stale device push tokens, browser
  sessions, usage counters, notification deliveries, and development OAuth credentials were deliberately excluded.
- AgentCore validation, generated CDK tests, 216 runtime tests, and 373 backend tests passed before deployment. The
  TestFlight gate passed the transcription package and macOS application suites. Xcode 26.6's headless runner still
  could not launch the iOS UI suite because its host LLDB registry repeatedly returned
  `DebuggerVersionStore.StoreError` / `no debugger version`, even with the focused UI-test scheme using the non-debug
  launcher. The same scheme completed all 16 iOS UI tests in Xcode on iOS 26.2 with zero failures; the shared scheme
  and its project generator now preserve that non-debug launcher configuration.
- Created production-configured iPhone and Mac archives for version `6.0.0`, build `202609140210`, bundle
  `com.frogbot.app`, and team `GVXC5FQ2RP`. Both archives compiled and signed successfully with the available Apple
  Development identity. The initial command-line export stopped before transmission because Xcode could not use its
  stale signed-in account credentials (`missing Xcode-Token`). After the local Xcode account was refreshed, Organizer
  uploaded both archives to App Store Connect and confirmed `Uploaded to Apple` at 8:45 AM for iPhone and 8:51 AM for
  Mac. Both TestFlight builds are now awaiting Apple's processing.

## 2026-09-13 — production account bootstrap (Lambda quota pending)

- Created the dedicated AWS Organizations member account `820323452649` (`FroggyBot Production`) and bootstrapped
  CDK in `us-east-1` with termination protection. Production deployments use the member account's
  `FroggyBotOrganizationAccessRole`; account-root credentials are not used for application resources.
- Created a rotating customer-managed AgentCore memory key, isolated copies of the configured provider secrets, the
  production Amplify app `d17sj7dvhx07c`, and production/sandbox SNS APNs platform applications for
  `com.frogbot.app`.
- Deployed `AgentCore-FrogBot-production`. Runtime `FrogBot_FrogBot-3pPvmu2ODl` and gateway
  `frogbot-frogbottools-muu7bqevxo` reported `READY`; encrypted memory
  `FrogBot_FrogBotMemory-T17d4eBnCx` reported `ACTIVE`; the evaluator and five-percent online evaluation reported
  `ACTIVE`. The corrected regression dataset source published five examples to the managed draft.
- The first Amplify backend create reached the worker Lambda and then rolled back because AWS assigned the new member
  account only 10 regional concurrent executions. The production worker reserves 10 and Lambda requires additional
  unreserved capacity. Quota request `6c0b66ca52be4a4cbb809df314bb0ecbFAR2XZbA` opened support case
  `178934881900679` for 1,100 concurrent executions; its status remained `CASE_OPENED` at the end of this run.
- Verified the failed create contained no users or table records, removed its failed CloudFormation stack and empty
  retained data artifacts, and scheduled only its three orphaned KMS keys for deletion on 2026-09-20. The production
  AgentCore stack, Amplify app, provider secrets, APNs applications, and APNs delivery logs were preserved.
- Xcode 26.6 recognized Apple team `GVXC5FQ2RP`, bundle `com.frogbot.app`, release version `6.0.0`, and both native
  archive plans. Actual iOS/macOS archives remain gated on a successful production backend so no TestFlight build can
  accidentally embed development client configuration.

## 2026-09-13 — production release-readiness audit (not deployed)

- Made the shared SwiftUI target the production release surface: the controlled workflow no longer requires Expo or
  publishes web output, and a dependent macOS job verifies once before uploading matching iPhone and Mac TestFlight
  builds from the exact production backend configuration.
- Preserved the existing integration work in commit `299359c`, then audited the repository, GitHub controls, current
  AgentCore development state, AWS alarms/logging/budget, and production configuration. No production deployment was
  attempted: the available AWS identity was account root, the production target was not deployed, and required
  production values and accountable external approvals were absent.
- AgentCore validation passed; two evaluator tests, six CDK tests, 216 runtime tests, and 373 backend tests passed.
  Dependency audits reported zero known npm or Python vulnerabilities.
- Shared/web client tests, type checks, lint, Expo Doctor, production-preview exclusion, bundle budgets, and exported
  security-header checks passed. The transcription package's three Swift tests and the macOS app unit suite passed.
  The local iOS UI runner could not launch because Xcode 26.6 repeatedly reported a host LLDB “no debugger version”
  error; the test command is now bounded, and the macOS GitHub runner remains the release gate for that suite.
- The GitHub production environment was restricted to `main`, repository vulnerability alerts were enabled, and CI
  dependency installation/uv/CodeQL artifact handling were repaired. Environment reviewers remain unavailable on the
  current private-repository plan.
- A dedicated production member account (`820323452649`) was created after the audit. Production still fails closed
  until monitored alarms and APNs feedback are verified, provider/compliance/device attestations are complete, and
  the production workflow passes end to end.

## 2026-09-05 — us-east-1

- Forty authenticated bootstrap requests at concurrency eight returned HTTP 200 with zero failures and 2.12-second p99
  latency against the five-second gate.
- A disposable-account workflow passed attachment upload/read, schedule create/run/delete, share create/revoke,
  interactive approval deny and allow-once, cancellation, temporary-bot cleanup, and account deletion.
- DynamoDB point-in-time restore and S3 selected-version restore passed. All temporary recovery resources were removed.
- Budget notifications at 50% and 80% actual spend and 100% forecast were connected to the encrypted service alarm
  topic. A human or incident-system subscription was still pending.
- A synthetic telemetry marker appeared in no CloudWatch event payload. Its corresponding Strands trace events stored
  `[REDACTED]`.
- The work queue and dead-letter queue were empty, disposable identities were removed, and all eight service alarms
  returned to `OK` through their normal evaluation windows.
