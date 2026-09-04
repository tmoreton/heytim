import { defineBackend } from '@aws-amplify/backend';
import { Duration, RemovalPolicy } from 'aws-cdk-lib';
import { CorsHttpMethod, HttpApi, HttpMethod } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpJwtAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { AttributeType, BillingMode, Table } from 'aws-cdk-lib/aws-dynamodb';
import { Effect, PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Code, Function as LambdaFunction, Runtime } from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { Queue, QueueEncryption } from 'aws-cdk-lib/aws-sqs';
import path from 'node:path';

import { auth } from './auth/resource';

const backend = defineBackend({ auth });
const stack = backend.createStack('FrogBotApp');

const runtimeArn = process.env.FROGBOT_AGENT_RUNTIME_ARN;
if (!runtimeArn) {
  throw new Error('Set FROGBOT_AGENT_RUNTIME_ARN before running an Amplify sandbox or deploy.');
}

const { cfnUserPool, cfnUserPoolClient } = backend.auth.resources.cfnResources;
// Cognito username attributes are immutable after creation. This logical ID
// intentionally replaces the original email pool with a phone-only pool.
cfnUserPool.overrideLogicalId('FrogBotPhoneUserPool');
cfnUserPoolClient.overrideLogicalId('FrogBotPhoneUserPoolClient');
cfnUserPool.userPoolTier = 'ESSENTIALS';
// Username attributes already create Cognito's standard phone_number schema.
// Omitting the generated schema prevents CloudFormation from re-submitting that
// immutable attribute as a new custom attribute on later updates.
cfnUserPool.schema = undefined;
cfnUserPool.addPropertyOverride('Policies.SignInPolicy.AllowedFirstAuthFactors', [
  'PASSWORD',
  'SMS_OTP',
]);
cfnUserPoolClient.explicitAuthFlows = ['ALLOW_REFRESH_TOKEN_AUTH', 'ALLOW_USER_AUTH'];

const table = new Table(stack, 'Data', {
  partitionKey: { name: 'pk', type: AttributeType.STRING },
  sortKey: { name: 'sk', type: AttributeType.STRING },
  billingMode: BillingMode.PAY_PER_REQUEST,
  pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
  timeToLiveAttribute: 'expiresAt',
  removalPolicy: RemovalPolicy.RETAIN,
});

const deadLetterQueue = new Queue(stack, 'AgentJobsDeadLetter', {
  encryption: QueueEncryption.SQS_MANAGED,
  enforceSSL: true,
  retentionPeriod: Duration.days(14),
});
const jobs = new Queue(stack, 'AgentJobs', {
  encryption: QueueEncryption.SQS_MANAGED,
  enforceSSL: true,
  visibilityTimeout: Duration.minutes(25),
  retentionPeriod: Duration.days(4),
  deadLetterQueue: { queue: deadLetterQueue, maxReceiveCount: 3 },
});

const functionDefaults = {
  runtime: Runtime.PYTHON_3_14,
  memorySize: 512,
  environment: { TABLE_NAME: table.tableName },
};

const apiFunction = new LambdaFunction(stack, 'ApiFunction', {
  ...functionDefaults,
  handler: 'handler.handler',
  code: Code.fromAsset(path.resolve('amplify/functions/api')),
  timeout: Duration.seconds(15),
  environment: {
    ...functionDefaults.environment,
    QUEUE_URL: jobs.queueUrl,
    SHARE_BASE_URL: 'frogbot://share',
  },
});

const workerFunction = new LambdaFunction(stack, 'WorkerFunction', {
  ...functionDefaults,
  handler: 'handler.handler',
  code: Code.fromAsset(path.resolve('amplify/functions/worker')),
  timeout: Duration.minutes(4),
  environment: {
    ...functionDefaults.environment,
    AGENT_RUNTIME_ARN: runtimeArn,
    AGENT_RUNTIME_QUALIFIER: process.env.FROGBOT_AGENT_RUNTIME_QUALIFIER ?? 'DEFAULT',
    QUEUE_URL: jobs.queueUrl,
  },
});

table.grantReadWriteData(apiFunction);
table.grantReadWriteData(workerFunction);
jobs.grantSendMessages(apiFunction);
jobs.grantSendMessages(workerFunction);
workerFunction.addEventSource(
  new SqsEventSource(jobs, {
    batchSize: 1,
    reportBatchItemFailures: true,
  }),
);
workerFunction.addToRolePolicy(
  new PolicyStatement({
    effect: Effect.ALLOW,
    actions: ['bedrock-agentcore:InvokeAgentRuntime'],
    resources: [runtimeArn, `${runtimeArn}/runtime-endpoint/*`],
  }),
);

const httpApi = new HttpApi(stack, 'HttpApi', {
  corsPreflight: {
    allowOrigins: ['*'],
    allowHeaders: ['authorization', 'content-type'],
    allowMethods: [
      CorsHttpMethod.GET,
      CorsHttpMethod.POST,
      CorsHttpMethod.PUT,
      CorsHttpMethod.DELETE,
      CorsHttpMethod.OPTIONS,
    ],
  },
});
const authorizer = new HttpJwtAuthorizer(
  'CognitoAuthorizer',
  `https://cognito-idp.${stack.region}.amazonaws.com/${backend.auth.resources.userPool.userPoolId}`,
  { jwtAudience: [backend.auth.resources.userPoolClient.userPoolClientId] },
);
const integration = new HttpLambdaIntegration('ApiIntegration', apiFunction);

for (const [method, routePath] of [
  [HttpMethod.GET, '/bootstrap'],
  [HttpMethod.POST, '/bots'],
  [HttpMethod.PUT, '/bots/{botId}'],
  [HttpMethod.GET, '/bots/{botId}/messages'],
  [HttpMethod.POST, '/bots/{botId}/messages'],
  [HttpMethod.PUT, '/devices/push-token'],
  [HttpMethod.DELETE, '/devices/push-token'],
  [HttpMethod.POST, '/shares'],
  [HttpMethod.POST, '/shares/{token}/import'],
] as const) {
  httpApi.addRoutes({ path: routePath, methods: [method], integration, authorizer });
}

backend.addOutput({
  custom: {
    apiUrl: httpApi.apiEndpoint,
    shareBaseUrl: 'frogbot://share',
  },
});
