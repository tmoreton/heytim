import assert from 'node:assert/strict';
import test from 'node:test';

import { App, Stack } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { Key } from 'aws-cdk-lib/aws-kms';

import { addGithubDeploymentRole } from '../amplify/infrastructure/deployment-role.ts';

const actor = '3893a3ef3b21d5e84bd8a1117ce54afc4599424dc4c02cc5860ac572a921da56';
const destination = '820323452649';
const policyName = 'HeyTimSyntheticReleaseConsentRead';

function synth(account, releaseConsentFenceRead) {
  const stack = new Stack(new App(), 'Test', {
    env: { account, region: 'us-east-1' },
  });
  const logsKmsKey = new Key(stack, 'LogsKey');
  addGithubDeploymentRole({ stack, enabled: true, logsKmsKey, releaseConsentFenceRead });
  return Template.fromStack(stack).toJSON();
}

function syntheticPolicy(template) {
  return Object.values(template.Resources).filter(resource =>
    resource.Type === 'AWS::IAM::Policy'
    && resource.Properties.PolicyName === policyName);
}

test('default and legacy source synthesis do not create a synthetic consent read policy', () => {
  assert.equal(syntheticPolicy(synth(destination, false)).length, 0);
  assert.equal(syntheticPolicy(synth('188757775631', false)).length, 0);
});

test('destination release synthesis restricts the exact object and CloudFormation account', () => {
  const template = synth(destination, true);
  const [policy] = syntheticPolicy(template);
  assert.ok(policy);
  assert.equal(syntheticPolicy(template).length, 1);
  const [statement] = policy.Properties.PolicyDocument.Statement;
  assert.deepEqual(statement, {
    Effect: 'Allow',
    Action: 's3:GetObject',
    Resource: `arn:aws:s3:::heytim-production-user-files-${destination}-us-east-1/users/${actor}/ai-sharing-consent.json`,
  });
  const condition = template.Conditions[policy.Condition];
  assert.deepEqual(condition, {
    'Fn::Equals': [{ Ref: 'AWS::AccountId' }, destination],
  });
});

test('an accidental source opt-in remains blocked by the destination-account condition', () => {
  const template = synth('188757775631', true);
  const [policy] = syntheticPolicy(template);
  assert.ok(policy);
  const condition = template.Conditions[policy.Condition]['Fn::Equals'];
  assert.deepEqual(condition, [{ Ref: 'AWS::AccountId' }, destination]);
  assert.notEqual('188757775631', condition[1]);
});
