import { defineBackend } from '@aws-amplify/backend';
import { ArnFormat, Duration, RemovalPolicy } from 'aws-cdk-lib';
import { CfnStage, CorsHttpMethod, HttpApi, HttpMethod } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpJwtAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { Trail } from 'aws-cdk-lib/aws-cloudtrail';
import { AttributeType, BillingMode, Table } from 'aws-cdk-lib/aws-dynamodb';
import { Effect, PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import { Key } from 'aws-cdk-lib/aws-kms';
import { Code, Function as LambdaFunction, Runtime, Tracing } from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { BlockPublicAccess, Bucket, BucketEncryption, HttpMethods } from 'aws-cdk-lib/aws-s3';
import { ScheduleGroup } from 'aws-cdk-lib/aws-scheduler';
import { Queue, QueueEncryption } from 'aws-cdk-lib/aws-sqs';
import path from 'node:path';

import { preSignUp } from './auth/pre-sign-up/resource';
import { auth, emailCodeMessage } from './auth/resource';
import { AUTHENTICATED_ROUTES } from './infrastructure/api-routes';
import { addObservability } from './infrastructure/observability';

const backend = defineBackend({ auth, preSignUp });
const stack = backend.createStack('FrogBotApp');

const runtimeArn = process.env.FROGBOT_AGENT_RUNTIME_ARN;
if (!runtimeArn) {
  throw new Error('Set FROGBOT_AGENT_RUNTIME_ARN before running an Amplify sandbox or deploy.');
}
const memoryId = process.env.FROGBOT_MEMORY_ID;
if (!memoryId) {
  throw new Error('Set FROGBOT_MEMORY_ID before running an Amplify sandbox or deploy.');
}
const googleOAuthSecretArn = process.env.FROGBOT_GOOGLE_OAUTH_SECRET_ARN;
if (!googleOAuthSecretArn) {
  throw new Error('Set FROGBOT_GOOGLE_OAUTH_SECRET_ARN before running an Amplify sandbox or deploy.');
}
const monthlyBudgetUsd = Number(process.env.FROGBOT_MONTHLY_BUDGET_USD ?? '100');
if (!Number.isFinite(monthlyBudgetUsd) || monthlyBudgetUsd <= 0) {
  throw new Error('FROGBOT_MONTHLY_BUDGET_USD must be a positive number.');
}

const { cfnUserPool, cfnUserPoolClient } = backend.auth.resources.cfnResources;
// Cognito username attributes are immutable after creation. These logical IDs
// intentionally replace the phone-only pool with the current email-only pool.
cfnUserPool.overrideLogicalId('FrogBotEmailUserPool');
cfnUserPoolClient.overrideLogicalId('FrogBotEmailUserPoolClient');
cfnUserPool.userPoolTier = 'ESSENTIALS';
cfnUserPool.deletionProtection = 'ACTIVE';
cfnUserPool.emailConfiguration = {
  emailSendingAccount: 'DEVELOPER',
  sourceArn: `arn:aws:ses:${stack.region}:${stack.account}:identity/inboxai.cc`,
  from: 'FroggyBot <no-reply@inboxai.cc>',
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

cfnUserPool.emailAuthenticationSubject = 'Your FroggyBot sign-in code';
cfnUserPool.emailAuthenticationMessage = emailCodeMessage('{####}');
cfnUserPool.verificationMessageTemplate = {
  defaultEmailOption: 'CONFIRM_WITH_CODE',
  emailSubject: 'Your FroggyBot verification code',
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
backend.preSignUp.resources.lambda.addToRolePolicy(
  new PolicyStatement({
    actions: ['cognito-idp:AdminGetUser'],
    // Referencing the pool construct here would create a cycle because the
    // pool already depends on this trigger. Runtime input limits lookups to
    // the invoking pool in this account and region.
    resources: [
      backend.auth.stack.formatArn({
        service: 'cognito-idp',
        resource: 'userpool',
        resourceName: '*',
      }),
    ],
  }),
);

const table = new Table(stack, 'Data', {
  partitionKey: { name: 'pk', type: AttributeType.STRING },
  sortKey: { name: 'sk', type: AttributeType.STRING },
  billingMode: BillingMode.PAY_PER_REQUEST,
  pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
  timeToLiveAttribute: 'expiresAt',
  removalPolicy: RemovalPolicy.RETAIN,
});

const filesBucket = new Bucket(stack, 'UserFiles', {
  bucketName: `frogbot-user-files-${stack.account}-${stack.region}`,
  blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
  encryption: BucketEncryption.S3_MANAGED,
  enforceSSL: true,
  versioned: true,
  cors: [
    {
      allowedHeaders: ['*'],
      allowedMethods: [HttpMethods.GET, HttpMethods.HEAD, HttpMethods.POST],
      allowedOrigins: [
        'https://froggybot.com',
        'https://app.froggybot.com',
        'https://www.froggybot.com',
        'https://frogbot.expo.app',
        'http://localhost:8081',
        'http://localhost:19006',
      ],
      exposedHeaders: ['etag'],
      maxAge: 3600,
    },
  ],
  lifecycleRules: [
    {
      abortIncompleteMultipartUploadAfter: Duration.days(1),
      noncurrentVersionExpiration: Duration.days(30),
    },
  ],
  removalPolicy: RemovalPolicy.RETAIN,
});

const logsKey = new Key(stack, 'LogsKey', {
  description: 'Encrypts FroggyBot application and audit logs.',
  enableKeyRotation: true,
  removalPolicy: RemovalPolicy.RETAIN,
});
logsKey.addToResourcePolicy(
  new PolicyStatement({
    effect: Effect.ALLOW,
    principals: [new ServicePrincipal(`logs.${stack.region}.amazonaws.com`)],
    actions: [
      'kms:Encrypt*',
      'kms:Decrypt*',
      'kms:ReEncrypt*',
      'kms:GenerateDataKey*',
      'kms:Describe*',
    ],
    resources: ['*'],
    conditions: {
      ArnLike: {
        'kms:EncryptionContext:aws:logs:arn': stack.formatArn({
          service: 'logs',
          resource: 'log-group',
          resourceName: '*',
          arnFormat: ArnFormat.COLON_RESOURCE_NAME,
        }),
      },
    },
  }),
);
logsKey.addToResourcePolicy(
  new PolicyStatement({
    effect: Effect.ALLOW,
    principals: [new ServicePrincipal('cloudtrail.amazonaws.com')],
    actions: ['kms:GenerateDataKey*', 'kms:DescribeKey'],
    resources: ['*'],
    conditions: {
      ArnLike: {
        'aws:SourceArn': stack.formatArn({
          service: 'cloudtrail',
          resource: 'trail',
          resourceName: '*',
          arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
        }),
        'kms:EncryptionContext:aws:cloudtrail:arn': stack.formatArn({
          service: 'cloudtrail',
          resource: 'trail',
          resourceName: '*',
          arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
        }),
      },
    },
  }),
);
const apiLogGroup = new LogGroup(stack, 'ApiLogs', {
  encryptionKey: logsKey,
  retention: RetentionDays.ONE_MONTH,
  removalPolicy: RemovalPolicy.RETAIN,
});
const workerLogGroup = new LogGroup(stack, 'WorkerLogs', {
  encryptionKey: logsKey,
  retention: RetentionDays.ONE_MONTH,
  removalPolicy: RemovalPolicy.RETAIN,
});
const apiAccessLogGroup = new LogGroup(stack, 'ApiAccessLogs', {
  encryptionKey: logsKey,
  retention: RetentionDays.ONE_MONTH,
  removalPolicy: RemovalPolicy.RETAIN,
});

const auditBucket = new Bucket(stack, 'AuditLogs', {
  blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
  encryption: BucketEncryption.KMS,
  encryptionKey: logsKey,
  enforceSSL: true,
  versioned: true,
  removalPolicy: RemovalPolicy.RETAIN,
});
new Trail(stack, 'AuditTrail', {
  bucket: auditBucket,
  encryptionKey: logsKey,
  enableFileValidation: true,
  includeGlobalServiceEvents: true,
  isMultiRegionTrail: true,
  sendToCloudWatchLogs: true,
  cloudWatchLogsRetention: RetentionDays.ONE_MONTH,
});

const deadLetterQueue = new Queue(stack, 'AgentJobsDeadLetter', {
  encryption: QueueEncryption.SQS_MANAGED,
  enforceSSL: true,
  retentionPeriod: Duration.days(14),
});
const jobs = new Queue(stack, 'AgentJobs', {
  encryption: QueueEncryption.SQS_MANAGED,
  enforceSSL: true,
  // AWS recommends at least six times the Lambda timeout. Each active worker
  // narrows its own message to 16 minutes so a hard timeout still retries soon.
  visibilityTimeout: Duration.minutes(90),
  retentionPeriod: Duration.days(4),
  deadLetterQueue: { queue: deadLetterQueue, maxReceiveCount: 3 },
});
const taskScheduleGroup = new ScheduleGroup(stack, 'TaskSchedules', {
  removalPolicy: RemovalPolicy.DESTROY,
});
const taskScheduleRole = new Role(stack, 'TaskScheduleRole', {
  assumedBy: new ServicePrincipal('scheduler.amazonaws.com'),
});
jobs.grantSendMessages(taskScheduleRole);
deadLetterQueue.grantSendMessages(taskScheduleRole);

const functionDefaults = {
  runtime: Runtime.PYTHON_3_14,
  memorySize: 512,
  environment: { TABLE_NAME: table.tableName },
  tracing: Tracing.ACTIVE,
};

const apiFunction = new LambdaFunction(stack, 'ApiFunction', {
  ...functionDefaults,
  handler: 'api.handler.handler',
  code: Code.fromAsset(path.resolve('amplify/functions')),
  logGroup: apiLogGroup,
  timeout: Duration.seconds(15),
  environment: {
    ...functionDefaults.environment,
    QUEUE_URL: jobs.queueUrl,
    QUEUE_ARN: jobs.queueArn,
    SCHEDULE_DLQ_ARN: deadLetterQueue.queueArn,
    SCHEDULE_GROUP_NAME: taskScheduleGroup.scheduleGroupName,
    SCHEDULE_ROLE_ARN: taskScheduleRole.roleArn,
    INVITE_TABLE_NAME: inviteAccess.tableName,
    USER_POOL_ID: backend.auth.resources.userPool.userPoolId,
    AGENT_RUNTIME_ARN: runtimeArn,
    AGENT_RUNTIME_QUALIFIER: process.env.FROGBOT_AGENT_RUNTIME_QUALIFIER ?? 'DEFAULT',
    FROGBOT_MEMORY_ID: memoryId,
    FILES_BUCKET_NAME: filesBucket.bucketName,
    PUBLIC_WEB_BASE_URL: 'https://froggybot.com',
    CAPABILITY_CATALOG_URL:
      'https://froggybot.com/catalog.json',
    GOOGLE_OAUTH_SECRET_ARN: googleOAuthSecretArn,
  },
});

const workerFunction = new LambdaFunction(stack, 'WorkerFunction', {
  ...functionDefaults,
  handler: 'worker.handler.handler',
  code: Code.fromAsset(path.resolve('amplify/functions')),
  logGroup: workerLogGroup,
  timeout: Duration.minutes(14),
  environment: {
    ...functionDefaults.environment,
    AGENT_RUNTIME_ARN: runtimeArn,
    AGENT_RUNTIME_QUALIFIER: process.env.FROGBOT_AGENT_RUNTIME_QUALIFIER ?? 'DEFAULT',
    QUEUE_URL: jobs.queueUrl,
    QUEUE_ARN: jobs.queueArn,
    SCHEDULE_DLQ_ARN: deadLetterQueue.queueArn,
    SCHEDULE_GROUP_NAME: taskScheduleGroup.scheduleGroupName,
    SCHEDULE_ROLE_ARN: taskScheduleRole.roleArn,
    INVITE_TABLE_NAME: inviteAccess.tableName,
    USER_POOL_ID: backend.auth.resources.userPool.userPoolId,
    FROGBOT_MEMORY_ID: memoryId,
    FILES_BUCKET_NAME: filesBucket.bucketName,
    PUBLIC_WEB_BASE_URL: 'https://froggybot.com',
    CAPABILITY_CATALOG_URL:
      'https://froggybot.com/catalog.json',
  },
});

table.grantReadWriteData(apiFunction);
inviteAccess.grantReadWriteData(apiFunction);
inviteAccess.grantReadWriteData(workerFunction);
table.grantReadWriteData(workerFunction);
filesBucket.grantReadWrite(apiFunction);
filesBucket.grantReadWrite(workerFunction);
const connectionSecretsArn = stack.formatArn({
  service: 'secretsmanager',
  resource: 'secret',
  resourceName: 'frogbot/connections/*',
  arnFormat: ArnFormat.COLON_RESOURCE_NAME,
});
apiFunction.addToRolePolicy(
  new PolicyStatement({
    actions: [
      'secretsmanager:CreateSecret',
      'secretsmanager:PutSecretValue',
      'secretsmanager:DeleteSecret',
      'secretsmanager:TagResource',
    ],
    resources: [connectionSecretsArn],
  }),
);
apiFunction.addToRolePolicy(
  new PolicyStatement({
    actions: ['secretsmanager:GetSecretValue'],
    resources: [googleOAuthSecretArn],
  }),
);
workerFunction.addToRolePolicy(
  new PolicyStatement({
    actions: ['secretsmanager:DeleteSecret'],
    resources: [connectionSecretsArn],
  }),
);
jobs.grantSendMessages(apiFunction);
jobs.grantSendMessages(workerFunction);
taskScheduleGroup.grantWriteSchedules(apiFunction);
taskScheduleGroup.grantDeleteSchedules(apiFunction);
taskScheduleGroup.grantDeleteSchedules(workerFunction);
for (const fn of [apiFunction, workerFunction]) {
  fn.addToRolePolicy(
    new PolicyStatement({
      actions: ['cognito-idp:AdminDeleteUser', 'cognito-idp:AdminUserGlobalSignOut'],
      resources: [backend.auth.resources.userPool.userPoolArn],
    }),
  );
}
apiFunction.addToRolePolicy(
  new PolicyStatement({
    actions: ['iam:PassRole'],
    resources: [taskScheduleRole.roleArn],
    conditions: { StringEquals: { 'iam:PassedToService': 'scheduler.amazonaws.com' } },
  }),
);
apiFunction.addToRolePolicy(
  new PolicyStatement({
    effect: Effect.ALLOW,
    actions: ['bedrock-agentcore:StopRuntimeSession'],
    resources: [runtimeArn, `${runtimeArn}/runtime-endpoint/*`],
  }),
);
workerFunction.addEventSource(
  new SqsEventSource(jobs, {
    batchSize: 1,
    reportBatchItemFailures: true,
  }),
);
workerFunction.addToRolePolicy(
  new PolicyStatement({
    effect: Effect.ALLOW,
    actions: ['bedrock-agentcore:InvokeAgentRuntime', 'bedrock-agentcore:StopRuntimeSession'],
    resources: [runtimeArn, `${runtimeArn}/runtime-endpoint/*`],
  }),
);
workerFunction.addToRolePolicy(
  new PolicyStatement({
    effect: Effect.ALLOW,
    actions: [
      'bedrock-agentcore:ListCodeInterpreterSessions',
      'bedrock-agentcore:StopCodeInterpreterSession',
      'bedrock-agentcore:ListBrowserSessions',
      'bedrock-agentcore:StopBrowserSession',
    ],
    resources: ['*'],
  }),
);
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

const httpApi = new HttpApi(stack, 'HttpApi', {
  corsPreflight: {
    allowOrigins: [
      'https://froggybot.com',
      'https://app.froggybot.com',
      'https://www.froggybot.com',
      'https://frogbot.expo.app',
      'http://localhost:8081',
      'http://localhost:19006',
    ],
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
apiFunction.addEnvironment(
  'GOOGLE_OAUTH_REDIRECT_URI',
  `${httpApi.apiEndpoint}/public/oauth/google/callback`,
);
const authorizer = new HttpJwtAuthorizer(
  'CognitoAuthorizer',
  `https://cognito-idp.${stack.region}.amazonaws.com/${backend.auth.resources.userPool.userPoolId}`,
  { jwtAudience: [backend.auth.resources.userPoolClient.userPoolClientId] },
);
const integration = new HttpLambdaIntegration('ApiIntegration', apiFunction, {
  scopePermissionToRoute: false,
});

const defaultStage = httpApi.defaultStage?.node.defaultChild as CfnStage | undefined;
if (!defaultStage) throw new Error('FroggyBot HTTP API must have a default stage.');
defaultStage.accessLogSettings = {
  destinationArn: apiAccessLogGroup.logGroupArn,
  format: JSON.stringify({
    requestId: '$context.requestId',
    requestTime: '$context.requestTime',
    httpMethod: '$context.httpMethod',
    routeKey: '$context.routeKey',
    status: '$context.status',
    responseLatency: '$context.responseLatency',
    integrationError: '$context.integrationErrorMessage',
    sourceIp: '$context.identity.sourceIp',
  }),
};
defaultStage.defaultRouteSettings = {
  detailedMetricsEnabled: true,
  throttlingBurstLimit: 100,
  throttlingRateLimit: 50,
};

httpApi.addRoutes({
  path: '/public/invites/{kind}/{token}',
  methods: [HttpMethod.GET],
  integration,
});
httpApi.addRoutes({
  path: '/public/catalog',
  methods: [HttpMethod.GET],
  integration,
});
httpApi.addRoutes({
  path: '/public/oauth/google/callback',
  methods: [HttpMethod.GET],
  integration,
});

for (const [method, routePath] of AUTHENTICATED_ROUTES) {
  httpApi.addRoutes({ path: routePath, methods: [method], integration, authorizer });
}

const { alarmTopic, monthlyBudgetName } = addObservability({
  stack,
  apiFunction,
  workerFunction,
  workerLogGroup,
  jobs,
  deadLetterQueue,
  logsKey,
  monthlyBudgetUsd,
});

backend.addOutput({
  custom: {
    apiUrl: httpApi.apiEndpoint,
    shareBaseUrl: 'https://froggybot.com/invite',
    dataTableName: table.tableName,
    filesBucketName: filesBucket.bucketName,
    alarmTopicArn: alarmTopic.topicArn,
    monthlyBudgetName,
  },
});
