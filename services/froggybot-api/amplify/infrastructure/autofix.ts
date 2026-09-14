import { ArnFormat, Duration, RemovalPolicy, type Stack } from 'aws-cdk-lib';
import type { Table } from 'aws-cdk-lib/aws-dynamodb';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import type { Key } from 'aws-cdk-lib/aws-kms';
import {
  CfnPermission,
  Code,
  Function as LambdaFunction,
  Runtime,
  Tracing,
} from 'aws-cdk-lib/aws-lambda';
import {
  CfnSubscriptionFilter,
  FilterPattern,
  LogGroup,
  RetentionDays,
  SubscriptionFilter,
} from 'aws-cdk-lib/aws-logs';
import { LambdaDestination } from 'aws-cdk-lib/aws-logs-destinations';
import path from 'node:path';

import { FUNCTION_ASSET_EXCLUDES } from './app-settings';

type AutofixResources = {
  stack: Stack;
  table: Table;
  workerLogGroup: LogGroup;
  logsKey: Key;
  githubAppSecretArn: string;
  runtimeArn: string;
  runtimeQualifier: string;
  enabled: boolean;
};

function runtimeId(runtimeArn: string): string {
  const value = runtimeArn.split('/').at(-1) ?? '';
  if (!/^[A-Za-z][A-Za-z0-9_-]{0,95}$/.test(value)) {
    throw new Error('FROGBOT_AGENT_RUNTIME_ARN does not contain a valid runtime id.');
  }
  return value;
}

export function addProductionAutofix({
  stack,
  table,
  workerLogGroup,
  logsKey,
  githubAppSecretArn,
  runtimeArn,
  runtimeQualifier,
  enabled,
}: AutofixResources) {
  if (!enabled) return undefined;

  const runtimeLogGroupName = `/aws/bedrock-agentcore/runtimes/${runtimeId(runtimeArn)}-${runtimeQualifier}`;
  const dispatcherLogGroup = new LogGroup(stack, 'AutofixDispatcherLogs', {
    encryptionKey: logsKey,
    retention: RetentionDays.ONE_MONTH,
    removalPolicy: RemovalPolicy.RETAIN,
  });
  const dispatcher = new LambdaFunction(stack, 'AutofixDispatcher', {
    runtime: Runtime.PYTHON_3_14,
    handler: 'autofix_dispatcher.handler.handler',
    code: Code.fromAsset(path.resolve('amplify/functions'), {
      exclude: FUNCTION_ASSET_EXCLUDES,
    }),
    logGroup: dispatcherLogGroup,
    memorySize: 256,
    timeout: Duration.seconds(30),
    tracing: Tracing.ACTIVE,
    environment: {
      TABLE_NAME: table.tableName,
      AUTOFIX_ALLOWED_LOG_GROUPS: [workerLogGroup.logGroupName, runtimeLogGroupName].join(','),
      AUTOFIX_GITHUB_APP_SECRET_ARN: githubAppSecretArn,
      AUTOFIX_REPOSITORY: 'tmoreton/frogbot',
      AUTOFIX_EVENT_TYPE: 'froggybot-production-error',
      AUTOFIX_COOLDOWN_HOURS: '6',
      AUTOFIX_DAILY_LIMIT: '3',
      AUTOFIX_RELEASE_SHA: /^[a-f0-9]{40}$/.test(process.env.GITHUB_SHA ?? '')
        ? process.env.GITHUB_SHA!
        : '',
    },
  });
  table.grantReadWriteData(dispatcher);
  dispatcher.addToRolePolicy(new PolicyStatement({
    actions: ['secretsmanager:GetSecretValue'],
    resources: [githubAppSecretArn],
  }));

  new SubscriptionFilter(stack, 'WorkerAutofixSubscription', {
    logGroup: workerLogGroup,
    destination: new LambdaDestination(dispatcher),
    filterPattern: FilterPattern.literal('"FROGBOT_TERMINAL_ERROR"'),
  });

  const runtimeLogGroupArn = stack.formatArn({
    service: 'logs',
    resource: 'log-group',
    resourceName: runtimeLogGroupName,
    arnFormat: ArnFormat.COLON_RESOURCE_NAME,
  });
  const permission = new CfnPermission(stack, 'AgentRuntimeAutofixLogsPermission', {
    action: 'lambda:InvokeFunction',
    functionName: dispatcher.functionName,
    principal: `logs.${stack.region}.amazonaws.com`,
    sourceAccount: stack.account,
    sourceArn: `${runtimeLogGroupArn}:*`,
  });
  const runtimeSubscription = new CfnSubscriptionFilter(
    stack,
    'AgentRuntimeAutofixSubscription',
    {
      destinationArn: dispatcher.functionArn,
      filterPattern: '"FROGBOT_TERMINAL_ERROR"',
      logGroupName: runtimeLogGroupName,
    },
  );
  runtimeSubscription.addDependency(permission);

  return { dispatcher, dispatcherLogGroup, runtimeLogGroupName };
}
