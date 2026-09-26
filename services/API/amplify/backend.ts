import { defineBackend } from '@aws-amplify/backend';
import { ArnFormat, Duration, RemovalPolicy } from 'aws-cdk-lib';
import { ReadWriteType, Trail } from 'aws-cdk-lib/aws-cloudtrail';
import { AttributeType, BillingMode, Table, TableEncryption } from 'aws-cdk-lib/aws-dynamodb';
import { EventField, Rule, RuleTargetInput, Schedule } from 'aws-cdk-lib/aws-events';
import { SqsQueue } from 'aws-cdk-lib/aws-events-targets';
import { Effect, PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import { Key } from 'aws-cdk-lib/aws-kms';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { BlockPublicAccess, Bucket, BucketEncryption, HttpMethods } from 'aws-cdk-lib/aws-s3';
import { ScheduleGroup } from 'aws-cdk-lib/aws-scheduler';
import { Queue, QueueEncryption } from 'aws-cdk-lib/aws-sqs';

import { preSignUp } from './auth/pre-sign-up/resource';
import { auth, emailCodeMessage } from './auth/resource';
import {
  ALLOWED_WEB_ORIGINS, CAPABILITY_CATALOG_URL,
  PUBLIC_WEB_BASE_URL,
  WORKER_CONCURRENCY, deploymentEnvironment,
  apnsApplicationArn, apnsSandboxApplicationArn, authEmailProvider,
  githubAppSecretArn, globalWindowRunUnitLimit, googleOAuthSecretArn,
  hubspotOAuthSecretArn, legacyTokenVaultKmsKeyArn,
  jiraOAuthSecretArn,
  zoomOAuthSecretArn,
  memoryId, memoryKmsKeyArn, microsoftOAuthSecretArn, monthlyBudgetUsd, monthlyRunUnitLimit,
  notionOAuthSecretArn, plaidSecretArn, quickBooksOAuthSecretArn,
  runtimeArn, runtimeQualifier, usageWindowSeconds, userWindowRunUnitLimit,
  slackOAuthSecretArn, xOAuthSecretArn, youtubeSearchDailyLimit,
  stripeAvailable,
} from './infrastructure/app-settings';
import { createApplicationFunctions } from './infrastructure/application-functions';
import { addBrowserAccess } from './infrastructure/browser-access';
import { addBotEmailReceiving } from './infrastructure/bot-email';
import { addProductionAutofix } from './infrastructure/autofix';
import { addGithubDeploymentRole } from './infrastructure/deployment-role';
import { addHttpApi } from './infrastructure/http-api';
import { addMemoryAccess } from './infrastructure/memory-access';
import {
  addNativePushAccess,
  addNativePushFeedbackRole,
  nativePushEnvironment,
  resolveNativePushApplicationArns,
} from './infrastructure/native-push';
import { addObservability, createApplicationLogGroups } from './infrastructure/observability';
import { addPlaidWebhook } from './infrastructure/plaid-webhook';
import { addPublicAvailabilityProbe } from './infrastructure/production-readiness';
import { addProviderConnectionAccess } from './infrastructure/provider-connections';
import { addStripeBilling } from './infrastructure/stripe-billing';
const backend = defineBackend({ auth, preSignUp });
// Keep the original identity so this updates rather than replaces live resources.
const stack = backend.createStack('FrogBotApp');
const nativePushApplications = resolveNativePushApplicationArns(
  stack,
  apnsApplicationArn,
  apnsSandboxApplicationArn,
);

const { cfnIdentityPool, cfnUserPool, cfnUserPoolClient } = backend.auth.resources.cfnResources;
// Public routes use API Gateway; keep signed-out AWS credentials deny-by-default.
cfnIdentityPool.allowUnauthenticatedIdentities = false;
// These IDs intentionally replace the immutable phone-only pool with email-only.
cfnUserPool.overrideLogicalId('FrogBotEmailUserPool');
cfnUserPoolClient.overrideLogicalId('FrogBotEmailUserPoolClient');
cfnUserPool.userPoolTier = 'ESSENTIALS';
cfnUserPool.deletionProtection = 'ACTIVE';
cfnUserPool.emailConfiguration = authEmailProvider === 'ses'
  ? {
      emailSendingAccount: 'DEVELOPER',
      sourceArn: `arn:aws:ses:${stack.region}:${stack.account}:identity/heytim.ai`,
      from: 'Hey Tim <no-reply@heytim.ai>',
    }
  : { emailSendingAccount: 'COGNITO_DEFAULT' };
// Username attributes already create Cognito's standard email schema. Omitting
// the generated schema prevents CloudFormation from re-submitting that immutable
// attribute as a new custom attribute on later updates.
cfnUserPool.schema = undefined;
cfnUserPool.addPropertyOverride('Policies.SignInPolicy.AllowedFirstAuthFactors', [
  'PASSWORD',
  'EMAIL_OTP',
]);
cfnUserPoolClient.explicitAuthFlows = ['ALLOW_REFRESH_TOKEN_AUTH', 'ALLOW_USER_AUTH'];
// Native/web clients use Cognito APIs, not the generated example.com hosted UI.
cfnUserPoolClient.allowedOAuthFlows = undefined;
cfnUserPoolClient.allowedOAuthFlowsUserPoolClient = false;
cfnUserPoolClient.allowedOAuthScopes = undefined;
cfnUserPoolClient.callbackUrLs = undefined;
cfnUserPoolClient.logoutUrLs = undefined;
cfnUserPoolClient.supportedIdentityProviders = ['COGNITO'];

cfnUserPool.emailAuthenticationSubject = 'Your Hey Tim sign-in code';
cfnUserPool.emailAuthenticationMessage = emailCodeMessage('{####}');
cfnUserPool.verificationMessageTemplate = {
  defaultEmailOption: 'CONFIRM_WITH_CODE',
  emailSubject: 'Your Hey Tim verification code',
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
    description: 'Encrypts HeyTim invitation records.',
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
  description: 'Encrypts HeyTim customer messages, settings, and files.',
  enableKeyRotation: true,
  removalPolicy: RemovalPolicy.RETAIN,
});
const filesKeyAlias = deploymentEnvironment === 'production'
  ? 'alias/heytim-production-user-files'
  : 'alias/heytim-user-files';
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

