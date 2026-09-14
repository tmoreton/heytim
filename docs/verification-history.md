# FroggyBot verification history

This file records dated checks against deployed environments. It is evidence from a point in time, not a statement that
the current checkout or environment still has the same status.

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
