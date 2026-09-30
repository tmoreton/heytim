# Source AgentCore Memory record capture

**Capture stack deployed; source Memory stream not attached. This does not clear the cutover NO-GO.** This
source-account stack is prepared to capture
`FULL_CONTENT` AgentCore Memory record lifecycle events. The stack uses account `188757775631`, region `us-east-1`,
and the existing Memory `HeyTimProduction_HeyTimMemory-xeQPMmBQGC`. It does not create or replace the Memory.
Never deploy it in destination account `820323452649`.

## Deployment sequence for an approved maintenance drill

1. Verify `aws --profile frogbot-release --region us-east-1 sts get-caller-identity` returns account
   `188757775631`. Read `GetMemory` with `view=full` and save its complete private configuration, including
   `memoryExecutionRoleArn`, three strategy IDs, `eventExpiryDuration=30`, and absent stream delivery. Confirm the
   execution role is in that same account and that no other stream delivery is attached. Keep the role ARN out of
   shell history where practical.
2. From this directory run `npm ci`, `npm run build`, and `npm test`. Synthesize and review the exact stack diff with
   `npx cdk diff HeyTimMemoryCapture -c memoryRoleArn=<existing-source-memory-role-arn> --profile frogbot-release`.
   The stack creates a seven-day KMS-encrypted on-demand Kinesis stream, a KMS-encrypted versioned S3 archive with
   30-day governance Object Lock, a Lambda consumer, and CloudWatch alarms. It adds PutRecords/DescribeStream and
   KMS GenerateDataKey to the **existing** Memory execution role. Confirm the diff makes no replacement or edit to
   the Memory resource. The stack and its data resources use RETAIN and termination protection.
3. Only inside the approved source maintenance/change window, deploy that reviewed stack. Save its outputs. The
   alarms have **no notification destination**; an operator must monitor them until an alert target is attached.
4. Attach its exact `StreamArn` to the existing Memory through the
   [legacy source Memory attachment runbook](source-memory-attachment.md). The source Memory belongs to
   `AgentCore-HeyTim-production` in account `188757775631`, while the current shared CDK production target is
   account `820323452649`. Do not use the normal `agentcore deploy` or CDK target to update this legacy source
   stack. The reviewed change must add only `StreamDeliveryResources` to the existing Memory resource. Its
   CloudFormation representation is:

   ```json
   {
     "Resources": [
       {
         "Kinesis": {
           "DataStreamArn": "arn:aws:kinesis:us-east-1:188757775631:stream/heytim-memory-record-capture",
           "ContentConfigurations": [{"Type": "MEMORY_RECORDS", "Level": "FULL_CONTENT"}]
         }
       }
     ]
   }
   ```

   AWS explicitly documents `StreamingEnabled` for a Memory *created* with streaming. Whether the same event is
   emitted on update is not stated. Confirm an archived validation or organic record event and monitor publishing
   failures before relying on the capture. Recheck `GetMemory` and CloudTrail afterward: exact Memory ARN, active strategies,
   execution role, 30-day event expiry, and the one FULL_CONTENT stream must match. Do not attach a stream only after
   the direct-write freeze: a late attachment leaves a gap for managed changes already in progress.
5. Run the read-only validation with
   `../../services/runtime/.venv/bin/python preflight.py --profile frogbot-release` from this directory,
   using the repository's runtime Python or an equivalent current boto3. It checks the exact source
   account, CloudFormation outputs and termination protection, Memory attachment, stream KMS/retention, archive
   versioning/KMS/Object Lock, Lambda source mapping, and every **retained** Kinesis record against the byte-exact
   S3 archive. It covers retained parent and child shards, fails if shards change during the scan, and emits only
   counts plus a hash of its shard checkpoints. Limits default to 50,000 records and 300 seconds; hitting either is
   NO-GO and requires increasing the explicit bound or splitting the review. Preserve each result privately.

## Capture and reconciliation contract

