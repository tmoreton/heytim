# Legacy source Memory stream attachment

This path is specific to the live source Memory in account `188757775631`. The current `production` target in
`agentcore/aws-targets.json` points to account `820323452649`; its regular CDK deployment cannot update the
legacy source stack. The reviewed [JSON overlay](source-memory-attachment.json) declares only the source stream
property. The planner copies the **current live source stack template** and inserts that property at the exact
Memory logical ID. It does not edit generated CDK or synthesize a different stack.

The source Memory is still live. CloudFormation [classifies `StreamDeliveryResources` as an update with no
interruption](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrockagentcore-memory.html),
and the [AgentCore `UpdateMemory` API](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_UpdateMemory.html)
supports changing stream delivery on an existing Memory. Neither document guarantees that every data-plane call
remains available during the asynchronous update. Use a supervised, low-traffic window and watch source Memory
reads and application errors. This attachment does not authorize traffic cutover or source retirement.

**September 30 live preview: NO-GO.** The candidate template changed only
`StreamDeliveryResources`, but CloudFormation's change set also proposed four
indirect dynamic modifications: runtime environment variables, runtime role
policy, online evaluation data source, and evaluation role policy. The reviewer
rejected the change set, and it was deleted without execution. Source Memory
remains unstreamed. Do not bypass the reviewer or rerun the same change set as
an attachment path without proving those indirect changes safe.

## Prepare locally and review

1. Verify the source profile resolves to account `188757775631`, the capture stack is healthy, and the Memory is
   `ACTIVE` with no stream. Run the planner using a Python environment with current `boto3`:

   ```bash
   cd infrastructure/memory-capture
   ../../services/runtime/.venv/bin/python source_memory_attachment.py --profile frogbot-release plan
   ```

   The script makes only read API calls. It validates the exact source stack ID, Memory physical ARN, full Memory
   configuration hash, three strategy IDs, role, KMS keys, capture stack outputs, stream readiness, role permissions,
   and the non-discarding consumer. It writes the complete candidate template in a private `0700` directory as a
   `0600` file under the system temporary directory. Treat that file as private. The pinned hashes in the JSON
   overlay cause any unrelated live stack or Memory change to stop planning until separately reviewed.

2. Review the candidate locally. Its only delta from the pinned live template must be
   `Resources.ApplicationMemoryHeyTimMemory78AB17BC.Properties.StreamDeliveryResources`, containing the exact
   source Kinesis ARN and `MEMORY_RECORDS` / `FULL_CONTENT`. The planner verifies this exact delta in code. Do not
   copy the stream ARN into the shared `agentcore/agentcore.json`: that file also deploys to the destination account.

## Create and guard a change set

The following `create-change-set` command changes CloudFormation metadata but does **not** attach the stream.
It has not been run. Replace the candidate path with the private path printed by `plan`:

```bash
SOURCE_STACK_ARN='arn:aws:cloudformation:us-east-1:188757775631:stack/AgentCore-HeyTim-production/95b9cdb0-b881-11f1-a9d7-12d6c1c28e71'
CANDIDATE_TEMPLATE='/private/tmp/replace-with-private-plan-path/candidate-template.json'
SOURCE_CHANGE_SET='heytim-source-memory-full-content-20260930'
aws --profile frogbot-release --region us-east-1 cloudformation create-change-set \
  --stack-name "$SOURCE_STACK_ARN" --change-set-name "$SOURCE_CHANGE_SET" --change-set-type UPDATE \
  --template-body "file://$CANDIDATE_TEMPLATE" \
  --parameters ParameterKey=BootstrapVersion,UsePreviousValue=true \
  --role-arn arn:aws:iam::188757775631:role/cdk-hnb659fds-cfn-exec-role-188757775631-us-east-1 \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND
aws --profile frogbot-release --region us-east-1 cloudformation wait change-set-create-complete \
  --stack-name "$SOURCE_STACK_ARN" --change-set-name "$SOURCE_CHANGE_SET"
../../services/runtime/.venv/bin/python source_memory_attachment.py --profile frogbot-release review \
  --change-set-name "$SOURCE_CHANGE_SET"
```

The read-only `review` command rejects every change set except one available `UPDATE` of the exact source stack,
with the same parameters, execution role, capabilities, and candidate template; it requires exactly one Memory
resource modification, only the stream property, `Replacement=False`, and `RequiresRecreation=Never`. A missing or
dynamic detail, changed physical ID, or changed live source baseline is **NO-GO**. Inspect CloudFormation's
pre-deployment validation events for the change set as well. Do not execute a rejected change set.

