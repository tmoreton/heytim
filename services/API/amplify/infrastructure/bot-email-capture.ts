import { CfnOutput, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import { Effect, PolicyStatement, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import { CfnSubscription, ITopic } from 'aws-cdk-lib/aws-sns';
import { Queue, QueueEncryption } from 'aws-cdk-lib/aws-sqs';

/** Store SES S3-action notifications independently of the app mail receiver. */
export function addBotEmailCapture(stack: Stack, topic: ITopic): void {
  const captureFailures = new Queue(stack, 'BotEmailInboundCaptureFailures', {
    encryption: QueueEncryption.SQS_MANAGED,
    enforceSSL: true,
    retentionPeriod: Duration.days(14),
    removalPolicy: RemovalPolicy.RETAIN,
  });
  const capture = new Queue(stack, 'BotEmailInboundCapture', {
    encryption: QueueEncryption.SQS_MANAGED,
    enforceSSL: true,
    retentionPeriod: Duration.days(14),
    receiveMessageWaitTime: Duration.seconds(20),
    removalPolicy: RemovalPolicy.RETAIN,
  });
  // Topic ARN and account are both checked, including for SNS redrive.
  const publisher = (queue: Queue): PolicyStatement => new PolicyStatement({
    effect: Effect.ALLOW,
    principals: [new ServicePrincipal('sns.amazonaws.com')],
    actions: ['sqs:SendMessage'],
    resources: [queue.queueArn],
    conditions: {
      ArnEquals: { 'aws:SourceArn': topic.topicArn },
      StringEquals: { 'aws:SourceAccount': stack.account },
    },
  });
  const captureGrant = capture.addToResourcePolicy(publisher(capture));
  const failureGrant = captureFailures.addToResourcePolicy(publisher(captureFailures));
  const subscription = new CfnSubscription(stack, 'BotEmailInboundCaptureSubscription', {
    topicArn: topic.topicArn,
    protocol: 'sqs',
    endpoint: capture.queueArn,
    rawMessageDelivery: false,
    redrivePolicy: { deadLetterTargetArn: captureFailures.queueArn },
  });
  if (captureGrant.policyDependable) subscription.node.addDependency(captureGrant.policyDependable);
  if (failureGrant.policyDependable) subscription.node.addDependency(failureGrant.policyDependable);
  new CfnOutput(stack, 'BotEmailInboundCaptureQueueArn', { value: capture.queueArn });
  new CfnOutput(stack, 'BotEmailInboundCaptureQueueUrl', { value: capture.queueUrl });
  new CfnOutput(stack, 'BotEmailInboundCaptureFailuresQueueArn', {
    value: captureFailures.queueArn,
  });
}