The Lambda archives raw Kinesis payload bytes to a deterministic S3 key before returning. `IfNoneMatch=*` makes
retries idempotent; a different payload for the same shard and sequence number fails. With batch size one, the
managed Lambda event-source mapping advances its checkpoint only after S3 accepts the write. It starts at
`TRIM_HORIZON`, has no retry or record-age discard limit, and can retry until Kinesis retention expires. Monitor
Lambda errors, `IteratorAge`, and AgentCore `StreamPublishingFailure`/`StreamUserError` before seven days elapse.
The archive has no Lifecycle expiry rule. Keep it, its KMS key, the Memory, and the source identity mapping for the
entire rollback and late-processing period; 30-day Object Lock prevents early removal, while retained objects remain
after the lock period. Do not remove the stack or disable the stream when public traffic moves. The source-only
stream declaration is in `source-memory-attachment.json`; the current shared `agentcore/agentcore.json` must not
embed this account's stream ARN. Avoid an AgentCore Memory redeploy while capture is active unless its change set
is reviewed to preserve the exact attachment and physical Memory ID; rerun
`GetMemory` and the read-only validator after any configuration change.

The initial source snapshot must include **all** raw events and current long-term records. The stream begins before
that snapshot and captures later creates, updates, and deletes, including managed consolidation after direct writers
are fenced. A destination reconciler must consume archived changes with per-shard checkpoints, map source record IDs
to destination IDs, and apply idempotent create/update/delete or re-read the current source state. It must check the
full source and destination record sets repeatedly, including namespaces and content hashes. Kinesis order applies
within a shard; there is no documented cross-shard or Memory-to-Kinesis total order. Blindly replaying all captured
events on top of a later snapshot can resurrect a deleted or superseded record. The current
`scripts/migrate-agentcore-memory.py` handles an initial empty-destination migration and does **not** implement this
late-change reconciler. Until that consumer and its failure/restart tests exist, observed stream health does not clear
the traffic cutover gate. `scripts/plan-agentcore-memory-reconciliation.py` now detects late create/update/delete
candidates from full source and destination inventories, using record hashes saved in the verified initial migration
manifest. It is read-only. AgentCore offers no conditional version on record update/delete, so applying candidates
while destination users or managed processing may write is unsafe. There is no automatic late-change apply or
restart-safe write checkpoint yet; the [migration utility runbook](../../scripts/migrate-agentcore-memory.md) records
the exact NO-GO.

After each reshard, the read-only validator must cover retained closed parent shards and open child shards before
the retention horizon passes. The checkpoint hash and source/destination full-state digests should be recorded for
overlapping scans. Any missing archive object, changed shard list, growing iterator lag, failure metric, terminal
publishing log, unmapped record, or parity mismatch is NO-GO. A `StreamingEnabled` event proves activation, not
publication of every later event. If the source or consumer is unavailable for longer than Kinesis retention, the
archive cannot prove coverage of that gap.

## Cutover decision

A traffic cutover can be considered only after the initial frozen snapshot is fully copied, a tested ongoing
reconciler is active, repeated overlapping capture scans and destination parity checks pass, and an operator is
assigned to continue them after traffic moves. Keep source Memory and capture running for at least the raw-event
expiry margin and beyond if managed processing remains possible. AWS documents neither a maximum delay nor a
terminal marker for built-in extraction/consolidation, and does not promise end-to-end completeness or ordering for
Memory-to-Kinesis publication. Thus these checks establish **observed parity**, not strict no-loss. If strict no-loss
remains a requirement, traffic cutover is **NO-GO** without AWS-backed delivery and completion assurance. An explicit
owner decision may accept residual risk for a traffic cutover under an observed-parity standard; that decision does
not establish strict no-loss. Retiring source Memory after a quiet interval is NO-GO.

AWS references: [Memory record streaming](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-record-streaming.html),
[Kinesis shard listing](https://docs.aws.amazon.com/kinesis/latest/APIReference/API_ShardFilter.html),
[Lambda Kinesis retry defaults](https://docs.aws.amazon.com/lambda/latest/dg/services-kinesis-parameters.html),
[managed Memory strategies](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-strategies.html).
