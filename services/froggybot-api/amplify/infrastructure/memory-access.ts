import { ArnFormat, Stack } from 'aws-cdk-lib';
import { Effect, Policy, PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';

type MemoryAccessProps = {
  stack: Stack;
  apiFunction: LambdaFunction;
  workerFunction: LambdaFunction;
  memoryId: string;
  memoryKmsKeyArn: string;
};

export function addMemoryAccess({
  stack, apiFunction, workerFunction, memoryId, memoryKmsKeyArn,
}: MemoryAccessProps): void {
  const memoryArn = stack.formatArn({
    service: 'bedrock-agentcore',
    resource: 'memory',
    resourceName: memoryId,
    arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
  });
  apiFunction.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: [
        'bedrock-agentcore:ListMemoryRecords',
        'bedrock-agentcore:GetMemoryRecord',
        'bedrock-agentcore:BatchCreateMemoryRecords',
        'bedrock-agentcore:BatchUpdateMemoryRecords',
        'bedrock-agentcore:BatchDeleteMemoryRecords',
      ],
      resources: [memoryArn],
    }),
  );
  workerFunction.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: [
        'bedrock-agentcore:ListSessions',
        'bedrock-agentcore:ListEvents',
        'bedrock-agentcore:DeleteEvent',
        'bedrock-agentcore:ListMemoryRecords',
        'bedrock-agentcore:BatchDeleteMemoryRecords',
      ],
      resources: [memoryArn],
    }),
  );

  const memoryKeyAccess = new Policy(stack, 'MemoryKeyAccess', {
    policyName: 'FrogBotMemoryKeyAccess',
    statements: [
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ['kms:Decrypt', 'kms:DescribeKey', 'kms:Encrypt', 'kms:GenerateDataKey'],
        resources: [memoryKmsKeyArn],
      }),
    ],
  });
  memoryKeyAccess.attachToRole(apiFunction.role!);
  memoryKeyAccess.attachToRole(workerFunction.role!);
}
