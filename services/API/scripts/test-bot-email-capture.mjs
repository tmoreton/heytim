import assert from 'node:assert/strict';
import { test } from 'node:test';

import { App, Stack } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { Topic } from 'aws-cdk-lib/aws-sns';

import { addBotEmailCapture } from '../amplify/infrastructure/bot-email-capture.ts';

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