**Observed blocker on 2026-09-30:** the reviewed source change set proposed the one static in-place Memory stream
addition **and four dynamic updates** to runtime environment variables, runtime IAM policy, online evaluation data
source configuration, and its IAM policy. The read-only reviewer correctly returned NO-GO. The source template
references the Memory through `Fn::GetAtt` in the runtime and runtime policy, and the online evaluation resources
reference the runtime. CloudFormation can reevaluate and update dependent resources, so these proposals cannot be
assumed inert. Do not execute this CloudFormation change set. The source Memory remains `ACTIVE` with no stream.

## Narrow direct API alternative (separate decision)

The [AgentCore API](https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_UpdateMemory.html)
can update only this Memory's stream delivery configuration, avoiding CloudFormation's dependent-resource update
machinery. It returns HTTP 202 and may leave the Memory `UPDATING` before it becomes `ACTIVE`. AWS gives no explicit
data-plane availability or complete-delivery guarantee during that interval. A direct update also creates deliberate
CloudFormation drift: the source stack template omits `StreamDeliveryResources`. CloudFormation [checks only
properties explicitly set in the template during drift detection](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-stack-drift.html),
so ordinary drift detection may not reveal this attachment. A later source stack update could remove it. This
alternative requires an operator-owned freeze on updates to `AgentCore-HeyTim-production` and custom `GetMemory`
checks for the entire capture period. The stack currently has no protective stack policy.

If that residual risk is accepted for **capture preparation only**, rerun the read-only planner guards immediately
before the approved source maintenance window. Snapshot the full private `GetMemory` configuration and the runtime,
runtime role policy, online evaluation configuration and role policy. Use one newly generated client token, stored
privately and reused only to retry the same request. The API request should contain no expiry, strategy, namespace,
or execution-role fields:

```bash
aws --profile frogbot-release --region us-east-1 bedrock-agentcore-control update-memory \
  --memory-id HeyTimProduction_HeyTimMemory-xeQPMmBQGC \
  --client-token '<stable-unique-attach-token>' \
  --stream-delivery-resources '{"resources":[{"kinesis":{"dataStreamArn":"arn:aws:kinesis:us-east-1:188757775631:stream/heytim-memory-record-capture","contentConfigurations":[{"type":"MEMORY_RECORDS","level":"FULL_CONTENT"}]}}]}'
```

This command has **not** been run. If the service rejects the request, stop and review the rejection; do not add
other fields automatically. Poll `GetMemory(view=full)` until `ACTIVE`; stop if it remains `UPDATING`, enters `FAILED`,
or changes its ARN, key, role, 30-day expiry, three strategies, or full non-stream configuration hash. Confirm that
the runtime, both role policies, and online evaluation configuration are unchanged; monitor source read probes,
application errors, stream publishing failures, consumer lag, and the private archive. CloudTrail should show only
the targeted Memory update for this step. Do not claim capture ready until actual record delivery and archive
parity are observed; `StreamingEnabled` is documented for create, not explicitly for update. The strict Memory
no-loss cutover gate remains NO-GO.

Run `preflight.py` once record events have been archived. Its current requirement for a `StreamingEnabled` event
may remain unmet after an update; in that case it correctly leaves capture at NO-GO until an approved isolated
probe and reviewed evidence establish delivery. A healthy capture still does not backfill prior records or prove
every future publication.

If the Memory returns to `ACTIVE` but the attachment degrades source service, the narrow rollback is a new
`UpdateMemory` request with a **distinct** client token and `--stream-delivery-resources '{"resources":[]}'`.
Poll to `ACTIVE` and verify the full original Memory configuration and absent stream. A rollback creates a capture
gap and therefore cannot clear migration continuity. If Memory is stuck `UPDATING` or `FAILED`, do not race another
update; retain the source and escalate to AWS service support.

The legacy source stack must remain frozen while a direct attachment is active. A normal `development` deployment
targets a different stack name in the source account, and a normal `production` deployment targets the destination
account. Neither can safely reconcile this source stack. Future maintenance requires a fresh source-specific
change review that preserves the exact stream and physical Memory identity, or first a deliberate rollback of the
attachment after its captured data has been reconciled.
