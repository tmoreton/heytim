/** Addition-only source-account capture stack. Never deploy it with Amplify. */
import { App, Stack } from 'aws-cdk-lib';
import { ArnPrincipal, CfnPolicy, Effect, PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Topic } from 'aws-cdk-lib/aws-sns';

import { addBotEmailCapture } from './infrastructure/bot-email-capture';
import { addBotEmailQuarantine } from './infrastructure/bot-email-quarantine';

const account = '188757775631';
const region = 'us-east-1';
const topicArn = process.env.HEYTIM_SOURCE_MAIL_TOPIC_ARN;
const roleArn = process.env.HEYTIM_SOURCE_SES_ROLE_ARN;
if (!topicArn?.startsWith(`arn:aws:sns:${region}:${account}:`)) {
  throw new Error('Set the exact source-account HEYTIM_SOURCE_MAIL_TOPIC_ARN.');
}
if (!roleArn?.startsWith(`arn:aws:iam::${account}:role/`)) {
  throw new Error('Set the exact source-account HEYTIM_SOURCE_SES_ROLE_ARN.');
}

const app = new App();
const stack = new Stack(app, 'HeyTimSourceMailCapture', {
  env: { account, region },
  terminationProtection: true,
});
const topic = Topic.fromTopicArn(stack, 'ExistingIncomingBotMailTopic', topicArn);
addBotEmailCapture(stack, topic);
const quarantine = addBotEmailQuarantine(stack);
// This adds one separately managed inline policy to the existing role; it
// does not rename or replace that role or change its existing policy.
new CfnPolicy(stack, 'BotEmailQuarantineSesWritePolicy', {
  policyName: 'HeyTimBotEmailQuarantineWrite',
  roles: [roleArn.split('/').at(-1)!],
  policyDocument: {
    Version: '2012-10-17',
    Statement: [{
      Effect: 'Allow',
      Action: 's3:PutObject',
      Resource: quarantine.arnForObjects('received/*'),
    }],
  },
});
quarantine.addToResourcePolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  principals: [new ArnPrincipal(roleArn)],
  actions: ['s3:PutObject'],
  resources: [quarantine.arnForObjects('received/*')],
}));
app.synth();
