import { ArnFormat, Stack } from 'aws-cdk-lib';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import type { Function as LambdaFunction } from 'aws-cdk-lib/aws-lambda';

/** Only the authenticated app API may issue human browser access or save logins. */
export function addBrowserAccess(
  stack: Stack,
  api: LambdaFunction,
  worker: LambdaFunction,
) {
  const browserArn = stack.formatArn({
    service: 'bedrock-agentcore',
    account: 'aws',
    resource: 'browser',
    resourceName: 'aws.browser.v1',
    arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
  });
  const profilesArn = stack.formatArn({
    service: 'bedrock-agentcore',
    resource: 'browser-profile',
    resourceName: '*',
    arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
  });
  api.addToRolePolicy(new PolicyStatement({
    actions: [
      'bedrock-agentcore:StartBrowserSession',
      'bedrock-agentcore:GetBrowserSession',
      'bedrock-agentcore:StopBrowserSession',
      'bedrock-agentcore:UpdateBrowserStream',
      'bedrock-agentcore:ConnectBrowserLiveViewStream',
      'bedrock-agentcore:SaveBrowserSessionProfile',
    ],
    resources: [browserArn],
  }));
  for (const fn of [api, worker]) {
    // Account deletion may need to recover an uncertain create using its stored
    // idempotency token before deleting that exact profile.
    fn.addToRolePolicy(new PolicyStatement({
      actions: ['bedrock-agentcore:CreateBrowserProfile'],
      // CreateBrowserProfile has no resource-level authorization in AWS.
      resources: ['*'],
      conditions: { StringEquals: { 'aws:RequestTag/frogbot:managed-by': 'FrogBot' } },
    }));
    fn.addToRolePolicy(new PolicyStatement({
      actions: ['bedrock-agentcore:TagResource'],
      resources: [profilesArn],
      conditions: {
        StringEquals: { 'aws:RequestTag/frogbot:managed-by': 'FrogBot' },
        'ForAllValues:StringEquals': { 'aws:TagKeys': ['frogbot:managed-by'] },
      },
    }));
  }
  api.addToRolePolicy(new PolicyStatement({
    actions: [
      'bedrock-agentcore:GetBrowserProfile',
      'bedrock-agentcore:DeleteBrowserProfile',
      'bedrock-agentcore:SaveBrowserSessionProfile',
      'bedrock-agentcore:StartBrowserSession',
    ],
    resources: [profilesArn],
    conditions: { StringEquals: { 'aws:ResourceTag/frogbot:managed-by': 'FrogBot' } },
  }));
  worker.addToRolePolicy(new PolicyStatement({
    actions: [
      'bedrock-agentcore:GetBrowserSession',
      'bedrock-agentcore:StartBrowserSession',
      'bedrock-agentcore:StopBrowserSession',
    ],
    resources: [browserArn],
  }));
  worker.addToRolePolicy(new PolicyStatement({
    actions: [
      'bedrock-agentcore:StartBrowserSession',
      'bedrock-agentcore:DeleteBrowserProfile',
    ],
    resources: [profilesArn],
    conditions: { StringEquals: { 'aws:ResourceTag/frogbot:managed-by': 'FrogBot' } },
  }));
}
