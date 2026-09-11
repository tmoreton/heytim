import { ArnFormat, Duration, RemovalPolicy, type Stack } from 'aws-cdk-lib';
import { FederatedPrincipal, PolicyStatement, Role } from 'aws-cdk-lib/aws-iam';

type DeploymentRoleResources = {
  stack: Stack;
  enabled: boolean;
};

export function addGithubDeploymentRole({ stack, enabled }: DeploymentRoleResources) {
  if (!enabled) return undefined;

  const role = new Role(stack, 'GitHubProductionDeployRole', {
    description: 'Least-privilege GitHub OIDC entrypoint for reviewed FroggyBot production deployments.',
    assumedBy: new FederatedPrincipal(
      stack.formatArn({
        service: 'iam',
        region: '',
        resource: 'oidc-provider',
        resourceName: 'token.actions.githubusercontent.com',
        arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
      }),
      {
        StringEquals: {
          'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com',
          'token.actions.githubusercontent.com:sub': 'repo:tmoreton/frogbot:environment:production',
        },
      },
      'sts:AssumeRoleWithWebIdentity',
    ),
    maxSessionDuration: Duration.hours(1),
  });
  role.applyRemovalPolicy(RemovalPolicy.RETAIN);
  role.addToPolicy(new PolicyStatement({
    actions: ['sts:AssumeRole'],
    resources: [stack.formatArn({
      service: 'iam',
      region: '',
      resource: 'role',
      resourceName: 'cdk-hnb659fds-*',
      arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    })],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['bedrock-agentcore:*'],
    resources: ['*'],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['kms:DescribeKey'],
    resources: [stack.formatArn({
      service: 'kms',
      resource: 'key',
      resourceName: '*',
      arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    })],
    conditions: {
      'ForAnyValue:StringEquals': {
        'kms:ResourceAliases': 'alias/frogbot-production-logs',
      },
    },
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['logs:AssociateKmsKey', 'logs:PutRetentionPolicy'],
    resources: [stack.formatArn({
      service: 'logs',
      resource: 'log-group',
      resourceName: '/aws/bedrock-agentcore/runtimes/*',
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    })],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['amplify:GetApp', 'amplify:GetBranch', 'cloudformation:DescribeStacks'],
    resources: ['*'],
  }));
  return role;
}
