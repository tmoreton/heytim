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

import { preSignUp } from './auth/pre-sign-up/resource';
import { auth, emailCodeMessage } from './auth/resource';

const backend = defineBackend({ auth, preSignUp });
const stack = backend.createStack('FrogBotApp');

const runtimeArn = process.env.FROGBOT_AGENT_RUNTIME_ARN;
if (!runtimeArn) {
  throw new Error('Set FROGBOT_AGENT_RUNTIME_ARN before running an Amplify sandbox or deploy.');
}

const { cfnUserPool, cfnUserPoolClient } = backend.auth.resources.cfnResources;
// Cognito username attributes are immutable after creation. These logical IDs
// intentionally replace the phone-only pool with the current email-only pool.
cfnUserPool.overrideLogicalId('FrogBotEmailUserPool');
cfnUserPoolClient.overrideLogicalId('FrogBotEmailUserPoolClient');
cfnUserPool.userPoolTier = 'ESSENTIALS';
cfnUserPool.emailConfiguration = {
  emailSendingAccount: 'DEVELOPER',
  sourceArn: `arn:aws:ses:${stack.region}:${stack.account}:identity/inboxai.cc`,
  from: 'FrogBot <no-reply@inboxai.cc>',
};
// Username attributes already create Cognito's standard email schema. Omitting
// the generated schema prevents CloudFormation from re-submitting that immutable
// attribute as a new custom attribute on later updates.
cfnUserPool.schema = undefined;
cfnUserPool.addPropertyOverride('Policies.SignInPolicy.AllowedFirstAuthFactors', [
  'PASSWORD',
  'EMAIL_OTP',
]);
cfnUserPoolClient.explicitAuthFlows = ['ALLOW_REFRESH_TOKEN_AUTH', 'ALLOW_USER_AUTH'];

cfnUserPool.emailAuthenticationSubject = 'Your FrogBot sign-in code';
cfnUserPool.emailAuthenticationMessage = emailCodeMessage('{####}');
cfnUserPool.verificationMessageTemplate = {
  defaultEmailOption: 'CONFIRM_WITH_CODE',
  emailSubject: 'Your FrogBot verification code',
  emailMessage: emailCodeMessage('{####}'),
};

const inviteAccess = new Table(backend.auth.stack, 'InviteAccess', {
  partitionKey: { name: 'tokenHash', type: AttributeType.STRING },
  billingMode: BillingMode.PAY_PER_REQUEST,
  pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
  timeToLiveAttribute: 'expiresAt',
  removalPolicy: RemovalPolicy.RETAIN,
});
backend.preSignUp.addEnvironment('INVITE_TABLE_NAME', inviteAccess.tableName);
inviteAccess.grantReadData(backend.preSignUp.resources.lambda);

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
  handler: 'api.handler.handler',
  code: Code.fromAsset(path.resolve('amplify/functions')),
  timeout: Duration.seconds(15),
  environment: {
    ...functionDefaults.environment,
    QUEUE_URL: jobs.queueUrl,
    INVITE_TABLE_NAME: inviteAccess.tableName,
    PUBLIC_WEB_BASE_URL: 'https://frogbot.expo.app',
    CAPABILITY_CATALOG_URL:
      'https://raw.githubusercontent.com/tmoreton/frogbot-capabilities/main/catalog.json',
  },
});

const workerFunction = new LambdaFunction(stack, 'WorkerFunction', {
  ...functionDefaults,
  handler: 'worker.handler.handler',
  code: Code.fromAsset(path.resolve('amplify/functions')),
  timeout: Duration.minutes(6),
  environment: {
    ...functionDefaults.environment,
    AGENT_RUNTIME_ARN: runtimeArn,
    AGENT_RUNTIME_QUALIFIER: process.env.FROGBOT_AGENT_RUNTIME_QUALIFIER ?? 'DEFAULT',
    QUEUE_URL: jobs.queueUrl,
    CAPABILITY_CATALOG_URL:
      'https://raw.githubusercontent.com/tmoreton/frogbot-capabilities/main/catalog.json',
  },
});

table.grantReadWriteData(apiFunction);
inviteAccess.grantReadWriteData(apiFunction);
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

httpApi.addRoutes({
  path: '/public/invites/{kind}/{token}',
  methods: [HttpMethod.GET],
  integration,
});

for (const [method, routePath] of [
  [HttpMethod.GET, '/bootstrap'],
  [HttpMethod.POST, '/bots'],
  [HttpMethod.PUT, '/bots/{botId}'],
  [HttpMethod.GET, '/bots/{botId}/messages'],
  [HttpMethod.POST, '/bots/{botId}/messages'],
  [HttpMethod.POST, '/groups'],
  [HttpMethod.PUT, '/groups/{groupId}'],
  [HttpMethod.GET, '/groups/{groupId}/messages'],
  [HttpMethod.POST, '/groups/{groupId}/messages'],
  [HttpMethod.POST, '/groups/{groupId}/invites'],
  [HttpMethod.DELETE, '/groups/{groupId}/members/{memberId}'],
  [HttpMethod.POST, '/group-invites/{token}/join'],
  [HttpMethod.PUT, '/devices/push-token'],
  [HttpMethod.DELETE, '/devices/push-token'],
  [HttpMethod.POST, '/shares'],
  [HttpMethod.POST, '/shares/{token}/import'],
  [HttpMethod.POST, '/skills'],
  [HttpMethod.GET, '/skills/{skillId}'],
  [HttpMethod.PUT, '/skills/{skillId}'],
  [HttpMethod.POST, '/skills/{skillId}/share'],
  [HttpMethod.POST, '/skill-shares/{token}/import'],
] as const) {
  httpApi.addRoutes({ path: routePath, methods: [method], integration, authorizer });
}

backend.addOutput({
  custom: {
    apiUrl: httpApi.apiEndpoint,
    shareBaseUrl: 'https://frogbot.expo.app/invite',
  },
});
