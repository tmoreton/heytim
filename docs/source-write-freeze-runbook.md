# Source account write freeze: operator review draft

**Status: NO-GO. Do not execute this as the cutover freeze yet.** The owner has approved a full-service outage of at
least 90 minutes plus migration checks, with the source retained for rollback. Setting the shared API Lambdas'
reserved concurrency to zero will remove authenticated reads and `/public/catalog` during that outage.
`/public/catalog` itself can refresh the catalog and update the application table on a `GET`, so leaving it available
would not provide a read-only health path. The remaining NO-GO reasons are the unproven managed AgentCore Memory
snapshot boundary, source installation of the tested direct-write fence, missing other disposable denial probes and
provider/in-flight evidence, the additional runtime file
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

The two auxiliary buckets in the source Amplify stack were classified read-only on
2026-09-30. `AuditLogs` is the active multi-region CloudTrail destination with
log-file validation; its checked-in retention is seven years, so it must keep
receiving audit records and remain in the source account through its retention
obligation. `HeyTimGatewaySchemas` contains two versioned, deployment-owned
OpenAPI schema objects under `releases/skills-v33/`, for X and YouTube. Neither
bucket is an application user-file or raw-mail migration source. Keep the
preflight's auxiliary-bucket review blocker until the live trail binding,
schema key inventory, and ownership are rechecked at the actual freeze; do not
fence the audit trail just to make the customer-state digest stable.

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

For an exact-account read-only settings capture, run this within 15 minutes of that preflight:

```bash
services/runtime/.venv/bin/python scripts/source_freeze_capture.py \
  --profile "$SOURCE_PROFILE" --stack-name "$SOURCE_STACK" \
  --preflight "$FREEZE_SNAPSHOT_DIR/source-writer-preflight.json" \
  --snapshot "$FREEZE_SNAPSHOT_DIR/source-freeze-snapshot.json"
```

It discovers physical IDs,
checks them against the sanitized evidence, and writes a mode-0600 snapshot only after every setting is readable.
The current source AgentCore Memory `GetResourcePolicy` returns HTTP 200 without a `policy` field. A disposable
destination drill proved that the same response after deleting a Memory policy means no policy is attached. The
capture accepts it as absence only when `GetMemory` independently returns the exact expected ID and ARN in `ACTIVE`
state; a 404 or identity/status mismatch remains NO-GO.

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

### Source Memory retention and extraction evidence (read-only)

