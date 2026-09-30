# Source account write freeze: operator review draft

**Status: NO-GO. Do not execute this as the cutover freeze yet.** The owner has approved a full-service outage of at
least 90 minutes plus migration checks, with the source retained for rollback. Setting the shared API Lambdas'
reserved concurrency to zero will remove authenticated reads and `/public/catalog` during that outage.
`/public/catalog` itself can refresh the catalog and update the application table on a `GET`, so leaving it available
would not provide a read-only health path. The remaining NO-GO reasons are unproven direct and managed AgentCore Memory
write boundaries, missing disposable denial probes and provider/in-flight evidence, the additional runtime file
bucket, and incomplete executor coverage. No control in this document is currently active.

This runbook covers source account `188757775631` in `us-east-1` only. It does not rename any physical resources. Run
all mutations only inside the announced maintenance window, from the named freeze role, after the owner records the
rollback role and the inventory below. Use the source account role for every command; a destination-account response is
a stop condition. Keep snapshots outside the repository with access limited to the operators. The existing
[cutover plan](account-isolation-cutover-2026-09-25.md) remains the authority for migration and go/no-go decisions.

## Why the paid-work circuit is insufficient

| Source ingress or autonomous writer | State at risk | Required fence |
| --- | --- | --- |
| Authenticated API Lambda | Both DynamoDB tables, files, secrets, schedules, memory, provider calls; `GET /bootstrap` also writes | Request-level gate plus storage fence, or function concurrency zero with a read outage |
| Public API Lambda | Stripe and GitHub webhooks; OAuth and Plaid callbacks are mutating `GET`s; `/public/catalog` can refresh and update catalog metadata | Same; redirect/pause providers and preserve delivery IDs for replay; make any retained catalog read path truly read-only |
| Plaid webhook Lambda | Enqueues sync jobs | Function concurrency zero or signed webhook gate |
| Cognito pre-sign-up Lambda | New Cognito users | Function concurrency zero for new sign-ups; existing sign-in remains independent |
| SQS worker and email sender | Jobs, memory, outbound mail, files, account deletion | Stop producers, drain, disable their event source mappings, then concurrency zero |
| SES receipt rule and email receiver | SES writes the raw message to S3 **before** invoking the receiver | Disable the exact source receipt rule and verify it; fence its bucket if pending mail must remain immutable |
| EventBridge catalog rule, Scheduler group, CloudWatch autofix subscription | New jobs or repository dispatch | Disable schedules, snapshot subscriptions, stop the dispatcher, and account for log-delivery retries |
| Existing upload POST forms | S3 write without another API call for up to **600 seconds** after issue | Object-write Deny on every source customer-file bucket; wait at least 600 seconds and test an existing form |
| Direct AgentCore invocation and active runtime sessions | Runtime S3 objects in a separate source-owned bucket and AgentCore memory events | Deny new invocations on runtime **and** endpoint, drain/stop known sessions, fence its bucket, verify active-session metric and memory counts |
| Direct AgentCore Memory APIs and managed processing | API/worker record edits, events, delayed strategy extraction and event expiry | Deny direct memory mutations on the Memory resource after draining; inventory pending extraction and per-event expiry separately |
| DynamoDB TTL and S3 Lifecycle | Service-driven row deletion, object-version expiration and transition | Disable TTL on both tables and lifecycle on every source customer-state bucket; wait for propagation before final checksums |

