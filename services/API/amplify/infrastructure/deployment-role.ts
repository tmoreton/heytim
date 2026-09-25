import { ArnFormat, Duration, RemovalPolicy, type Stack } from 'aws-cdk-lib';
import { FederatedPrincipal, PolicyStatement, Role } from 'aws-cdk-lib/aws-iam';
import {
  BlockPublicAccess,
  Bucket,
  BucketEncryption,
  ObjectOwnership,
} from 'aws-cdk-lib/aws-s3';

type DeploymentRoleResources = {
  stack: Stack;
  enabled: boolean;
  legacyTokenVaultKmsKeyArn?: string;
  nativePushFeedbackRoleArn?: string;
};

export function addGithubDeploymentRole({
  stack,
  enabled,
  legacyTokenVaultKmsKeyArn,
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
  const tokenVaultKmsKeyArn = stack.formatArn({
    service: 'kms',
    resource: 'key',
    resourceName: '*',
    arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
  });
  const tokenVaultKmsResourceConditions = {
    StringEquals: {
      'aws:ResourceAccount': stack.account,
      'aws:ResourceTag/agentcore:project': 'HeyTim',
    },
  };
  const credentialProviderNames = [
    'HeyTim_OpenRouter',
    'HeyTimXApi',
    'HeyTimYouTubeApi',
  ];
  const credentialProviderArns = credentialProviderNames
    .map(name => agentCoreArn('token-vault', `default/apikeycredentialprovider/${name}`));
  const credentialSecretArns = credentialProviderNames.map(name => stack.formatArn({
    service: 'secretsmanager',
    resource: 'secret',
    resourceName: `bedrock-agentcore-identity!default/apikey/${name}-*`,
    arnFormat: ArnFormat.COLON_RESOURCE_NAME,
  }));
  const stripeSecretArn = stack.formatArn({
    service: 'secretsmanager',
    resource: 'secret',
    resourceName: 'heytim/stripe/production-*',
    arnFormat: ArnFormat.COLON_RESOURCE_NAME,
  });
  const productionOnlineEvaluationRoleArn = stack.formatArn({
    service: 'iam',
    region: '',
    resource: 'role',
    // CloudFormation appends a generated suffix and may truncate the logical ID.
    resourceName: 'AgentCore-HeyTim-product-ApplicationOnlineEval*',
    arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
  });
  const projectResourceCondition = {
    StringEquals: {
      'aws:ResourceTag/agentcore:project-name': 'HeyTim',
    },
  };
  const productionFilesBucketName = `heytim-production-user-files-${stack.account}-${stack.region}`;
  const productionFilesBucketArn = stack.formatArn({
    service: 's3',
    region: '',
    account: '',
    resource: productionFilesBucketName,
    arnFormat: ArnFormat.NO_RESOURCE_NAME,
  });
  const gatewaySchemaBucketName = `bedrock-agentcore-gateway-heytim-${stack.account}-use1`;
  const gatewaySchemaBucket = new Bucket(stack, 'HeyTimGatewaySchemas', {
    bucketName: gatewaySchemaBucketName,
    blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
    encryption: BucketEncryption.S3_MANAGED,
    enforceSSL: true,
    objectOwnership: ObjectOwnership.BUCKET_OWNER_ENFORCED,
    removalPolicy: RemovalPolicy.RETAIN,
    versioned: true,
  });
  const gatewaySchemaBucketArn = gatewaySchemaBucket.bucketArn;
  const productionGatewayRoleArn = stack.formatArn({
    service: 'iam',
    region: '',
    resource: 'role',
    // AgentCore truncates the production stack segment before appending the
    // generated suffix. Keep this scoped to the one production gateway role.
    resourceName: 'AgentCore-HeyTim-producti-McpGatewayHeyTimToolsRole-*',
    arnFormat: ArnFormat.SLASH_RESOURCE_NAME,
  });

  const role = new Role(stack, 'GitHubProductionDeployRole', {
    description: 'Least-privilege GitHub OIDC entrypoint for reviewed HeyTim production deployments.',
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
          // GitHub's customized OIDC subject includes the immutable repository ID.
          'token.actions.githubusercontent.com:sub':
            'repo:tmoreton@5090418/heytim@1356546597:environment:production',
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
  if (legacyTokenVaultKmsKeyArn) {
    // AgentCore has one account-wide token vault. Existing credentials remain
    // encrypted with this explicitly configured pre-rename key until a
    // separately reviewed key migration can rotate every credential provider.
    role.addToPolicy(new PolicyStatement({
      actions: ['kms:DescribeKey'],
      resources: [legacyTokenVaultKmsKeyArn],
      conditions: {
        StringEquals: {
          'aws:ResourceAccount': stack.account,
        },
      },
    }));
    role.addToPolicy(new PolicyStatement({
      actions: [
        'kms:Decrypt',
        'kms:Encrypt',
        'kms:GenerateDataKeyWithoutPlaintext',
      ],
      resources: [legacyTokenVaultKmsKeyArn],
      conditions: {
        StringEquals: {
          'aws:ResourceAccount': stack.account,
          'kms:ViaService': `bedrock-agentcore-identity.${stack.region}.amazonaws.com`,
          'kms:EncryptionContext:aws-crypto-ec:aws:bedrock-agentcore-identity:token-vault-arn':
            tokenVaultArn,
        },
      },
    }));
  }
  role.addToPolicy(new PolicyStatement({
    actions: ['bedrock-agentcore:GetTokenVault'],
    resources: [tokenVaultArn],
  }));
  role.addToPolicy(new PolicyStatement({
    // AgentCore currently authorizes this API against its non-resource control
    // route ARN, so the action cannot be constrained to the documented vault ARN.
    actions: ['bedrock-agentcore:SetTokenVaultCMK'],
    resources: ['*'],
  }));
  role.addToPolicy(new PolicyStatement({
    // AgentCore CLI creates the token-vault encryption key with this project tag.
    // CreateKey requires "*" because the key ARN does not exist until the call succeeds.
    actions: ['kms:CreateKey', 'kms:TagResource'],
    resources: ['*'],
    conditions: {
      StringEquals: {
        'aws:RequestTag/agentcore:project': 'HeyTim',
      },
      'ForAllValues:StringEquals': {
        'aws:TagKeys': ['agentcore:project'],
      },
    },
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['kms:DescribeKey'],
    resources: [tokenVaultKmsKeyArn],
    conditions: tokenVaultKmsResourceConditions,
  }));
  role.addToPolicy(new PolicyStatement({
    actions: [
      'kms:Decrypt',
      'kms:Encrypt',
      'kms:GenerateDataKeyWithoutPlaintext',
    ],
    resources: [tokenVaultKmsKeyArn],
    conditions: {
      StringEquals: {
        ...tokenVaultKmsResourceConditions.StringEquals,
        'kms:ViaService': `bedrock-agentcore-identity.${stack.region}.amazonaws.com`,
        'kms:EncryptionContext:aws-crypto-ec:aws:bedrock-agentcore-identity:token-vault-arn':
          tokenVaultArn,
      },
    },
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
    actions: [
      'secretsmanager:CreateSecret',
      'secretsmanager:GetSecretValue',
      'secretsmanager:PutSecretValue',
    ],
    resources: credentialSecretArns,
  }));
  role.addToPolicy(new PolicyStatement({
    actions: [
      'secretsmanager:CreateSecret',
      'secretsmanager:DescribeSecret',
      'secretsmanager:PutSecretValue',
    ],
    resources: [stripeSecretArn],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: [
      'bedrock-agentcore:CreateGatewayTarget',
      'bedrock-agentcore:GetGateway',
      'bedrock-agentcore:GetGatewayTarget',
      'bedrock-agentcore:InvokeGateway',
      'bedrock-agentcore:ListGatewayTargets',
      'bedrock-agentcore:SynchronizeGatewayTargets',
      'bedrock-agentcore:UpdateGatewayTarget',
    ],
    resources: [agentCoreArn('gateway', '*')],
    conditions: projectResourceCondition,
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['iam:GetRolePolicy', 'iam:PutRolePolicy'],
    resources: [productionGatewayRoleArn],
  }));
  role.addToPolicy(new PolicyStatement({
    actions: ['s3:GetObject', 's3:PutObject'],
    resources: [
      `${gatewaySchemaBucketArn}/releases/skills-v*/x/openapi.yaml`,
      `${gatewaySchemaBucketArn}/releases/skills-v*/youtube/openapi.yaml`,
    ],
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
        'kms:ResourceAliases': ['alias/heytim-production-logs'],
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
    resources: ['HeyTim'].map(name => stack.formatArn({
      service: 'cloudwatch',
      resource: 'alarm',
      resourceName: `${name}-production-*`,
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    })),
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
      resourceName: 'HeyTim',
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
        'kms:ResourceAliases': 'alias/heytim-production-user-files',
      },
    },
  }));
  role.addToPolicy(new PolicyStatement({
    actions: [
      'amplify:GetApp',
      'amplify:GetBranch',
      'cloudformation:DescribeStacks',
      'cloudformation:GetTemplateSummary',
    ],
    resources: ['*'],
  }));
  return role;
}
