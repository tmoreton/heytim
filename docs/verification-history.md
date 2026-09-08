# FroggyBot verification history

This file records dated checks against deployed environments. It is evidence from a point in time, not a statement that
the current checkout or environment still has the same status.

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
