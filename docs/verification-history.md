# FroggyBot verification history

This file records dated checks against deployed environments. It is evidence from a point in time, not a statement that
the current checkout or environment still has the same status.

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
