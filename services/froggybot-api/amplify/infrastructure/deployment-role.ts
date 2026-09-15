import { ArnFormat, Duration, RemovalPolicy, type Stack } from 'aws-cdk-lib';
import { FederatedPrincipal, PolicyStatement, Role } from 'aws-cdk-lib/aws-iam';

type DeploymentRoleResources = {
  stack: Stack;
  enabled: boolean;
  nativePushFeedbackRoleArn?: string;
};

export function addGithubDeploymentRole({
  stack,
  enabled,
  nativePushFeedbackRoleArn,
}: DeploymentRoleResources) {
  if (!enabled) return undefined;

  const agentCoreArn = (resource: string, resourceName: string) => stack.formatArn({
    service: 'bedrock-agentcore',
    resource,
    resourceName,
    arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
  });
  const tokenVaultArn = agentCoreArn('token-vault', 'default');
  const credentialProviderArns = [
    'FrogBot_OpenRouter',
    'FrogBotXApi',
    'FrogBotYouTubeApi',
  ].map(name => agentCoreArn('token-vault', `default/apikeycredentialprovider/${name}`));
  const productionOnlineEvaluationRoleArn = stack.formatArn({
    service: 'iam',
    region: '',
    resource: 'role',
    // CloudFormation appends a generated suffix and may truncate the logical ID.
    resourceName: 'AgentCore-FrogBot-product-ApplicationOnlineEval*',
    arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
  });
  const projectResourceCondition = {
    StringEquals: {
      'aws:ResourceTag/agentcore:project-name': 'FrogBot',
    },
  };
  const productionFilesBucketName = `frogbot-production-user-files-${stack.account}-${stack.region}`;
  const productionFilesBucketArn = stack.formatArn({
    service: 's3',
    region: '',
    account: '',
    resource: productionFilesBucketName,
    arnFormat: ArnFormat.NO_RESOURCE_NAME,
  });

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
          // GitHub's customized OIDC subject binds the owner and repository names to
          // their immutable IDs, so a rename or name reuse cannot inherit production access.
          'token.actions.githubusercontent.com:sub':
            'repo:tmoreton@5090418/frogbot@1356546597:environment:production',
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
    actions: ['bedrock-agentcore:GetTokenVault'],
    resources: [tokenVaultArn],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: [
      'bedrock-agentcore:CreateApiKeyCredentialProvider',
      'bedrock-agentcore:GetApiKeyCredentialProvider',
      'bedrock-agentcore:UpdateApiKeyCredentialProvider',
    ],
    resources: [tokenVaultArn, ...credentialProviderArns],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['bedrock-agentcore:TagResource'],
    resources: credentialProviderArns,
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['bedrock-agentcore:ListGatewayTargets'],
    resources: [agentCoreArn('gateway', '*')],
    conditions: projectResourceCondition,
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['bedrock-agentcore:UpdateOnlineEvaluationConfig'],
    resources: [agentCoreArn('online-evaluation-config', '*')],
    conditions: projectResourceCondition,
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['iam:PassRole'],
    resources: [productionOnlineEvaluationRoleArn],
    conditions: {
      StringEquals: {
        'iam:PassedToService': 'bedrock-agentcore.amazonaws.com',
      },
    },
  }));
  role.addToPolicy(new PolicyStatement({
    actions: [
      'bedrock-agentcore:GetDataset',
      'bedrock-agentcore:AddDatasetExamples',
      'bedrock-agentcore:UpdateDatasetExamples',
      'bedrock-agentcore:DeleteDatasetExamples',
    ],
    resources: [agentCoreArn('dataset', '*')],
    conditions: projectResourceCondition,
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
    actions: ['logs:DescribeLogGroups'],
    resources: ['*'],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['cloudwatch:PutMetricAlarm'],
    resources: [stack.formatArn({
      service: 'cloudwatch',
      resource: 'alarm',
      resourceName: 'FroggyBot-production-*',
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    })],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['cloudwatch:DescribeAlarms'],
    resources: ['*'],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['sns:SetPlatformApplicationAttributes', 'sns:GetPlatformApplicationAttributes'],
    resources: [stack.formatArn({
      service: 'sns',
      resource: 'app/APNS*',
      resourceName: 'FroggyBot',
      arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    })],
  }));
  if (nativePushFeedbackRoleArn) {
    role.addToPolicy(new PolicyStatement({
      actions: ['iam:PassRole'],
      resources: [nativePushFeedbackRoleArn],
      conditions: {
        StringEquals: {
          'iam:PassedToService': 'sns.amazonaws.com',
        },
      },
    }));
  }
  role.addToPolicy(new PolicyStatement({
    actions: ['sns:ListSubscriptionsByTopic'],
    resources: [stack.formatArn({
      service: 'sns',
      resource: '*',
      arnFormat: ArnFormat.NO_RESOURCE_NAME,
    })],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['dynamodb:DescribeTable', 'dynamodb:DescribeContinuousBackups'],
    resources: [stack.formatArn({
      service: 'dynamodb',
      resource: 'table',
      resourceName: '*',
      arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    })],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['s3:ListBucket', 's3:GetBucketLocation', 's3:GetBucketVersioning', 's3:GetEncryptionConfiguration'],
    resources: [productionFilesBucketArn],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['s3:GetObject', 's3:PutObject'],
    resources: [`${productionFilesBucketArn}/meme-templates/*`],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['kms:Decrypt', 'kms:DescribeKey', 'kms:Encrypt', 'kms:GenerateDataKey'],
    resources: [stack.formatArn({
      service: 'kms',
      resource: 'key',
      resourceName: '*',
      arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
    })],
    conditions: {
      'ForAnyValue:StringEquals': {
        'kms:ResourceAliases': 'alias/frogbot-production-user-files',
      },
    },
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['amplify:GetApp', 'amplify:GetBranch', 'cloudformation:DescribeStacks'],
    resources: ['*'],
  }));
  return role;
}