const legacyFilesBucketPrefix = deploymentEnvironment === 'production'
  ? 'frogbot-production-user-files'
  : 'frogbot-user-files';
const heytimFilesBucketPrefix = deploymentEnvironment === 'production'
  ? 'heytim-production-user-files'
  : 'heytim-user-files';
const filesBucketProperties = {
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
};
const legacyFilesBucket = new Bucket(stack, 'UserFiles', {
  ...filesBucketProperties,
  bucketName: `${legacyFilesBucketPrefix}-${stack.account}-${stack.region}`,
});
const heytimFilesBucket = new Bucket(stack, 'HeyTimUserFiles', {
  ...filesBucketProperties,
  bucketName: `${heytimFilesBucketPrefix}-${stack.account}-${stack.region}`,
});
// Retain the legacy bucket for rollback; route new access through the HeyTim copy.
const filesBucket = heytimFilesBucket;

const logsKey = new Key(stack, 'LogsKey', {
  description: 'Encrypts HeyTim application and audit logs.',
  enableKeyRotation: true,
  removalPolicy: RemovalPolicy.RETAIN,
});
logsKey.addAlias(`alias/heytim-${deploymentEnvironment}-logs`);
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
const {
  apiLogGroup, publicApiLogGroup, workerLogGroup, plaidWebhookLogGroup, apiAccessLogGroup,
} = createApplicationLogGroups(stack, logsKey);
const nativePushFeedbackRole = addNativePushFeedbackRole(
  stack,
  [nativePushApplications.production, nativePushApplications.sandbox],
  logsKey,
);
const githubDeployRole = addGithubDeploymentRole({
  stack,
  enabled: true,
  logsKmsKey: logsKey,
  legacyTokenVaultKmsKeyArn,
  nativePushApplicationArns: [
    nativePushApplications.production,
    nativePushApplications.sandbox,
  ],
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
auditTrail.addS3EventSelector([{ bucket: legacyFilesBucket }, { bucket: heytimFilesBucket }], {
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
const botEmail = deploymentEnvironment === 'production'
  ? addBotEmailReceiving({ stack, table, logsKey, jobs })
  : undefined;
const catalogRefresh = new Rule(stack, 'CatalogRefresh', {
  schedule: Schedule.rate(Duration.minutes(5)),
});
catalogRefresh.addTarget(
  new SqsQueue(jobs, {
    deadLetterQueue,
    retryAttempts: 2,
    message: RuleTargetInput.fromObject({
      schemaVersion: 1,
      type: 'CATALOG_REFRESH',
      correlationId: EventField.eventId,
      idempotencyKey: EventField.eventId,
      occurredAt: EventField.time,
    }),
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

const applicationEnvironment = {
  TABLE_NAME: table.tableName,
  QUEUE_URL: jobs.queueUrl,
  QUEUE_ARN: jobs.queueArn,
  SCHEDULE_DLQ_ARN: deadLetterQueue.queueArn,
  SCHEDULE_GROUP_NAME: taskScheduleGroup.scheduleGroupName,
  SCHEDULE_ROLE_ARN: taskScheduleRole.roleArn,
  INVITE_TABLE_NAME: inviteAccess.tableName,
  USER_POOL_ID: backend.auth.resources.userPool.userPoolId,
  AGENT_RUNTIME_ARN: runtimeArn,
  AGENT_RUNTIME_QUALIFIER: runtimeQualifier,
  HEYTIM_MEMORY_ID: memoryId,
  FILES_BUCKET_NAME: filesBucket.bucketName,
  PUBLIC_WEB_BASE_URL,
  BOT_EMAIL_AVAILABLE:
    deploymentEnvironment === 'production' && process.env.HEYTIM_BOT_EMAIL_AVAILABLE === 'true'
      ? 'true' : 'false',
  CAPABILITY_CATALOG_URL,
  HEYTIM_MONTHLY_RUN_UNIT_LIMIT: String(monthlyRunUnitLimit),
  HEYTIM_USER_WINDOW_RUN_UNIT_LIMIT: String(userWindowRunUnitLimit),
  HEYTIM_GLOBAL_WINDOW_RUN_UNIT_LIMIT: String(globalWindowRunUnitLimit),
  HEYTIM_USAGE_WINDOW_SECONDS: String(usageWindowSeconds),
  HEYTIM_YOUTUBE_SEARCH_DAILY_LIMIT: String(youtubeSearchDailyLimit),
  ...nativePushEnvironment(nativePushApplications.production, nativePushApplications.sandbox),
};
const { apiFunction, publicApiFunction, workerFunction } = createApplicationFunctions({
  stack,
  environment: applicationEnvironment,
  workerEnvironment: {
    EMAIL_QUEUE_URL: botEmail?.outboundQueue.queueUrl ?? '',
  },
  apiLogGroup,
  publicApiLogGroup,
  workerLogGroup,
  workerConcurrency: WORKER_CONCURRENCY,
});

const plaidWebhookFunction = addPlaidWebhook({
  stack, table, jobs, logGroup: plaidWebhookLogGroup,
  secretArn: plaidSecretArn, workerFunction,
});

table.grantReadWriteData(apiFunction);
table.grantReadWriteData(publicApiFunction);
addBrowserAccess(stack, apiFunction, workerFunction);
inviteAccess.grantReadWriteData(apiFunction);
inviteAccess.grantReadData(publicApiFunction);
inviteAccess.grantReadWriteData(workerFunction);
table.grantReadWriteData(workerFunction);
addStripeBilling(apiFunction, workerFunction, publicApiFunction);
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
workerFunction.addToRolePolicy(new PolicyStatement({
  actions: ['s3:ListBucketVersions'],
  resources: [filesBucket.bucketArn],
  conditions: { StringLike: { 's3:prefix': ['users/*', 'groups/*'] } },
}));
workerFunction.addToRolePolicy(new PolicyStatement({
  actions: ['s3:DeleteObjectVersion'],
  resources: [filesBucket.arnForObjects('users/*'), filesBucket.arnForObjects('groups/*')],
}));
const connectionSecretsArn = stack.formatArn({
  service: 'secretsmanager',
  resource: 'secret',
  resourceName: 'heytim/connections/*',
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
publicApiFunction.addToRolePolicy(
  new PolicyStatement({
    actions: [
      'secretsmanager:CreateSecret',
      'secretsmanager:GetSecretValue',
      'secretsmanager:PutSecretValue',
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
jobs.grantSendMessages(publicApiFunction);
jobs.grantSendMessages(workerFunction);
botEmail?.outboundQueue.grantSendMessages(workerFunction);
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
addMemoryAccess({
  stack, apiFunction, workerFunction, memoryId, memoryKmsKeyArn,
});

const httpApi = addHttpApi({
  stack,
  apiFunction,
  publicApiFunction,
  plaidWebhookFunction,
  apiAccessLogGroup,
  allowedOrigins: ALLOWED_WEB_ORIGINS,
  userPoolId: backend.auth.resources.userPool.userPoolId,
  userPoolClientId: backend.auth.resources.userPoolClient.userPoolClientId,
});
workerFunction.addEnvironment('PLAID_WEBHOOK_URL', httpApi.apiEndpoint + '/public/webhooks/plaid');
const availabilityProbe = addPublicAvailabilityProbe({
  stack,
  apiEndpoint: httpApi.apiEndpoint,
  logsKey,
  enabled: deploymentEnvironment === 'production',
});
addProviderConnectionAccess(apiFunction, httpApi.apiEndpoint, {
  github: githubAppSecretArn, google: googleOAuthSecretArn,
  hubspot: hubspotOAuthSecretArn,
  jira: jiraOAuthSecretArn,
  zoom: zoomOAuthSecretArn,
  microsoft: microsoftOAuthSecretArn, notion: notionOAuthSecretArn, plaid: plaidSecretArn, quickbooks: quickBooksOAuthSecretArn,
  slack: slackOAuthSecretArn, x: xOAuthSecretArn,
});
addProviderConnectionAccess(publicApiFunction, httpApi.apiEndpoint, {
  github: githubAppSecretArn, google: googleOAuthSecretArn,
  hubspot: hubspotOAuthSecretArn,
  jira: jiraOAuthSecretArn,
  zoom: zoomOAuthSecretArn,
  microsoft: microsoftOAuthSecretArn, notion: notionOAuthSecretArn, plaid: plaidSecretArn, quickbooks: quickBooksOAuthSecretArn,
  slack: slackOAuthSecretArn, x: xOAuthSecretArn,
});

const autofix = addProductionAutofix({
  stack, table, workerLogGroup, logsKey, githubAppSecretArn, runtimeArn, runtimeQualifier,
  enabled: deploymentEnvironment === 'production',
});

const { alarmTopic, monthlyBudgetName } = addObservability({
  stack,
  apiFunction,
  publicApiFunction,
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
    billingAvailable: stripeAvailable,
    stripeWebhookUrl: `${httpApi.apiEndpoint}/public/webhooks/stripe`,
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
