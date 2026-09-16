# FroggyBot operations

This runbook defines service objectives and response steps for the current serverless architecture. Declarative
`development` and `production` AgentCore targets exist. Production temporarily uses management account
`188757775631` while the dedicated member account's Lambda quota request is pending, with target-scoped resources kept
separate. Treat these objectives as production launch gates until the
production deployment, authenticated end-to-end checks, alert subscription, and recovery drill are complete.
Review them after 30 days of representative
traffic and tighten them from observed percentiles rather than relaxing them to hide incidents.

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

## Provider-usage admission controls

The API and worker reserve product-funded provider capacity before starting paid work. One direct turn costs one
run unit; a coordinated group round atomically reserves one unit for every planned bot reply; and creation of a
new remote browser session costs one unit. Refreshing an existing live browser session costs no additional unit.
A durable admission marker makes API/SQS retries, scheduled retries, direct background continuations, and
uncertain browser starts idempotent. This is the quota and circuit-breaker foundation only—it is not payment
checkout, subscription accounting, or an invoice ledger.

The Amplify backend validates these deployment environment settings and passes them to both API and worker
functions:

| Setting | Default | Allowed range | Meaning |
| --- | ---: | ---: | --- |
| `FROGBOT_MONTHLY_RUN_UNIT_LIMIT` | 1,000 | 1–1,000,000 | Maximum run units admitted for one billing user in a UTC calendar month |
| `FROGBOT_USER_WINDOW_RUN_UNIT_LIMIT` | 30 | 1–10,000 | Maximum run units admitted for one billing user in a short fixed window |
| `FROGBOT_GLOBAL_WINDOW_RUN_UNIT_LIMIT` | 300 | 1–100,000 | Maximum run units admitted across the service in that fixed window |
| `FROGBOT_USAGE_WINDOW_SECONDS` | 60 | 10–3,600 | Fixed-window duration in seconds |
| `FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT` | 100 | 3–1,000,000 | Maximum conservative YouTube tool-call capacity FroggyBot may reserve per Pacific-time quota day |

YouTube access has a separate provider budget. Before every runtime session with public search or a connected
YouTube channel, the worker atomically reserves three calls from the shared Pacific-time daily counter. The lease is
idempotent for retries, is fenced against account deletion, and is passed to the runtime; the runtime blocks
a fourth metered YouTube call or any call after that Pacific date changes. Reservations are intentionally conservative:
unused calls are not returned, so the default 100-call provider allocation admits at most 33 such runtime
sessions. Before publishing Creator Studio or Trend Scout, verify the production Google project's current
[Search Queries quota](https://developers.google.com/youtube/v3/docs/search/list), raise it for launch traffic,
and set `FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT` no higher than the verified provider limit. Video-details and
comment reads, plus connected channel and upload-list reads, use YouTube's general endpoint quota, so verify that
bucket as well before raising the allocation. The application counter is intentionally conservative and treats each
public search or connected-channel tool invocation as one reserved call even when the underlying quota costs differ.

To stop new paid-work admissions and later continuation invocations manually, write this item to the main
DynamoDB data table identified by the Amplify `dataTableName` output. No secret value is involved:

```json
{
  "pk": "SYSTEM#USAGE_CONTROL",
  "sk": "CIRCUIT#PROVIDER",
  "entity": "USAGE_CIRCUIT",
  "open": true
}
```

The worker reads this exact key with `ConsistentRead=true`, checks it inside the atomic admission transaction,
and checks it again before reusing an admission for a later group reply or background continuation. Set `open`
to `false` or delete the item to reopen admission. A denied run is saved as a readable terminal error and is not
retried; a group denial finalizes the rest of the round without another provider invocation. The circuit does not
interrupt a provider request or AgentCore runtime invocation that is already in flight. A retry may reconcile the
same idempotent browser-session start so a remotely created session is not orphaned, but it cannot create a second
session or consume another run unit.

The AgentCore runtime also enforces in-process dispatch caps before paid provider calls:

| Setting | Default | Allowed range | Meaning |
| --- | ---: | ---: | --- |
| `FROGBOT_MAX_MODEL_CALLS_PER_RUNTIME_RUN` | 24 | 1–100 | OpenRouter model attempts, including retry and fallback dispatches |
| `FROGBOT_MAX_PROVIDER_TOOL_CALLS_PER_RUNTIME_RUN` | 24 | 1–100 | Combined metered AgentCore Gateway and OpenRouter image tool dispatches |
| `FROGBOT_MAX_IMAGE_CALLS_PER_RUNTIME_RUN` | 2 | 1–10 | OpenRouter image-generation dispatches within the combined tool cap |

Each valid YouTube quota lease has a fixed three-call ceiling across public search and connected-channel tools in
addition to the combined tool cap.

These runtime caps terminate the current AgentCore invocation with a user-readable error rather than dispatching
the over-limit call. A later backend continuation is a separate runtime invocation and therefore gets a fresh
in-process budget. Cross-invocation dollar ceilings require a durable provider ledger and are intentionally not
claimed by this phase.

## Alarm response

1. Open the FroggyBot CloudWatch dashboard whose name ends in `-health` and confirm which signal breached.
   Do not replay or delete work yet.
2. Check API and worker logs for the same time window and correlate the request, turn, and runtime session
   identifiers. Logs must not contain message bodies, access tokens, or attachment contents.
3. For API errors or latency, check Lambda errors, throttles, downstream DynamoDB/S3 responses, and the
   HTTP API access log status distribution.
4. For worker errors or latency, check queue age, current concurrency, AgentCore runtime state, model errors,
   and the lease state of the affected turn.
5. For AgentCore alarms, inspect the `AWS/Bedrock-AgentCore` runtime or gateway `Resource` dimension, then
   correlate `SystemErrors`, `Throttles`, `Invocations`, and p99 `Latency` with the app request/session IDs.
6. For dead-letter messages, inspect the failure before redriving. The worker's conditional lease and
   idempotent schedule identifiers make replay safe, but a malformed or permanently unauthorized message
   should be quarantined rather than replayed repeatedly.
7. Record the start time, customer impact, mitigation, root cause, and follow-up owner. Confirm alarms return
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

The read-only concurrency check is `npm run load:test -- --requests 40 --concurrency 8` from `services/API`.
Supply `FROGBOT_API_URL` and a short-lived `FROGBOT_ACCESS_TOKEN` in the shell; the script never prints or
stores the token. It fails if any request fails or if p99 exceeds five seconds by default. Increase traffic
gradually and keep the API rate limit, downstream capacity, and expected production traffic in view.

The destructive authenticated workflow suite is `npm run workflow:test` from `services/API`. It requires an
isolated Cognito user plus `FROGBOT_API_URL`, `FROGBOT_ID_TOKEN`, and
`FROGBOT_DISPOSABLE_ACCOUNT=1`. It verifies bootstrap, attachment processing, schedules, sharing and
revocation, one-time approval in both directions, cancellation, cleanup, and queued account deletion. Never
point it at a real person's account.

The encrypted alarm topic must have a confirmed operations subscription before a production launch. The
destination is deliberately not hard-coded in the repository; use a monitored team address or incident
system rather than a personal mailbox.

## Verification evidence

Keep dated deployment and recovery results in [verification-history.md](verification-history.md). This runbook defines
the checks and response procedures; it does not imply that a historical result describes the current deployment.
