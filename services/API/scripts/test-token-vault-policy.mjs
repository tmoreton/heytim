import assert from 'node:assert/strict';
import test from 'node:test';

import { App, Stack } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { Key } from 'aws-cdk-lib/aws-kms';

import { addGithubDeploymentRole } from '../amplify/infrastructure/deployment-role.ts';

function deploymentStatements(account) {
  const stack = new Stack(new App(), 'Test', {
    env: { account, region: 'us-east-1' },
  });
  const logsKmsKey = new Key(stack, 'LogsKey');
  addGithubDeploymentRole({ stack, enabled: true, logsKmsKey });
  const template = Template.fromStack(stack).toJSON();
  return Object.values(template.Resources)
    .filter(resource => resource.Type === 'AWS::IAM::Policy')
    .flatMap(resource => resource.Properties.PolicyDocument.Statement);
}

const asArray = value => Array.isArray(value) ? value : [value];
const matches = (pattern, action) => new RegExp(`^${pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replaceAll('*', '.*')}$`, 'i').test(action);
const grants = (statement, action) => statement.Effect === 'Allow'
  && asArray(statement.Action).some(pattern => matches(pattern, action));

for (const account of ['820323452649', '188757775631']) {
  test(`${account}: the CLI default-vault request can use the regional control route`, () => {
    const statements = deploymentStatements(account);
    const lookups = statements.filter(statement => grants(statement, 'bedrock-agentcore:GetTokenVault'));
    assert.equal(lookups.length, 1);
    assert.deepEqual(asArray(lookups[0].Resource), ['*']);
    assert.equal(lookups[0].Condition.StringEquals['aws:RequestedRegion'], 'us-east-1');
  });

  test(`${account}: a failed vault lookup cannot bootstrap or replace its KMS key`, () => {
    const statements = deploymentStatements(account);
    for (const action of ['kms:CreateKey', 'kms:TagResource', 'bedrock-agentcore:SetTokenVaultCMK']) {
      assert.equal(statements.some(statement => grants(statement, action)), false, action);
    }
    for (const action of ['bedrock-agentcore:CreateApiKeyCredentialProvider', 'bedrock-agentcore:UpdateApiKeyCredentialProvider']) {
      assert.equal(statements.some(statement => grants(statement, action)), true, action);
    }
  });
}