The entries above combine repository inspection with **read-only** source-account observations between
2026-09-30 00:08 and 00:17 UTC. The source remains live, so this is not a final freeze attestation. Both DynamoDB TTL settings,
both catalog-related EventBridge rules, the SES receipt rule, and the worker/email queue mappings were still enabled.
The job queue had two delayed messages at 00:08 and one at 00:16. The checked-in source Amplify outputs still name the legacy file bucket,
while the current backend source selects the HeyTim bucket. The deployed AgentCore runtime references a **third
versioned customer-state bucket** outside the Amplify stack (sanitized bucket-name SHA-256 prefix `0726d501433d`).
`HeadBucket` with `ExpectedBucketOwner=188757775631` succeeded, its region is `us-east-1`, and it has one enabled
Lifecycle rule and no replication configuration. A complete read-only listing found **208 versions and 6 delete
markers**: 202 entries under `meme-templates/`, 10 under `users/`, and 2 under `groups/`. Its five distinct `users/`
keys had zero SHA-256 key overlap with the 211 distinct `users/` keys in the HeyTim stack bucket and 149 in the
legacy stack bucket. A read-only, eventually consistent scan of 652 application records and zero invite records
found no value containing this runtime bucket name or an `s3://` URI under it; this does not prove future or external
references absent. The runtime bucket must be included in the versioned migration, freeze, and checksum scope.
The freeze operator must compare **deployed** Lambda environment variables, CloudFormation resources, receipt rules,
queue mappings, runtime ARN/endpoint, Memory resource, and bucket settings with this table. Unknown writer or missing
read permission is NO-GO. Do not assume a Lambda gate blocks
[presigned POSTs](../services/API/amplify/functions/api/attachments.py),
[SES S3 delivery](../services/API/amplify/infrastructure/bot-email.ts), or
[runtime S3 writes](../services/runtime/runtime/heytim_runtime/runtime_jobs.py) or
[memory writes](../services/runtime/runtime/heytim_runtime/memory.py).

## 1. Inventory and reversible snapshots (read-only)

Use a private snapshot directory; record its path, timestamp, role ARN, and SHA-256 of each saved JSON file in the
cutover evidence. Set the actual source profile and backend stack name after confirming them in the console. The stack
name below is a **discovery starting point**, not proof of the currently deployed resources.

```bash
export SOURCE_PROFILE='<source-profile>'
export SOURCE_REGION='us-east-1'
export SOURCE_ACCOUNT='188757775631'
export SOURCE_STACK='amplify-d1tu46ki1836w1-main-branch-6ca713cbb2'
export FREEZE_SNAPSHOT_DIR="$(mktemp -d)"
chmod 700 "$FREEZE_SNAPSHOT_DIR"
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" sts get-caller-identity
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" cloudformation list-stack-resources \
  --stack-name "$SOURCE_STACK" --output json > "$FREEZE_SNAPSHOT_DIR/root-stack.json"
```

Stop unless `Account` is exactly `$SOURCE_ACCOUNT`. Traverse every nested stack in the saved resource list, then record
the **physical** identifiers for the application and invite tables, both Amplify versioned file buckets, the separate
AgentCore runtime file bucket, SES inbound bucket/rule
set, all eight state-capable Lambdas listed above, their SQS queues and mappings, catalog EventBridge rule, Scheduler
group and its schedules, autofix subscription filters, AgentCore runtime, endpoint, and Memory, and provider webhook
endpoints. Compare the live Lambda `Handler`, `Role`, `Environment`, and `LastModified` values to the expected source.
The public availability probe is a ninth Lambda but does not itself write customer state; it calls `/public/catalog`.
Use `describe-table` to check for DynamoDB replicas, and inspect S3 bucket replication and S3 Batch Operations. An
active replication or batch job targeting source customer-state buckets needs its own drain/fence and destination
inventory; the commands below do not cover it.
[S3 replication is asynchronous](https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication.html).

Run `services/runtime/.venv/bin/python scripts/source_writer_preflight.py --profile "$SOURCE_PROFILE"
--stack-name "$SOURCE_STACK" --output "$FREEZE_SNAPSHOT_DIR/source-writer-preflight.json"` from the repository
root. It verifies the exact source account before inventorying, uses only allowlisted read operations, records
sanitized hashes/counts, and exits `2` for NO-GO. Treat its report as a checklist of observed blockers, never as
cutover approval; preserve the full private configuration snapshots separately.

Save these responses **before** changing anything. A missing resource or error must be explained, not silently
treated as an empty setting:

