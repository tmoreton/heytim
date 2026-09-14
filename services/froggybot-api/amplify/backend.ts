import { defineBackend } from '@aws-amplify/backend';
import { ArnFormat, Duration, RemovalPolicy } from 'aws-cdk-lib';
import { ReadWriteType, Trail } from 'aws-cdk-lib/aws-cloudtrail';
import { AttributeType, BillingMode, Table, TableEncryption } from 'aws-cdk-lib/aws-dynamodb';
import { Rule, RuleTargetInput, Schedule } from 'aws-cdk-lib/aws-events';
import { SqsQueue } from 'aws-cdk-lib/aws-events-targets';
import { Effect, PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import { Key } from 'aws-cdk-lib/aws-kms';
import { Code, Function as LambdaFunction, RecursiveLoop, Runtime, Tracing } from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { BlockPublicAccess, Bucket, BucketEncryption, HttpMethods } from 'aws-cdk-lib/aws-s3';
import { ScheduleGroup } from 'aws-cdk-lib/aws-scheduler';
import { Queue, QueueEncryption } from 'aws-cdk-lib/aws-sqs';
import path from 'node:path';

import { preSignUp } from './auth/pre-sign-up/resource';
import { auth, emailCodeMessage } from './auth/resource';
import {
  ALLOWED_WEB_ORIGINS, CAPABILITY_CATALOG_URL,
  FUNCTION_ASSET_EXCLUDES, PUBLIC_WEB_BASE_URL,
  WORKER_CONCURRENCY, deploymentEnvironment,
  apnsApplicationArn, apnsSandboxApplicationArn,
  githubAppSecretArn, globalWindowRunUnitLimit, googleOAuthSecretArn,
  memoryId, microsoftOAuthSecretArn, monthlyBudgetUsd, monthlyRunUnitLimit,
  notionOAuthSecretArn,
  runtimeArn, runtimeQualifier, usageWindowSeconds, userWindowRunUnitLimit,
  slackOAuthSecretArn, xOAuthSecretArn, youtubeSearchDailyLimit,
} from './infrastructure/app-settings';
import { addBrowserAccess } from './infrastructure/browser-access';
import { addProductionAutofix } from './infrastructure/autofix';
import { addGithubDeploymentRole } from './infrastructure/deployment-role';
import { addHttpApi } from './infrastructure/http-api';
import {
  addNativePushAccess,
  addNativePushFeedbackRole,
  nativePushEnvironment,
  resolveNativePushApplicationArns,
} from './infrastructure/native-push';
import { addObservability } from './infrastructure/observability';
import { addPublicAvailabilityProbe } from './infrastructure/production-readiness';
import { addProviderConnectionAccess } from './infrastructure/provider-connections';
const backend = defineBackend({ auth, preSignUp });
const stack = backend.createStack('FrogBotApp');
const nativePushApplications = resolveNativePushApplicationArns(
  stack,
  apnsApplicationArn,
  apnsSandboxApplicationArn,
);

const { cfnIdentityPool, cfnUserPool, cfnUserPoolClient } = backend.auth.resources.cfnResources;
// The app's public routes use API Gateway directly and never need AWS guest
// credentials. Keep the identity pool deny-by-default for signed-out devices.
cfnIdentityPool.allowUnauthenticatedIdentities = false;
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
// Authentication happens in the native/web clients through Cognito APIs. Do
// not synthesize the generated example.com hosted-UI callback configuration.
cfnUserPoolClient.allowedOAuthFlows = undefined;
cfnUserPoolClient.allowedOAuthFlowsUserPoolClient = false;
cfnUserPoolClient.allowedOAuthScopes = undefined;
cfnUserPoolClient.callbackUrLs = undefined;
cfnUserPoolClient.logoutUrLs = undefined;
cfnUserPoolClient.supportedIdentityProviders = ['COGNITO'];

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
  deletionProtection: deploymentEnvironment === 'production',
  encryption: TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: new Key(backend.auth.stack, 'InviteDataKey', {
    description: 'Encrypts FroggyBot invitation records.',
    enableKeyRotation: true,
    removalPolicy: RemovalPolicy.RETAIN,
  }),
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

const dataKey = new Key(stack, 'DataKey', {
  description: 'Encrypts FroggyBot customer messages, settings, and files.',
  enableKeyRotation: true,
  removalPolicy: RemovalPolicy.RETAIN,
});
const filesKeyAlias = deploymentEnvironment === 'production'
  ? 'alias/frogbot-production-user-files'
  : 'alias/frogbot-user-files';
dataKey.addAlias(filesKeyAlias);

const table = new Table(stack, 'Data', {
  partitionKey: { name: 'pk', type: AttributeType.STRING },
  sortKey: { name: 'sk', type: AttributeType.STRING },
  billingMode: BillingMode.PAY_PER_REQUEST,
  pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
  timeToLiveAttribute: 'expiresAt',
  removalPolicy: RemovalPolicy.RETAIN,
  deletionProtection: deploymentEnvironment === 'production',
  encryption: TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: dataKey,
});

const filesBucketPrefix = deploymentEnvironment === 'production'
  ? 'frogbot-production-user-files'
  : 'frogbot-user-files';
const filesBucket = new Bucket(stack, 'UserFiles', {
  bucketName: `${filesBucketPrefix}-${stack.account}-${stack.region}`,
  blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
  encryption: BucketEncryption.KMS,
  encryptionKey: dataKey,
  bucketKeyEnabled: true,
  enforceSSL: true,
  versioned: true,
  cors: [
    {
      allowedHeaders: ['*'],
      allowedMethods: [HttpMethods.GET, HttpMethods.HEAD, HttpMethods.POST],
      allowedOrigins: ALLOWED_WEB_ORIGINS,
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
logsKey.addAlias(`alias/frogbot-${deploymentEnvironment}-logs`);
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
const nativePushFeedbackRole = addNativePushFeedbackRole(
  stack,
  [nativePushApplications.production, nativePushApplications.sandbox],
  logsKey,
);
const githubDeployRole = addGithubDeploymentRole({
  stack,
  enabled: true,
  nativePushFeedbackRoleArn: nativePushFeedbackRole?.roleArn,
});

const auditBucket = new Bucket(stack, 'AuditLogs', {
  blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
  encryption: BucketEncryption.KMS,
  encryptionKey: logsKey,
  enforceSSL: true,
  versioned: true,
  lifecycleRules: [{
    id: 'RetainAuditRecordsSevenYears',
    abortIncompleteMultipartUploadAfter: Duration.days(1),
    expiration: Duration.days(2_555),
    noncurrentVersionExpiration: Duration.days(2_555),
  }],
  removalPolicy: RemovalPolicy.RETAIN,
});
const auditLogGroup = deploymentEnvironment === 'production'
  ? new LogGroup(stack, 'AuditCloudWatchLogs', {
      encryptionKey: logsKey,
      retention: RetentionDays.ONE_YEAR,
      removalPolicy: RemovalPolicy.RETAIN,
    })
  : undefined;
const auditTrail = new Trail(stack, 'AuditTrail', {
  bucket: auditBucket,
  encryptionKey: logsKey,
  enableFileValidation: true,
  includeGlobalServiceEvents: true,
  isMultiRegionTrail: true,
  sendToCloudWatchLogs: true,
  ...(auditLogGroup
    ? { cloudWatchLogGroup: auditLogGroup }
    : { cloudWatchLogsRetention: RetentionDays.ONE_MONTH }),
});
auditTrail.addS3EventSelector([{ bucket: filesBucket }], {
  readWriteType: ReadWriteType.ALL,
});

const deadLetterQueue = new Queue(stack, 'AgentJobsDeadLetter', {
  encryption: QueueEncryption.SQS_MANAGED,
  enforceSSL: true,
  retentionPeriod: Duration.days(14),
});
const jobs = new Queue(stack, 'AgentJobs', {
  encryption: QueueEncryption.SQS_MANAGED,
  enforceSSL: true,
  // AWS recommends at least six times the 14-minute Lambda timeout. The worker
  // uses an 85-minute active visibility/lease and shortens explicit failures.
  visibilityTimeout: Duration.minutes(90),
  retentionPeriod: Duration.days(4),
  deadLetterQueue: { queue: deadLetterQueue, maxReceiveCount: 3 },
});
const catalogRefresh = new Rule(stack, 'CatalogRefresh', {
  schedule: Schedule.rate(Duration.minutes(5)),
});
catalogRefresh.addTarget(
  new SqsQueue(jobs, {
    deadLetterQueue,
    retryAttempts: 2,
    message: RuleTargetInput.fromObject({ type: 'CATALOG_REFRESH' }),
  }),
);
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
  code: Code.fromAsset(path.resolve('amplify/functions'), {
    exclude: FUNCTION_ASSET_EXCLUDES,
  }),
  logGroup: apiLogGroup,
  timeout: Duration.seconds(29),
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
    AGENT_RUNTIME_QUALIFIER: runtimeQualifier,
    FROGBOT_MEMORY_ID: memoryId,
    FILES_BUCKET_NAME: filesBucket.bucketName,
    PUBLIC_WEB_BASE_URL,
    CAPABILITY_CATALOG_URL,
    FROGBOT_MONTHLY_RUN_UNIT_LIMIT: String(monthlyRunUnitLimit),
    FROGBOT_USER_WINDOW_RUN_UNIT_LIMIT: String(userWindowRunUnitLimit),
    FROGBOT_GLOBAL_WINDOW_RUN_UNIT_LIMIT: String(globalWindowRunUnitLimit),
    FROGBOT_USAGE_WINDOW_SECONDS: String(usageWindowSeconds),
    FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT: String(youtubeSearchDailyLimit),
    ...nativePushEnvironment(nativePushApplications.production, nativePushApplications.sandbox),
  },
});

const workerFunction = new LambdaFunction(stack, 'WorkerFunction', {
  ...functionDefaults,
  handler: 'worker.handler.handler',
  code: Code.fromAsset(path.resolve('amplify/functions'), {
    exclude: FUNCTION_ASSET_EXCLUDES,
  }),
  logGroup: workerLogGroup,
  timeout: Duration.minutes(14),
  // Long-running AgentCore jobs intentionally return bounded watchdog messages
  // to this queue. Allow that lineage past Lambda's approximate 16-hop cutoff;
  // application deadlines and reserved concurrency provide the guardrails.
  recursiveLoop: RecursiveLoop.ALLOW,
  reservedConcurrentExecutions: WORKER_CONCURRENCY,
  environment: {
    ...functionDefaults.environment,
    AGENT_RUNTIME_ARN: runtimeArn,
    AGENT_RUNTIME_QUALIFIER: runtimeQualifier,
    QUEUE_URL: jobs.queueUrl,
    QUEUE_ARN: jobs.queueArn,
    SCHEDULE_DLQ_ARN: deadLetterQueue.queueArn,
    SCHEDULE_GROUP_NAME: taskScheduleGroup.scheduleGroupName,
    SCHEDULE_ROLE_ARN: taskScheduleRole.roleArn,
    INVITE_TABLE_NAME: inviteAccess.tableName,
    USER_POOL_ID: backend.auth.resources.userPool.userPoolId,
    FROGBOT_MEMORY_ID: memoryId,
    FILES_BUCKET_NAME: filesBucket.bucketName,
    PUBLIC_WEB_BASE_URL,
    CAPABILITY_CATALOG_URL,
    FROGBOT_MONTHLY_RUN_UNIT_LIMIT: String(monthlyRunUnitLimit),
    FROGBOT_USER_WINDOW_RUN_UNIT_LIMIT: String(userWindowRunUnitLimit),
    FROGBOT_GLOBAL_WINDOW_RUN_UNIT_LIMIT: String(globalWindowRunUnitLimit),
    FROGBOT_USAGE_WINDOW_SECONDS: String(usageWindowSeconds),
    FROGBOT_YOUTUBE_SEARCH_DAILY_LIMIT: String(youtubeSearchDailyLimit),
    ...nativePushEnvironment(nativePushApplications.production, nativePushApplications.sandbox),
  },
});

table.grantReadWriteData(apiFunction);
addBrowserAccess(stack, apiFunction, workerFunction);
inviteAccess.grantReadWriteData(apiFunction);
inviteAccess.grantReadWriteData(workerFunction);
table.grantReadWriteData(workerFunction);
addNativePushAccess(apiFunction, workerFunction, [
  nativePushApplications.production,
  nativePushApplications.sandbox,
]);
apiFunction.addToRolePolicy(
  new PolicyStatement({
    actions: ['dynamodb:TransactWriteItems'],
    resources: [table.tableArn],
  }),
);
workerFunction.addToRolePolicy(
  new PolicyStatement({
    actions: ['dynamodb:TransactWriteItems'],
    resources: [table.tableArn],
  }),
);
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
      'secretsmanager:GetSecretValue',
      'secretsmanager:PutSecretValue',
      'secretsmanager:DeleteSecret',
      'secretsmanager:TagResource',
    ],
    resources: [connectionSecretsArn],
  }),
);
workerFunction.addToRolePolicy(
  new PolicyStatement({
    actions: ['secretsmanager:GetSecretValue', 'secretsmanager:DeleteSecret'],
    resources: [connectionSecretsArn],
  }),
);
jobs.grantSendMessages(apiFunction);
jobs.grantSendMessages(workerFunction);
taskScheduleGroup.grantWriteSchedules(apiFunction);
taskScheduleGroup.grantDeleteSchedules(apiFunction);
taskScheduleGroup.grantDeleteSchedules(workerFunction);
workerFunction.addToRolePolicy(
  new PolicyStatement({
    actions: ['cognito-idp:AdminDeleteUser', 'cognito-idp:AdminUserGlobalSignOut'],
    resources: [backend.auth.resources.userPool.userPoolArn],
  }),
);
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
    actions: [
      'bedrock-agentcore:InvokeCodeInterpreter',
      'bedrock-agentcore:StopCodeInterpreterSession',
    ],
    resources: ['*'],
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
    maxConcurrency: WORKER_CONCURRENCY,
    reportBatchItemFailures: true,
  }),
);
workerFunction.addToRolePolicy(
  new PolicyStatement({
    effect: Effect.ALLOW,
    actions: [
      'bedrock-agentcore:InvokeAgentRuntime',
      'bedrock-agentcore:InvokeAgentRuntimeForUser',
      'bedrock-agentcore:StopRuntimeSession',
    ],
    resources: [runtimeArn, `${runtimeArn}/runtime-endpoint/*`],
  }),
);
workerFunction.addToRolePolicy(
  new PolicyStatement({
    effect: Effect.ALLOW,
    actions: [
      'bedrock-agentcore:ListCodeInterpreterSessions',
      'bedrock-agentcore:InvokeCodeInterpreter',
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

const httpApi = addHttpApi({
  stack,
  apiFunction,
  apiAccessLogGroup,
  allowedOrigins: ALLOWED_WEB_ORIGINS,
  userPoolId: backend.auth.resources.userPool.userPoolId,
  userPoolClientId: backend.auth.resources.userPoolClient.userPoolClientId,
});
const availabilityProbe = addPublicAvailabilityProbe({
  stack,
  apiEndpoint: httpApi.apiEndpoint,
  logsKey,
  enabled: deploymentEnvironment === 'production',
});
addProviderConnectionAccess(apiFunction, httpApi.apiEndpoint, {
  github: githubAppSecretArn, google: googleOAuthSecretArn,
  microsoft: microsoftOAuthSecretArn, notion: notionOAuthSecretArn,
  slack: slackOAuthSecretArn, x: xOAuthSecretArn,
});

const autofix = addProductionAutofix({
  stack, table, workerLogGroup, logsKey, githubAppSecretArn, runtimeArn, runtimeQualifier,
  enabled: deploymentEnvironment === 'production',
});

const { alarmTopic, monthlyBudgetName } = addObservability({
  stack,
  apiFunction,
  workerFunction,
  workerLogGroup,
  apiAccessLogGroup,
  jobs,
  deadLetterQueue,
  logsKey,
  availabilityProbe,
  monthlyBudgetUsd,
  workerConcurrencyLimit: WORKER_CONCURRENCY,
});

backend.addOutput({
  custom: {
    environment: deploymentEnvironment,
    apiUrl: httpApi.apiEndpoint,
    shareBaseUrl: `${PUBLIC_WEB_BASE_URL}/invite`,
    dataTableName: table.tableName,
    inviteTableName: inviteAccess.tableName,
    filesBucketName: filesBucket.bucketName,
    alarmTopicArn: alarmTopic.topicArn,
    logsKeyArn: logsKey.keyArn,
    ...(nativePushFeedbackRole ? { nativePushFeedbackRoleArn: nativePushFeedbackRole.roleArn } : {}),
    ...(githubDeployRole ? { githubDeployRoleArn: githubDeployRole.roleArn } : {}),
    ...(autofix ? { autofixDispatcherArn: autofix.dispatcher.functionArn } : {}),
    monthlyBudgetName,
  },
});
