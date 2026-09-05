# FroggyBot operations

This runbook defines the initial production targets and the response steps for the current serverless
architecture. Review the targets after 30 days of representative traffic and tighten them from observed
percentiles rather than relaxing them to hide incidents.

## Service objectives

| Signal | Initial objective | Fast incident signal |
| --- | --- | --- |
| Authenticated API availability | At least 99.9% successful Lambda invocations per calendar month | Error rate above 5% for 2 of 3 minutes |
| Authenticated API latency | 99% of Lambda invocations below 5 seconds | p99 above 5 seconds for 2 of 3 minutes |
| Agent completion latency | 95% below 2 minutes and 99% below 5 minutes, excluding a person waiting to approve an interactive action | Worker p99 above 5 minutes for 2 of 3 minutes |
| Queue freshness | 99% of available jobs begin within 5 minutes | Oldest available message above 10 minutes for 2 of 3 minutes |
| Durable job processing | No acknowledged job loss | Any message in the dead-letter queue |
| Capacity | No sustained Lambda throttling | Any throttle in a 3-minute window |

Model-provider refusals, safety filtering, and user cancellations are tracked separately from application
availability. A request counts as successful when FroggyBot durably accepts it and either completes it or
returns an explicit, actionable failure.

## Alarm response

1. Open the FroggyBot CloudWatch dashboard whose name ends in `-health` and confirm which signal breached.
   Do not replay or delete work yet.
2. Check API and worker logs for the same time window and correlate the request, turn, and runtime session
   identifiers. Logs must not contain message bodies, access tokens, or attachment contents.
3. For API errors or latency, check Lambda errors, throttles, downstream DynamoDB/S3 responses, and the
   HTTP API access log status distribution.
4. For worker errors or latency, check queue age, current concurrency, AgentCore runtime state, model errors,
   and the lease state of the affected turn.
5. For dead-letter messages, inspect the failure before redriving. The worker's conditional lease and
   idempotent schedule identifiers make replay safe, but a malformed or permanently unauthorized message
   should be quarantined rather than replayed repeatedly.
6. Record the start time, customer impact, mitigation, root cause, and follow-up owner. Confirm alarms return
   to `OK` after recovery.

## Recovery procedures

### Agent runtime failure

Confirm the AgentCore runtime and `DEFAULT` endpoint are ready. Redeploy from `agentcore/agentcore.json` only;
do not patch generated CDK. Invoke a plain response, then a memory-backed response, before reopening queued
traffic. Existing SQS jobs remain durable while the runtime recovers.

### Worker backlog or dead-letter queue

Resolve the downstream failure first. Confirm the event source is enabled, the worker is not throttled, and
the SQS visibility timeout remains longer than the longest expected attempt. Redrive a small sample and
verify the turn reaches one terminal state before moving the rest. Never copy messages into the work queue by
hand because that bypasses the redrive audit trail.

### DynamoDB data recovery

Point-in-time recovery is enabled. Restore to a new table at a selected timestamp, validate record counts and
ownership keys, then perform a planned application cutover. AWS does not restore a point in time over the
existing table. Keep the original table read-only until the restored service is verified.

### S3 file recovery

The user-file and audit buckets are versioned and retained. Restore only the required object versions after
verifying the owner prefix and file record. Account deletion intentionally removes every version and delete
marker for that user's prefix and is not a recovery path.

Run `scripts/aws-recovery-drill.sh` from the repository root after deployment to exercise both recovery
paths safely. The drill restores DynamoDB into a temporary isolated table and uses only a synthetic S3 key
under `recovery-drills/`; it validates both results and removes the temporary resources when it exits.
If a run is interrupted after its DynamoDB restore was independently validated and removed, set
`FROGBOT_SKIP_DYNAMODB_RESTORE=1` once to resume only the S3 half. Do not use that flag for a normal drill.

### Bad deployment

Use CloudFormation events to identify the first failed resource. For application regressions, redeploy the
last known-good source revision through the normal AgentCore and Amplify commands. Do not rename stateful CDK
constructs or replace DynamoDB/S3 resources during an incident.

## Exercises and evidence

- Monthly: create a disposable direct-chat message and download one generated artifact through the app.
- Quarterly: inject one synthetic SQS failure, verify it reaches the dead-letter queue and alarm topic, fix
  the cause, redrive it, and confirm one terminal result.
- Quarterly: restore DynamoDB to a temporary table and one non-sensitive S3 object version, validate them,
  then remove the temporary recovery resources.
- Before a major release: run the authenticated concurrency test at the agreed traffic target and confirm
  error, latency, throttle, queue-age, and cost signals remain within the objectives above.

The read-only concurrency check is `npm run load:test -- --requests 40 --concurrency 8` from `apps/mobile`.
Supply `FROGBOT_API_URL` and a short-lived `FROGBOT_ACCESS_TOKEN` in the shell; the script never prints or
stores the token. It fails if any request fails or if p99 exceeds five seconds by default. Increase traffic
gradually and keep the API rate limit, downstream capacity, and expected production traffic in view.

The destructive authenticated workflow suite is `npm run workflow:test` from `apps/mobile`. It requires an
isolated Cognito user plus `FROGBOT_API_URL`, `FROGBOT_ID_TOKEN`, and
`FROGBOT_DISPOSABLE_ACCOUNT=1`. It verifies bootstrap, attachment processing, schedules, sharing and
revocation, one-time approval in both directions, cancellation, cleanup, and queued account deletion. Never
point it at a real person's account.

The encrypted alarm topic must have a confirmed operations subscription before a production launch. The
destination is deliberately not hard-coded in the repository; use a monitored team address or incident
system rather than a personal mailbox.

## Latest production verification

Verified in `us-east-1` on 2026-09-05:

- 40 authenticated bootstrap requests at concurrency 8: 40 HTTP 200 responses, zero failures,
  2.12-second p99 against the five-second gate.
- Disposable-account workflow: attachment upload/read, schedule create/run/delete, share create/revoke,
  interactive approval deny and allow-once, cancellation, temporary-bot cleanup, and account deletion passed.
- Recovery: the DynamoDB point-in-time restore became ACTIVE with the expected partition/sort keys; the S3
  selected-version restore matched by SHA-256. All temporary recovery resources were removed.
- Budget: 50% and 80% actual-spend notifications and a 100% forecast notification target the encrypted
  service alarm topic. Human/incident delivery remains pending until an operations destination is supplied.
- Telemetry privacy: a synthetic unique marker completed through the live runtime, appeared in zero
  CloudWatch events, and its three corresponding Strands trace events stored `[REDACTED]` instead.
- Post-test health: the work queue and dead-letter queue were empty, all disposable identities were gone,
  and all eight service alarms returned to `OK` through their normal evaluation windows.
