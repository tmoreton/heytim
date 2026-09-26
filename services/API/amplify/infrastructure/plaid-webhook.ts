import { Duration, type Stack } from 'aws-cdk-lib';
import type { Table } from 'aws-cdk-lib/aws-dynamodb';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Function as LambdaFunction, Runtime, Tracing } from 'aws-cdk-lib/aws-lambda';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';
import type { LogGroup } from 'aws-cdk-lib/aws-logs';
import type { Queue } from 'aws-cdk-lib/aws-sqs';
import path from 'node:path';

type PlaidWebhookResources = {
  stack: Stack;
  table: Table;
  jobs: Queue;
  logGroup: LogGroup;
  secretArn: string;
  workerFunction: LambdaFunction;
};

export function addPlaidWebhook({
  stack,
  table,
  jobs,
  logGroup,
  secretArn,
  workerFunction,
}: PlaidWebhookResources): NodejsFunction {
  const webhook = new NodejsFunction(stack, 'PlaidWebhookFunction', {
    entry: path.resolve('amplify/functions/plaid-webhook/handler.ts'),
    handler: 'handler',
    runtime: Runtime.NODEJS_22_X,
    timeout: Duration.seconds(15),
    memorySize: 256,
    logGroup,
    tracing: Tracing.ACTIVE,
    bundling: { minify: true, externalModules: [] },
    environment: {
      TABLE_NAME: table.tableName,
      QUEUE_URL: jobs.queueUrl,
      PLAID_SECRET_ARN: secretArn,
    },
  });
  table.grantReadData(webhook);
  jobs.grantSendMessages(webhook);
  if (secretArn) {
    const readSecret = new PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'], resources: [secretArn],
    });
    webhook.addToRolePolicy(readSecret);
    workerFunction.addToRolePolicy(readSecret);
  }
  return webhook;
}
