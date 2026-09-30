import assert from 'node:assert/strict';
import { test } from 'node:test';

import { App, Stack, Token } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { Topic } from 'aws-cdk-lib/aws-sns';

import { addBotEmailCapture } from '../amplify/infrastructure/bot-email-capture.ts';
import {
  botEmailCaptureOwner,
  validatedStandaloneCaptureBucket,
} from '../amplify/infrastructure/bot-email-capture-owner.ts';

test('SES notifications have a retained, unconsumed, account-scoped capture path', () => {
  const app = new App();
  const stack = new Stack(app, 'CaptureTest', {
    env: { account: '188757775631', region: 'us-east-1' },
  });
  addBotEmailCapture(stack, new Topic(stack, 'IncomingBotMailTopic'));
  const resources = Template.fromStack(stack).toJSON().Resources;
  const queues = Object.values(resources).filter((r) => r.Type === 'AWS::SQS::Queue');
  assert.equal(queues.length, 2);
  for (const queue of queues) {
    assert.equal(queue.Properties.MessageRetentionPeriod, 14 * 24 * 60 * 60);
    assert.equal(queue.Properties.SqsManagedSseEnabled, true);
    assert.equal(queue.DeletionPolicy, 'Retain');
    assert.equal(queue.UpdateReplacePolicy, 'Retain');
  }

  const subscriptions = Object.values(resources).filter((r) => r.Type === 'AWS::SNS::Subscription');
  assert.equal(subscriptions.length, 1);
  assert.equal(subscriptions[0].Properties.Protocol, 'sqs');
  assert.equal(subscriptions[0].Properties.RawMessageDelivery, false);
  assert.ok(subscriptions[0].Properties.RedrivePolicy.deadLetterTargetArn);
  assert.equal(
    Object.values(resources).filter((r) => r.Type === 'AWS::Lambda::EventSourceMapping').length,
    0,
  );

  const policies = Object.values(resources).filter((r) => r.Type === 'AWS::SQS::QueuePolicy');
  assert.equal(policies.length, 2);
  for (const policy of policies) {
    const grants = policy.Properties.PolicyDocument.Statement.filter(
      (statement) => statement.Effect === 'Allow' && statement.Action === 'sqs:SendMessage',
    );
    assert.equal(grants.length, 1);
    assert.deepEqual(grants[0].Principal, { Service: 'sns.amazonaws.com' });
    assert.equal(grants[0].Condition.StringEquals['aws:SourceAccount'], '188757775631');
    assert.ok(grants[0].Condition.ArnEquals['aws:SourceArn']);
  }
});

test('standalone destination capture is imported without a second queue or bucket', () => {
  const app = new App();
  const stack = new Stack(app, 'StandaloneCaptureTest', {
    env: { account: '820323452649', region: 'us-east-1' },
  });
  const bucketName = 'heytimdestinationmailcapt-botemailquarantinef3eb96-zuptorklfzuw';
  const result = botEmailCaptureOwner(
    stack, new Topic(stack, 'IncomingBotMailTopic'), bucketName,
  );
  assert.equal(result.standalone, true);
  assert.equal(result.quarantine.bucketName, bucketName);
  const resources = Object.values(Template.fromStack(stack).toJSON().Resources);
  for (const type of [
    'AWS::S3::Bucket', 'AWS::S3::BucketPolicy', 'AWS::SQS::Queue',
    'AWS::SQS::QueuePolicy', 'AWS::SNS::Subscription',
  ]) {
    assert.equal(resources.filter((resource) => resource.Type === type).length, 0);
  }
});

test('destination receipt stage requires the exact standalone capture owner', () => {
  const app = new App();
  const destination = new Stack(app, 'Destination', {
    env: { account: '820323452649', region: 'us-east-1' },
  });
  const source = new Stack(app, 'Source', {
    env: { account: '188757775631', region: 'us-east-1' },
  });
  const bucketName = 'heytimdestinationmailcapt-botemailquarantinef3eb96-zuptorklfzuw';
  assert.throws(() => validatedStandaloneCaptureBucket(destination, 'receive', undefined));
  assert.throws(() => validatedStandaloneCaptureBucket(destination, 'receive', 'wrong-bucket'));
  assert.throws(() => validatedStandaloneCaptureBucket(source, 'receive', bucketName));
  assert.throws(() => validatedStandaloneCaptureBucket(destination, 'identity', bucketName));
  assert.equal(validatedStandaloneCaptureBucket(destination, 'receive', bucketName), bucketName);
  assert.equal(validatedStandaloneCaptureBucket(source, 'receive', undefined), undefined);
});

test('unresolved Amplify account uses the checked CDK account and fails closed without it', () => {
  const app = new App();
  const stack = new Stack(app, 'UnresolvedAccount');
  const bucketName = 'heytimdestinationmailcapt-botemailquarantinef3eb96-zuptorklfzuw';
  assert.equal(Token.isUnresolved(stack.account), true);
  const previous = process.env.CDK_DEFAULT_ACCOUNT;
  try {
    delete process.env.CDK_DEFAULT_ACCOUNT;
    assert.throws(() => validatedStandaloneCaptureBucket(stack, 'receive', bucketName));
    process.env.CDK_DEFAULT_ACCOUNT = '188757775631';
    assert.throws(() => validatedStandaloneCaptureBucket(stack, 'receive', bucketName));
    assert.equal(validatedStandaloneCaptureBucket(stack, 'receive', undefined), undefined);
    process.env.CDK_DEFAULT_ACCOUNT = '820323452649';
    assert.throws(() => validatedStandaloneCaptureBucket(stack, 'receive', undefined));
    assert.equal(validatedStandaloneCaptureBucket(stack, 'receive', bucketName), bucketName);
  } finally {
    if (previous === undefined) delete process.env.CDK_DEFAULT_ACCOUNT;
    else process.env.CDK_DEFAULT_ACCOUNT = previous;
  }
});
