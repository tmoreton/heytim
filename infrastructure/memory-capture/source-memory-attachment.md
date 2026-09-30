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

Immediately before any separately authorized execution, rerun `review`, verify the source remains stable, and
check current source application error and Memory delivery metrics. If it still passes, the operator can execute
the exact reviewed change set with `aws cloudformation execute-change-set --stack-name "$SOURCE_STACK_ARN"
--change-set-name "$SOURCE_CHANGE_SET"`. Stop on `UPDATE_FAILED`, rollback, a changed physical Memory ID, or a
strategy/expiry/role change. Do not auto-retry an uncertain execution with a new change set.

After CloudFormation returns `UPDATE_COMPLETE`, read `GetMemory` until it is `ACTIVE`; verify the same ARN, role,
encryption key, 30-day expiry, three strategy IDs, and one `FULL_CONTENT` stream. Check source data-plane reads,
application errors, `StreamPublishingFailure` and `StreamUserError`, Kinesis consumer lag, and the encrypted archive.
Run `preflight.py` once record events have been archived. AWS documents `StreamingEnabled` after **creation** with
streaming, but does not explicitly promise it after an **update**. The existing preflight requires that event; if it
is absent, the capture gate remains NO-GO until an approved isolated probe and revised evidence establish delivery.
Even a healthy capture does not backfill prior records, prove every future publication, or clear the Memory
migration's strict no-loss NO-GO.

The legacy source stack must continue to be maintained through a source-specific reviewed template. A normal
`development` deployment targets a different stack name in the source account, and a normal `production`
deployment targets the destination account. Neither is a safe way to reconcile this stack.