```bash
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" dynamodb describe-table \
  --table-name '<physical-table-name>' --output json
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" dynamodb describe-time-to-live \
  --table-name '<physical-table-name>' --output json
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" dynamodb get-resource-policy \
  --resource-arn '<physical-table-arn>' --output json
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" s3api get-bucket-versioning \
  --bucket '<physical-bucket-name>' --expected-bucket-owner "$SOURCE_ACCOUNT"
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" s3api get-bucket-policy \
  --bucket '<physical-bucket-name>' --expected-bucket-owner "$SOURCE_ACCOUNT"
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" s3api get-bucket-lifecycle-configuration \
  --bucket '<physical-bucket-name>' --expected-bucket-owner "$SOURCE_ACCOUNT"
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" s3api get-bucket-replication \
  --bucket '<physical-bucket-name>' --expected-bucket-owner "$SOURCE_ACCOUNT"
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" s3control list-jobs \
  --account-id "$SOURCE_ACCOUNT"
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" lambda get-function-concurrency \
  --function-name '<physical-function-name>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" lambda list-event-source-mappings \
  --function-name '<physical-function-name>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" sqs get-queue-attributes \
  --queue-url '<physical-source-queue-url>' \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible ApproximateNumberOfMessagesDelayed
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" events describe-rule \
  --name '<catalog-refresh-rule-name>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" scheduler list-schedules \
  --group-name '<physical-task-schedule-group>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" scheduler get-schedule \
  --group-name '<physical-task-schedule-group>' --name '<each-schedule-name>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" ses describe-active-receipt-rule-set
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" ses describe-receipt-rule \
  --rule-set-name '<active-source-rule-set>' --rule-name '<source-bot-inbox-rule>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" logs describe-subscription-filters \
  --log-group-name '<each-autofix-source-log-group>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" bedrock-agentcore-control get-resource-policy \
  --resource-arn '<source-runtime-or-endpoint-or-memory-arn>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" bedrock-agentcore-control get-memory \
  --memory-id '<source-memory-id>' --view full
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" bedrock-agentcore list-memory-extraction-jobs \
  --memory-id '<source-memory-id>'
```