On 2026-09-30, exact-account checks found the source Memory `ACTIVE` with three active strategies and
`eventExpiryDuration=30`. Its `createdAt` is 2026-09-25 01:37:26 UTC, and its `updatedAt` is one second later.
The 90-day CloudTrail management-event history
contained one successful `CreateMemory` for that exact Memory ID with a 30-day expiry request and no `UpdateMemory`
since creation. [AWS applies expiry at each event's write time](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-create-a-memory-store.html).
An event in this Memory could not have been written before the resource existed, so **2026-10-25 01:37:26 UTC is a
conservative lower bound on its first possible raw-event expiry** at this observed configuration. Recheck the exact
creation event, all subsequent `UpdateMemory` events, live `GetMemory` configuration, and the remaining margin before
the maintenance window. If the creation history is absent, any update shortened retention, or the margin cannot cover
capture, retry, and verification, treat raw-event preservation as NO-GO. Do not estimate expiry from
`eventTimestamp`: some source events have timestamps earlier than this Memory's creation and were therefore backdated.

The same read-only inventory found 4 actors, 16 sessions, 192 events, and 417 long-term records; destination Memory
was empty. The Cognito/DynamoDB-backed identity generator mapped all 4 actors and 16 sessions, including the reviewed
one orphan actor and two historical sessions. These are point-in-time counts, not the final frozen inventory. Source
`ListMemoryExtractionJobs` returned zero jobs, but that API lists jobs eligible for re-drive, chiefly failed jobs; it
does **not** enumerate in-progress built-in extraction or prove that record consolidation has finished.
[AWS describes built-in extraction as automatic](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-strategies.html),
and [the extraction-job API's scope](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_ListMemoryExtractionJobs.html)
is narrower than a completion barrier.

### Strict no-loss path for delayed managed records (not deployed)

An [existing Memory can be updated with a stream delivery resource](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_UpdateMemory.html),
and the exact source Memory already has an execution role and is not managed by another AgentCore resource. Its
`streamDeliveryResources` is currently absent. The supported destination is **Kinesis Data Streams only**, with at most
one stream configuration; S3 is not a direct Memory record-stream destination. `FULL_CONTENT` sends record creation
and update content, while deletion events carry the record ID. Built-in extraction and consolidation can cause those
events after direct client writes are fenced.
[Memory record streaming](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-record-streaming.html).

Before this path can clear the gate, deploy an encrypted source Kinesis stream and least-privilege Memory execution-role
permission, attach it to the exact source Memory **before** the write freeze, and verify activation and delivery in a
disposable drill. A consumer must durably archive the full-content change stream in an encrypted, versioned store and
checkpoint each Kinesis shard. Build and test idempotent create/update/delete reconciliation into destination Memory
using the migration's source-to-destination record map, including changes while destination begins creating its own
records. Cross-check stream delivery metrics and terminal-failure logs; any publication failure, missing checkpoint,
unreconciled change, or source/destination full-state mismatch is NO-GO. Keep the source Memory and archive for the
rollback period and continue reconciliation after traffic moves, because managed extraction may finish late. Attaching
the stream changes source Memory configuration: redo the CloudTrail retention-history check afterward and ensure the
update did not change `eventExpiryDuration`.

This is a design for the missing capture/replay path, **not current cutover evidence**. AWS's published streaming guide
does not state an upper bound on built-in extraction delay or an end-of-processing marker, and does not specify
end-to-end ordering or at-least-once delivery for Memory-to-Kinesis publication. Source Memory has no configured
application-log delivery either; [those logs can report extraction/consolidation start and completion](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-memory-metrics.html)
only after they are enabled. A bounded quiet interval, stream metrics, and parity together can verify observed state;
they cannot by themselves certify that no future managed write exists. Operate the tested source-to-destination
reconciler while the source is retained, and require AWS service assurance of a completion condition or a separately
reviewed bound before retiring it. Do not mark strict no-loss complete merely because a Kinesis stream has been
configured.

The bounded [source Memory capture stack and validator](../infrastructure/memory-capture/README.md) are prepared but
not deployed. They archive the exact Kinesis payload before Lambda checkpoints it and compare all retained parent
and child shard records to S3. Deploy and attach `FULL_CONTENT` streaming **before** the final source snapshot,
then use overlapping scans before Kinesis retention expires. The existing initial Memory migration tool has no
late-change reconciler; that component must map record identities and handle creates, updates, and deletes before a
traffic cutover can be called reconciled. Moving public traffic is a separate decision from retiring source Memory:
traffic may move only with a tested ongoing reconciler, fully copied frozen snapshot, repeated observed parity,
live capture and alerts, and an assigned operator continuing checks after the move. The source Memory and archive
must remain available beyond the 30-day raw-event horizon while late processing remains possible. If strict no-loss
remains a requirement, traffic cutover is **NO-GO** without AWS-backed delivery and completion assurance. An explicit
owner decision may accept the residual risk under an observed-parity standard, but does not establish strict no-loss.
A quiet interval is never a source-retirement criterion.

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
    workers are drained. It must cover `CreateEvent`, `IngestData`, `DeleteEvent`, single and batch record mutations,
    `StartMemoryExtractionJob`, and resource updates/deletion without removing existing policy statements. The API and worker have direct Memory
    permissions; a Runtime-only Deny does not stop those callers. Preserve read and list actions for migration.
    A disposable destination Memory drill on September 29 verified that valid `CreateEvent` and `IngestData` calls
    succeeded before an exact-resource, wildcard-principal Deny and both returned `AccessDeniedException` afterward.
    This Deny does **not** stop built-in strategy extraction or expiration of existing events. If
    `GetResourcePolicy` returns HTTP 200 without a `policy` field, interpret that as policy absence only after
    `GetMemory` confirms the same exact ID and ARN in `ACTIVE` state; a 404 remains fatal. Snapshot the live `GetMemory`
    response, its strategies and event expiry; the checked-in configuration uses semantic, summarization, and user
    preference strategies with 30-day event expiry. [AgentCore Memory policy actions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html),
    [managed extraction](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-strategies.html).

11. Capture the final source records and all current **and noncurrent** versions and delete markers from all three versioned
    file buckets, plus the SES inbound bucket's current objects. Preserve object tags, sizes, content checksums, and a
    source-to-destination version map. Repeat strongly consistent DynamoDB base-table scans and canonical-record digests
    and `ListObjectVersions` inventory after a quiet interval and immediately before copying. Counts or hashes that
    move are NO-GO even if the preceding controls appear applied. Repeat the AgentCore actor/session/event/record
    inventory, and check its `ActiveSessionCount` (an account-level, one-minute gauge), invocation logs, and memory
    events for activity. `SessionCount` is cumulative and cannot prove no active sessions. After the direct-write
    fence is effective and runtime sessions have drained, take at least three full Memory inventories at least 30
    minutes apart over a 60-minute quiet interval. Compare actor/session sets, event IDs and canonical payload hashes,
    record IDs and canonical content/system-metadata hashes, not only counts. Any change resets the interval. Check
    failed Memory extraction jobs at each sample. Apply the migration against the final digest, verify destination
    content parity, and immediately repeat the source inventory after transfer. A mismatch is NO-GO.
    `ListMemoryExtractionJobs` reports failed/re-drive jobs and does not certify that built-in processing has finished.
    The quiet interval and parity are a **practical observation of the copied state**, not a guaranteed completion
    signal for future managed extraction or consolidation. For a strict promise to preserve every eventual source
    record, retain NO-GO until there is a demonstrated completion signal from AWS or a deployed, tested durable source
    record-change stream with replay/reconciliation of late creates, updates, and deletes. The source currently has no
    `streamDeliveryResources`; [AgentCore Memory can stream record changes to Kinesis](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-record-streaming.html),
    but that path has not been built or verified. Existing raw events have a fixed expiry applied when written;
    changing `eventExpiryDuration` cannot extend them. If an event may expire during capture/transfer, there is no
    stable raw-event snapshot and this cutover remains NO-GO. [Memory event expiry](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-create-a-memory-store.html),
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
    "bedrock-agentcore:CreateEvent", "bedrock-agentcore:IngestData",
    "bedrock-agentcore:DeleteEvent",
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
  and AgentCore direct-invocation denial still need disposable proof. The Memory `CreateEvent` and `IngestData`
  resource-policy denial was proven in a disposable destination Memory; source policy installation and readback remain
  pending. A failed denial probe is NO-GO.
- No CLI list of active AgentCore **runtime** sessions was found. Use runtime-specific invocation traces plus
  `ActiveSessionCount`, known session IDs, and a long enough quiet window; if that cannot prove no in-flight or
  background task, do not take the final memory snapshot.
- Existing Memory events expire on their original write-time schedule, and managed strategy extraction/consolidation
  can change long-term records after the last `CreateEvent`. The temporary Memory policy does not pause either service
  process. The CloudTrail-backed resource-creation lower bound above currently clears the approved transfer window;
  recheck it before the freeze. Obtain stable repeated event/record inventories, but do not assume their quiet interval
  guarantees all eventual built-in output is present. A verified completion signal or durable record-change stream
  with replay remains necessary for a strict no-loss cutover.
- AgentCore's `IngestData` submits content directly for long-term record generation. Although the current
  resource-policy supported-action list omits it, the destination drill accepted a Deny containing `IngestData`,
  read it back, and rejected a valid call that succeeded before the Deny. The source is the organization's management
  account, so SCPs cannot protect it; the live source policy must be installed and repeatedly verified during the
  freeze. The production CloudTrail trail currently selects S3 object data events but not AgentCore Memory data
  events, so Event History cannot prove the absence of direct Memory data calls. Built-in extraction and event expiry
  remain outside the policy. Verify every existing event's expiry against the full transfer window and obtain stable
  repeated record digests after draining; a reported next expiry more than four days away is not by itself a
  settled-memory signal.
  [IngestData API](https://docs.aws.amazon.com/cli/latest/reference/bedrock-agentcore/ingest-data.html),
  [Memory resource-policy actions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/resource-based-policies.html),
  [CloudTrail data event scope](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-events.html).
- The live source inventory must show whether DynamoDB replicas, S3 replication, S3 Batch jobs, or any other
  autonomous writer are active. The current commands do not fence those paths; any present path is NO-GO until a
  resource-specific drain, snapshot, and denial procedure has been reviewed.
- Confirm that source table backups/exports, all three versioned bucket histories, the SES inbound bucket's pending mail,
  and every TTL/lifecycle exclusion match the approved migration scope before treating a stable digest as complete.
- `scripts/source_freeze_executor.py` rehearses staged controls and reverse-order restore with fixtures or exact-ID
  allowlisted disposable AWS resources. The boto3 adapter can read source settings, and its source-account mutation
  guard is unconditional. The Memory resource-policy denial has a disposable-account proof; other disposable-account
  write payloads, propagation/readback handling, and denial probes require review before any production freeze.
