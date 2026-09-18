import { CfnOutput, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import { Code, Function as LambdaFunction, Runtime, Tracing } from 'aws-cdk-lib/aws-lambda';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { BlockPublicAccess, Bucket, BucketEncryption } from 'aws-cdk-lib/aws-s3';
import { CfnEmailIdentity, CfnReceiptRule, CfnReceiptRuleSet } from 'aws-cdk-lib/aws-ses';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { LambdaSubscription } from 'aws-cdk-lib/aws-sns-subscriptions';
import { Queue, QueueEncryption } from 'aws-cdk-lib/aws-sqs';
import path from 'node:path';

import { FUNCTION_ASSET_EXCLUDES } from './app-settings';

type BotEmailProps = {
  stack: Stack;
  table: Table;
  logsKey: import('aws-cdk-lib/aws-kms').Key;
};

export function addBotEmailReceiving({ stack, table, logsKey }: BotEmailProps): void {
  const domain = 'bots.heytim.ai';
  const stage = process.env.FROGBOT_BOT_EMAIL_STAGE;
  if (stage !== 'identity' && stage !== 'receive') {
    throw new Error('Set FROGBOT_BOT_EMAIL_STAGE to identity or receive for production.');
  }
  if (process.env.FROGBOT_BOT_EMAIL_AVAILABLE === 'true' && stage !== 'receive') {
    throw new Error('Bot email cannot be available before its receiver is deployed.');
  }
  const configuredRuleSet = process.env.FROGBOT_SES_RULE_SET_NAME?.trim();
  const ruleSetName = configuredRuleSet || 'frogbot-production-bot-mail';
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(ruleSetName)) {
    throw new Error('FROGBOT_SES_RULE_SET_NAME must be a valid SES receipt rule set name.');
  }
  const identity = new CfnEmailIdentity(stack, 'BotEmailIdentity', {
    emailIdentity: domain,
  });
  new CfnOutput(stack, 'BotEmailMx', {
    value: `10 inbound-smtp.${stack.region}.amazonaws.com`,
    description: `MX record for ${domain}`,
  });
  for (const [index, name, value] of [
    [1, identity.attrDkimDnsTokenName1, identity.attrDkimDnsTokenValue1],
    [2, identity.attrDkimDnsTokenName2, identity.attrDkimDnsTokenValue2],
    [3, identity.attrDkimDnsTokenName3, identity.attrDkimDnsTokenValue3],
  ] as const) {
    new CfnOutput(stack, `BotEmailDkimName${index}`, { value: name });
    new CfnOutput(stack, `BotEmailDkimValue${index}`, { value });
  }
  if (stage === 'identity') return;

  const bucket = new Bucket(stack, 'IncomingBotMail', {
    blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
    encryption: BucketEncryption.S3_MANAGED,
    enforceSSL: true,
    lifecycleRules: [{ expiration: Duration.days(7) }],
    removalPolicy: RemovalPolicy.RETAIN,
  });
  const topic = new Topic(stack, 'IncomingBotMailTopic', { enforceSSL: true });
  const deliveryFailures = new Queue(stack, 'BotEmailDeliveryFailures', {
    encryption: QueueEncryption.SQS_MANAGED,
    enforceSSL: true,
    retentionPeriod: Duration.days(14),
  });
  const receiver = new LambdaFunction(stack, 'BotEmailReceiver', {
    runtime: Runtime.PYTHON_3_14,
    handler: 'email_ingest.handler.handler',
    code: Code.fromAsset(path.resolve('amplify/functions'), {
      exclude: FUNCTION_ASSET_EXCLUDES,
    }),
    memorySize: 512,
    timeout: Duration.seconds(60),
    tracing: Tracing.ACTIVE,
    deadLetterQueue: deliveryFailures,
    logGroup: new LogGroup(stack, 'BotEmailReceiverLogs', {
      encryptionKey: logsKey,
      retention: RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.RETAIN,
    }),
    environment: {
      TABLE_NAME: table.tableName,
      MAIL_BUCKET_NAME: bucket.bucketName,
      MAIL_TOPIC_ARN: topic.topicArn,
      MAIL_PROCESSING_ENABLED: process.env.FROGBOT_BOT_EMAIL_AVAILABLE === 'true' ? 'true' : 'false',
    },
  });
  table.grantReadWriteData(receiver);
  receiver.addToRolePolicy(new PolicyStatement({
    actions: ['dynamodb:TransactWriteItems'], resources: [table.tableArn],
  }));
  bucket.grantRead(receiver, 'received/*');
  topic.addSubscription(new LambdaSubscription(receiver, { deadLetterQueue: deliveryFailures }));

  const receiveRole = new Role(stack, 'BotEmailSesDeliveryRole', {
    assumedBy: new ServicePrincipal('ses.amazonaws.com', {
      conditions: { StringEquals: {
        'aws:SourceAccount': stack.account,
        'aws:SourceArn': `arn:aws:ses:${stack.region}:${stack.account}:receipt-rule-set/${ruleSetName}:receipt-rule/FroggyBotBotInbox`,
      } },
    }),
  });
  const bucketGrant = bucket.grantPut(receiveRole, 'received/*');
  const topicGrant = topic.grantPublish(receiveRole);

  const ruleSet = configuredRuleSet
    ? undefined
    : new CfnReceiptRuleSet(stack, 'BotEmailRuleSet', {
        ruleSetName,
      });
  const rule = new CfnReceiptRule(stack, 'BotEmailReceiptRule', {
    ruleSetName,
    rule: {
      name: 'FroggyBotBotInbox',
      enabled: true,
      scanEnabled: true,
      recipients: [domain],
      actions: [{
        s3Action: {
          bucketName: bucket.bucketName,
          objectKeyPrefix: 'received/',
          topicArn: topic.topicArn,
          iamRoleArn: receiveRole.roleArn,
        },
      }],
    },
  });
  if (ruleSet) rule.node.addDependency(ruleSet);
  rule.node.addDependency(identity);
  bucketGrant.applyBefore(rule);
  topicGrant.applyBefore(rule);
  new CfnOutput(stack, 'BotEmailRuleSetName', {
    value: ruleSetName,
  });
}