`get-resource-policy`, `get-bucket-policy`, `get-bucket-lifecycle-configuration`, or `get-bucket-replication` may return
a documented not-found error when no setting exists. Record that specific absence and restore **absence** on thaw. Save complete
responses, not only a status field. [Scheduler updates replace omitted optional fields](https://docs.aws.amazon.com/scheduler/latest/UserGuide/managing-schedule-state.html), so a schedule must be restored from its full saved `get-schedule` response after converting it to valid update input.

## 2. Prepare the source before the final snapshot

1. Disable TTL on **both** physical source tables using their captured attribute names (currently `expiresAt`), then
   poll `describe-time-to-live` to `DISABLED` and wait another **30 minutes**. AWS says a TTL change may take up to one
   hour and deletes can continue for about 30 minutes after disablement. Treat `DISABLING`, an API error, or another
   TTL update within the one-hour change window as NO-GO. [AWS TTL procedure](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/time-to-live-ttl-how-to.html).
   Reserve at least **90 minutes from the disable requests** before the earliest final digest, and extend the window
   if either table reaches `DISABLED` later than one hour. Disabling TTL while the service is still live is not
   preapproved: quota/admission and idempotency records may depend on physical expiry, and retaining expired rows
   changes retention behavior. Review those readers and retention obligations before moving this step outside the
   maintenance window.

   ```bash
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" dynamodb update-time-to-live \
     --table-name '<physical-table-name>' \
     --time-to-live-specification Enabled=false,AttributeName=expiresAt
   ```

2. Save the full S3 Lifecycle configuration for the legacy, HeyTim, and separate AgentCore runtime **versioned**
   source file buckets and for the SES inbound bucket if it exists. Change every rule's `Status` from `Enabled` to `Disabled`, retaining all other
   fields, with `put-bucket-lifecycle-configuration`; read back every rule. AWS says propagation has a delay and
   disabling a rule unschedules queued actions. Do not start the final version inventory until the disabled settings
   have propagated and two inventories agree. [AWS lifecycle behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/how-to-set-lifecycle-configuration-intro.html).

   ```bash
   jq '.Rules |= map(.Status = "Disabled")' '<saved-bucket-lifecycle.json>' > '<disabled-bucket-lifecycle.json>'
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" s3api put-bucket-lifecycle-configuration \
     --bucket '<physical-bucket-name>' --expected-bucket-owner "$SOURCE_ACCOUNT" \
     --lifecycle-configuration file://'<disabled-bucket-lifecycle.json>'
   ```

3. Disable the source catalog-refresh **and public-availability** EventBridge rules, then disable **each** live Scheduler schedule in the task
   group. Build each `update-schedule` request from its saved `get-schedule` result, preserving `Target`,
   `FlexibleTimeWindow`, `ScheduleExpression`, and every populated optional field; set only `State=DISABLED`.
   Re-read every schedule and confirm the target and expression did not change. Do not disable unrelated schedules.

   ```bash
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" events disable-rule \
     --name '<catalog-refresh-rule-name>'
   jq '{Name,GroupName,ScheduleExpression,FlexibleTimeWindow,Target,
        ActionAfterCompletion,Description,EndDate,KmsKeyArn,
        ScheduleExpressionTimezone,StartDate,State:"DISABLED"}
       | with_entries(select(.value != null))' \
     '<saved-get-schedule.json>' > '<disabled-update-schedule.json>'
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" scheduler update-schedule \
     --cli-input-json file://'<disabled-update-schedule.json>'
   ```

4. Disable the **specific active** SES bot-inbox receipt rule by submitting the complete saved `Rule` with only
   `Enabled=false`, then verify `describe-receipt-rule`. SES writes mail to S3 before the email receiver Lambda runs;
   stopping that Lambda alone is insufficient. Record provider delivery and bounce/replay handling before this step.
   [SES receipt rule API](https://docs.aws.amazon.com/cli/latest/reference/ses/update-receipt-rule.html).

   ```bash
   jq '.Rule | .Enabled = false' '<saved-describe-receipt-rule.json>' > '<disabled-receipt-rule.json>'
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" ses update-receipt-rule \
     --rule-set-name '<active-source-rule-set>' --rule file://'<disabled-receipt-rule.json>'
   ```

5. Stop new application admissions. Until a request-level gate is deployed and tested, the only known complete Lambda
   ingress shutoff is `put-function-concurrency --reserved-concurrent-executions 0` for authenticated API, public API,
   Plaid webhook, Cognito pre-sign-up, email receiver, and autofix dispatcher. Save each function's prior concurrency
   value **or lack of a limit** first. Confirm zero with `get-function-concurrency`. This deliberately causes an API
   read/health outage and may produce provider retries. The owner approved this bounded outage; record its start and
   expected end before making changes. [Lambda concurrency behavior](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html).

   ```bash
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" lambda put-function-concurrency \
     --function-name '<one-verified-source-function>' --reserved-concurrent-executions 0
   ```

6. Let the main job queue and outbound email queue drain. Check SQS visible, in-flight, and delayed counts; inspect
   worker and sender `ConcurrentExecutions`, failures, DLQs, and unfinished background work. Then disable their SQS
   event source mappings and set their reserved concurrency to zero. An event source mapping with `Enabled=false`
   pauses polling; setting concurrency zero first can create retries or DLQ churn. [Event source mapping API](https://docs.aws.amazon.com/cli/latest/reference/lambda/update-event-source-mapping.html).

   ```bash
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" lambda update-event-source-mapping \
     --uuid '<verified-main-or-email-queue-mapping-uuid>' --no-enabled
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" lambda get-event-source-mapping \
     --uuid '<verified-main-or-email-queue-mapping-uuid>'
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" lambda put-function-concurrency \
     --function-name '<worker-or-email-sender-function>' --reserved-concurrent-executions 0
   ```

7. Block new direct AgentCore invocations at both the source runtime and endpoint with reviewed resource-policy Deny
   statements for `bedrock-agentcore:InvokeAgentRuntime*` (including direct, user-scoped, command, and WebSocket
   invocation actions). Snapshot the exact preexisting policies first and merge the Deny without dropping any other
   statement. AgentCore resource policies are independently evaluated on runtime and endpoint, and
   `StopRuntimeSession` stops only a known session; it is not an account-wide pause. A denied-invocation probe and
   active-session drain procedure must be exercised in a disposable environment; do not invoke the production
   runtime merely to test the fence. Review runtime-specific invocation traces, known session IDs, and
   `ActiveSessionCount` after the Deny. [AgentCore policy behavior](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html),
   [session stop](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-stop-session.html).

8. Add reviewed, temporary **object-write Deny** statements to all three versioned source file bucket policies,
   including the bucket selected by the live AgentCore runtime. Include
   `s3:PutObject*`, `s3:DeleteObject*`, `s3:AbortMultipartUpload`, and `s3:RestoreObject` on the bucket object ARNs.
   Merge with the saved policies; never replace their encryption/TLS controls. This must reject an already issued
   presigned POST even though its form has not expired. Independently wait 600 seconds after the last API admission,
   then verify no object versions appeared. Exercise a valid presigned-form denial **only in a disposable copy**;
   a production `PutObject` test can create a version if its expected key disappears before the request is checked.
   On the source, read back the exact policy, verify ordinary reads still work, and compare repeated version
   inventories. If the SES bucket contains retained mail, fence its object writes only after the receipt rule is
   disabled and all accepted notifications have drained.

9. After application workers are drained, add reviewed, temporary **data-write Deny** statements to both DynamoDB
   table resource policies. Cover `PutItem`, `UpdateItem`, `DeleteItem`, `BatchWriteItem`, and the three
   `PartiQLInsert/Update/Delete` actions. DynamoDB transactions authorize their contained Put/Update/Delete actions;
   `TransactWriteItems` is an API name, **not** a standalone IAM action. Preserve any existing policy and its
   revision, use `ExpectedRevisionId` when replacing it, and verify that an impossible-condition write receives
   `AccessDeniedException` rather than `ConditionalCheckFailedException`. A conditional failure means the Deny was
   not yet effective. Read back the policy and retry probes after propagation.
   [DynamoDB action mapping](https://docs.aws.amazon.com/service-authorization/latest/reference/list_dynamodb.html),
   [policy consistency](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_GetResourcePolicy.html).

   ```bash
   aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" dynamodb put-item \
     --table-name '<physical-app-table>' \
     --item '{"pk":{"S":"SYSTEM#FREEZE_PROBE"},"sk":{"S":"NO_WRITE"}}' \
     --condition-expression 'attribute_exists(pk) AND attribute_not_exists(pk)'
   ```

10. Add a reviewed **Memory mutation Deny** to the exact source AgentCore Memory resource after the runtime and
    workers are drained. It must cover `CreateEvent`, `DeleteEvent`, single and batch record mutations,
    `StartMemoryExtractionJob`, and resource updates/deletion without removing existing policy statements. The API and worker have direct Memory
    permissions; a Runtime-only Deny does not stop those callers. Preserve read and list actions for migration.
    This Deny does **not** stop built-in strategy extraction, expiration of existing events, or the newer
    `IngestData` API until its resource-policy enforcement has been verified. Test the policy and
    a denied direct Memory write in a disposable environment before source use. Snapshot the live `GetMemory`
    response, its strategies and event expiry; the checked-in configuration uses semantic, summarization, and user
    preference strategies with 30-day event expiry. [AgentCore Memory policy actions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html),
    [managed extraction](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-strategies.html).

11. Capture the final source records and all current **and noncurrent** versions and delete markers from all three versioned
    file buckets, plus the SES inbound bucket's current objects. Preserve object tags, sizes, content checksums, and a
    source-to-destination version map. Repeat strongly consistent DynamoDB base-table scans and canonical-record digests
    and `ListObjectVersions` inventory after a quiet interval and immediately before copying. Counts or hashes that
    move are NO-GO even if the preceding controls appear applied. Repeat the AgentCore actor/session/event/record
    inventory, and check its `ActiveSessionCount` (an account-level, one-minute gauge), invocation logs, and memory
    events for activity. `SessionCount` is cumulative and cannot prove no active sessions. Check pending Memory
    extraction jobs and repeat record IDs and content digests after processing settles. Job listings alone may not
    expose all built-in processing. Existing raw events have a
    fixed expiry applied when written; changing `eventExpiryDuration` cannot extend them. If an event may expire
    during capture/transfer or managed extraction may still create a record, there is no stable memory snapshot and
    this cutover remains NO-GO. [Memory event expiry](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-create-a-memory-store.html),
    [AgentCore metrics](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html).

### Policy statements to review before the window

These are the statements to **append** to the policy already on each exact resource. They are not complete replacement
policies. Use a unique `Sid` once per resource, preserve every existing statement, and read back after each write. If
the original resource had no policy, start from `{"Version":"2012-10-17","Statement":[]}` and record that the
original state was absent. A policy change is not a substitute for the drain and service-managed TTL/Lifecycle steps.

```json
{
  "Sid": "HeyTimSourceWriteFreeze",
  "Effect": "Deny",
  "Principal": "*",
  "Action": [
    "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem",
    "dynamodb:BatchWriteItem", "dynamodb:PartiQLInsert",
    "dynamodb:PartiQLUpdate", "dynamodb:PartiQLDelete"
  ],
  "Resource": "<one-exact-source-table-arn>"
}
```

```json
{
  "Sid": "HeyTimSourceWriteFreeze",
  "Effect": "Deny",
  "Principal": "*",
  "Action": ["s3:PutObject*", "s3:DeleteObject*", "s3:AbortMultipartUpload", "s3:RestoreObject"],
  "Resource": "arn:aws:s3:::<one-exact-source-bucket>/*"
}
```

```json
{
  "Sid": "HeyTimSourceWriteFreeze",
  "Effect": "Deny",
  "Principal": "*",
  "Action": "bedrock-agentcore:InvokeAgentRuntime*",
  "Resource": "<one-exact-runtime-or-runtime-endpoint-arn>"
}
```

```json
{
  "Sid": "HeyTimSourceWriteFreeze",
  "Effect": "Deny",
  "Principal": "*",
  "Action": [
    "bedrock-agentcore:UpdateMemory", "bedrock-agentcore:DeleteMemory",
    "bedrock-agentcore:CreateEvent", "bedrock-agentcore:DeleteEvent",
    "bedrock-agentcore:DeleteMemoryRecord",
    "bedrock-agentcore:BatchCreateMemoryRecords",
    "bedrock-agentcore:BatchUpdateMemoryRecords",
    "bedrock-agentcore:BatchDeleteMemoryRecords",
    "bedrock-agentcore:StartMemoryExtractionJob"
  ],
  "Resource": "<exact-source-memory-arn>"
}
```

For each prepared complete policy document, the apply calls are:

```bash
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" dynamodb put-resource-policy \
  --resource-arn '<exact-source-table-arn>' --policy file://'<reviewed-complete-table-policy.json>' \
  --expected-revision-id '<saved-revision-id-or-NO_POLICY>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" s3api put-bucket-policy \
  --bucket '<exact-source-bucket>' --expected-bucket-owner "$SOURCE_ACCOUNT" \
  --policy file://'<reviewed-complete-bucket-policy.json>'
aws --profile "$SOURCE_PROFILE" --region "$SOURCE_REGION" bedrock-agentcore-control put-resource-policy \
  --resource-arn '<exact-runtime-or-endpoint-or-memory-arn>' \
  --policy file://'<reviewed-complete-agentcore-policy.json>'
```

Use the literal `NO_POLICY` expected revision when DynamoDB had no prior policy; this conditionally creates the
policy only if absence still holds. [DynamoDB conditional policy writes](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_PutResourcePolicy.html).
On thaw, use the **current** revision ID to
replace the temporary DynamoDB policy with the saved complete policy, or call `delete-resource-policy` when its saved
state was absent. Restore a saved S3/AgentCore policy with `put-*`; remove the temporary policy only when the saved
state was absent. First compare the current document to the reviewed freeze document; stop on unrelated drift.

## 3. Thaw, rollback, and retention

On a **successful** destination cutover, leave the source read-only for the approved 30-day rollback window. Do not
reenable source TTL or S3 Lifecycle merely because destination traffic works. Preserve all snapshots and denied
provider delivery IDs. Source cleanup is a separate decision.

On rollback, reconcile any destination writes first, then restore saved source controls in this order: remove only
the temporary DynamoDB and S3 Deny statements (compare the current policies with the saved policy plus the known
freeze statement; abort on unrelated drift); restore existing policies exactly or remove policies that were absent;
restore the AgentCore runtime, endpoint, and Memory policies; restore each original Lambda concurrency value or delete the
temporary limit when none existed; reenable the two SQS mappings according to their saved `Enabled` states; restore
the SES rule and EventBridge/Scheduler states; restore each saved lifecycle configuration; reenable TTL only on tables
where it was originally enabled, after the prior one-hour TTL update window permits it. Verify each readback before
opening the next ingress. Restore provider webhook routing/delivery only when the source can accept it, and replay
missed deliveries by provider event ID with idempotency checks. Run authenticated read/write, webhook, queue, memory,
and object-version smoke checks; record any duplicate or lost work.

## Unresolved approval and proof items

- The approved outage will make the shared API, authenticated reads, and `/public/catalog` unavailable. The catalog's
  `GET` path calls `sync_official()` through `refresh_on_read` and can write a sync lease and metadata, so it must be
  stopped with the other API ingress. Adjust maintenance monitoring and user/provider notices to this full outage.
- The point-in-time read-only source inventory above is incomplete as a freeze attestation. The source has continued
  changing, the AgentCore runtime bucket sits outside the Amplify stack, and provider delivery/retry state and active
  runtime sessions still need independent evidence.
- The policy Deny templates, policy revision handling, preexisting presigned-form denial, provider retry windows,
  AgentCore direct-invocation denial, and direct Memory mutation denial have not been exercised in a disposable copy.
  A failed denial probe is NO-GO.
- No CLI list of active AgentCore **runtime** sessions was found. Use runtime-specific invocation traces plus
  `ActiveSessionCount`, known session IDs, and a long enough quiet window; if that cannot prove no in-flight or
  background task, do not take the final memory snapshot.
- Existing Memory events expire on their original schedule, and managed strategy extraction/consolidation can change
  long-term records after the last `CreateEvent`. The temporary Memory policy does not pause either service process.
  Confirm every event expiry timestamp and extraction job state against the transfer interval, and obtain stable
  repeated event/record inventories. If AWS offers no reliable settled signal for built-in processing, treat that as
  an unresolved source snapshot boundary rather than assuming a quiet interval guarantees completion.
- AgentCore's `IngestData` can submit content directly for long-term record generation. Its action is absent from the
  current resource-policy supported-action list, so the Memory Deny template cannot be claimed to fence it. Prove no
  source principal can call `IngestData` through IAM or a tested resource policy before treating Memory as frozen.
  A possible fallback is a complete effective-principal inventory and a tested temporary identity/SCP-level explicit
  Deny, combined with drained runtime/API/worker work, CloudTrail evidence of no new admissions, zero active
  extraction jobs, and repeated stable event/record digests. This is not approved or proven. Verify every existing
  event's expiry against the full transfer window; a reported next expiry more than four days away is not by itself a
  settled-memory signal.
  [IngestData API](https://docs.aws.amazon.com/cli/latest/reference/bedrock-agentcore/ingest-data.html),
  [Memory resource-policy actions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html).
- The live source inventory must show whether DynamoDB replicas, S3 replication, S3 Batch jobs, or any other
  autonomous writer are active. The current commands do not fence those paths; any present path is NO-GO until a
  resource-specific drain, snapshot, and denial procedure has been reviewed.
- Confirm that source table backups/exports, all three versioned bucket histories, the SES inbound bucket's pending mail,
  and every TTL/lifecycle exclusion match the approved migration scope before treating a stable digest as complete.
- `scripts/source_freeze_executor.py` currently rehearses staged controls and reverse-order restore with fixtures only;
  it refuses source-account mutation and has no production AWS mutation adapter. A reviewed adapter, private snapshots,
  readback/propagation handling, denial probes, and the independent Memory fallback are required before source use.
