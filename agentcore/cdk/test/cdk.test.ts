import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { ConfigIO } from '@aws/agentcore-cdk';
import * as fs from 'fs';
import * as path from 'path';
import { AgentCoreStack } from '../lib/cdk-stack';
import { dirtySourceEntries } from '../lib/deploy-preflight';
import {
  UNCONFIGURED_AWS_ACCOUNT,
  assertProductionTargetConfigured,
  bindSpecToTarget,
  filesBucketName,
} from '../lib/target-bindings';

test('deployment preflight rejects source changes but ignores generated deploy state', () => {
  expect(
    dirtySourceEntries(
      ' M services/agent-runtime/runtime/main.py\n' + ' M agentcore/.cli/deployed-state.json\n' + '?? scratch.txt\n'
    )
  ).toEqual([' M services/agent-runtime/runtime/main.py', '?? scratch.txt']);
});

test('AgentCoreStack synthesizes with a minimal resource spec', () => {
  const app = new cdk.App();
  const stack = new AgentCoreStack(app, 'TestStack', {
    spec: {
      name: 'testproject',
      version: 1,
      managedBy: 'CDK' as const,
      runtimes: [],
      memories: [
        {
          name: 'TestMemory',
          eventExpiryDuration: 30,
          strategies: [],
        },
      ],
      credentials: [],
      evaluators: [],
      onlineEvalConfigs: [],
      configBundles: [],
      policyEngines: [],
      payments: [],
      agentCoreGateways: [],
      mcpRuntimeTools: [],
      unassignedTargets: [],
      datasets: [],
      knowledgeBases: [],
    },
  });
  const template = Template.fromStack(stack);
  template.hasOutput('StackNameOutput', {
    Description: 'Name of the CloudFormation Stack',
  });
});

test('runtime roles can use the configured memory encryption key', async () => {
  const configRoot = path.resolve(__dirname, '../..');
  const source = await new ConfigIO({ baseDir: configRoot }).readProjectSpec();
  const memoryKeyArn = 'arn:aws:kms:us-east-1:123456789012:key/memory-key';
  const spec = {
    ...source,
    memories: source.memories.map(memory => ({ ...memory, encryptionKeyArn: memoryKeyArn })),
    evaluators: [],
    onlineEvalConfigs: [],
    agentCoreGateways: [],
  };
  const app = new cdk.App();
  const stack = new AgentCoreStack(app, 'MemoryKeyStack', {
    env: { account: '123456789012', region: 'us-east-1' },
    spec,
  });
  const template = Template.fromStack(stack).toJSON();
  const statements = Object.values(
    template.Resources as Record<
      string,
      { Type: string; Properties?: { PolicyDocument?: { Statement?: Array<Record<string, unknown>> } } }
    >
  )
    .filter(resource => resource.Type === 'AWS::IAM::Policy')
    .flatMap(resource => resource.Properties?.PolicyDocument?.Statement ?? []);

  expect(statements).toContainEqual(
    expect.objectContaining({
      Effect: 'Allow',
      Action: expect.arrayContaining(['kms:Decrypt', 'kms:Encrypt', 'kms:GenerateDataKey']),
      Resource: memoryKeyArn,
    })
  );
});

test('target bindings isolate production storage and memory encryption', () => {
  const source = {
    name: 'testproject',
    runtimes: [
      {
        name: 'FrogBot',
        envVars: [{ name: 'FROGBOT_FILES_BUCKET', value: 'development-bucket' }],
        additionalPolicies: ['attachments-policy.json'],
      },
    ],
    memories: [{ name: 'FrogBotMemory', encryptionKeyArn: 'development-key' }],
  } as unknown as Parameters<typeof bindSpecToTarget>[0];
  const target = { name: 'production', account: '123456789012', region: 'us-east-1' } as const;
  const bound = bindSpecToTarget(source, target, 'arn:aws:kms:us-east-1:123456789012:key/key-id', true) as unknown as {
    name: string;
    runtimes: Array<{ envVars: Array<{ name: string; value: string }>; additionalPolicies: string[] }>;
    memories: Array<{ encryptionKeyArn: string }>;
  };

  expect(bound.name).toBe('testprojectProduction');
  expect((source as unknown as { name: string }).name).toBe('testproject');
  expect(filesBucketName(target)).toBe('frogbot-production-user-files-123456789012-us-east-1');
  expect(bound.runtimes[0].envVars).toContainEqual({
    name: 'FROGBOT_FILES_BUCKET',
    value: 'frogbot-production-user-files-123456789012-us-east-1',
  });
  expect(bound.runtimes[0].additionalPolicies).toEqual([]);
  expect(bound.memories[0].encryptionKeyArn).toContain(':123456789012:key/');
  expect(
    (source as unknown as { runtimes: Array<{ additionalPolicies: string[] }> }).runtimes[0].additionalPolicies
  ).toEqual(['attachments-policy.json']);
});

test('production target rejects placeholders and requires an explicit shared-account override', () => {
  expect(() =>
    assertProductionTargetConfigured([
      { name: 'development', account: '123456789012', region: 'us-east-1' },
      { name: 'production', account: UNCONFIGURED_AWS_ACCOUNT, region: 'us-east-1' },
    ])
  ).toThrow('placeholder');
  expect(() =>
    assertProductionTargetConfigured([
      { name: 'development', account: '123456789012', region: 'us-east-1' },
      { name: 'production', account: '123456789012', region: 'us-east-1' },
    ])
  ).toThrow('different AWS account');
  expect(
    assertProductionTargetConfigured(
      [
        { name: 'development', account: '123456789012', region: 'us-east-1' },
        { name: 'production', account: '123456789012', region: 'us-east-1' },
      ],
      true
    )
  ).toEqual({ name: 'production', account: '123456789012', region: 'us-east-1' });
});

test('AgentCore service roles are protected against confused-deputy access', () => {
  const app = new cdk.App();
  const stack = new AgentCoreStack(app, 'TrustStack', {
    env: { account: '123456789012', region: 'us-east-1' },
    spec: {
      name: 'testproject',
      version: 1,
      managedBy: 'CDK' as const,
      runtimes: [],
      memories: [{ name: 'TestMemory', eventExpiryDuration: 30, strategies: [] }],
      credentials: [],
      evaluators: [],
      onlineEvalConfigs: [],
      configBundles: [],
      policyEngines: [],
      payments: [],
      agentCoreGateways: [],
      mcpRuntimeTools: [],
      unassignedTargets: [],
      datasets: [],
      knowledgeBases: [],
    },
  });
  const template = Template.fromStack(stack).toJSON();
  const agentCoreRoles = Object.values(
    template.Resources as Record<
      string,
      {
        Type: string;
        Properties?: { AssumeRolePolicyDocument?: { Statement?: Array<Record<string, unknown>> } };
      }
    >
  )
    .filter(resource => resource.Type === 'AWS::IAM::Role')
    .flatMap(resource => resource.Properties?.AssumeRolePolicyDocument?.Statement ?? [])
    .filter(
      statement =>
        (statement.Principal as { Service?: string } | undefined)?.Service === 'bedrock-agentcore.amazonaws.com'
    );

  expect(agentCoreRoles.length).toBeGreaterThan(0);
  for (const statement of agentCoreRoles) {
    expect(statement).toEqual(
      expect.objectContaining({
        Condition: expect.objectContaining({
          StringEquals: { 'aws:SourceAccount': '123456789012' },
          ArnLike: expect.objectContaining({ 'aws:SourceArn': expect.anything() }),
        }),
      })
    );
    expect(JSON.stringify(statement.Condition)).toContain('bedrock-agentcore:us-east-1:123456789012:*');
  }
});

test('AgentCore Lambda permissions are protected against confused-deputy access', async () => {
  const configRoot = path.resolve(__dirname, '../..');
  const source = await new ConfigIO({ baseDir: configRoot }).readProjectSpec();
  const spec = {
    ...source,
    runtimes: [],
    memories: [],
    onlineEvalConfigs: [],
  };
  const app = new cdk.App();
  const stack = new AgentCoreStack(app, 'LambdaTrustStack', {
    env: { account: '123456789012', region: 'us-east-1' },
    spec,
  });
  const template = Template.fromStack(stack).toJSON();
  const permissions = Object.values(
    template.Resources as Record<string, { Type: string; Properties?: Record<string, unknown> }>
  ).filter(
    resource =>
      resource.Type === 'AWS::Lambda::Permission' &&
      resource.Properties?.Principal === 'bedrock-agentcore.amazonaws.com'
  );

  expect(permissions.length).toBeGreaterThan(0);
  for (const permission of permissions) {
    expect(permission.Properties).toMatchObject({
      SourceAccount: '123456789012',
      SourceArn: expect.anything(),
    });
    expect(JSON.stringify(permission.Properties?.SourceArn)).toContain('bedrock-agentcore:us-east-1:123456789012:*');
  }
});

test('authoritative AgentCore config preserves the runtime wiring contract', async () => {
  const configRoot = path.resolve(__dirname, '../..');
  const spec = await new ConfigIO({ baseDir: configRoot }).readProjectSpec();
  const actual = spec as unknown as {
    runtimes: Array<{
      name: string;
      build: string;
      codeLocation: string;
      runtimeVersion: string;
      networkMode: string;
      authorizerType: string;
      additionalPolicies: string[];
      envVars: Array<{ name: string; value: string }>;
    }>;
    memories: Array<{ name: string; strategies: Array<{ namespaceTemplates: string[] }> }>;
    credentials: Array<{ name: string }>;
    agentCoreGateways: Array<{ name: string; authorizerType: string; targets: Array<{ connectorId: string }> }>;
  };
  const runtime = actual.runtimes.find(item => item.name === 'FrogBot');

  expect(runtime).toMatchObject({
    build: 'CodeZip',
    codeLocation: 'services/agent-runtime/runtime/',
    runtimeVersion: 'PYTHON_3_14',
    networkMode: 'PUBLIC',
    authorizerType: 'AWS_IAM',
    additionalPolicies: ['attachments-policy.json'],
  });
  const runtimeRoot = path.resolve(configRoot, '..', runtime?.codeLocation ?? 'missing');
  expect(
    fs
      .readdirSync(runtimeRoot)
      .filter(item => item !== '__pycache__' && item !== '.DS_Store')
      .sort()
  ).toEqual(['attachments-policy.json', 'frogbot_runtime', 'group_context.py', 'main.py', 'model'].sort());
  expect(fs.existsSync(path.resolve(runtimeRoot, '..', 'pyproject.toml'))).toBe(true);
  expect(fs.existsSync(path.resolve(runtimeRoot, '..', 'uv.lock'))).toBe(true);
  expect(runtime?.envVars).toContainEqual({
    name: 'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT',
    value: 'NO_CONTENT',
  });
  expect(actual.credentials.map(item => item.name)).toEqual(['FrogBot_OpenRouter', 'FrogBotXApi', 'FrogBotYouTubeApi']);
  expect(actual.memories).toContainEqual(
    expect.objectContaining({
      name: 'FrogBotMemory',
      strategies: expect.arrayContaining([
        expect.objectContaining({ namespaceTemplates: ['/facts/{actorId}/'] }),
        expect.objectContaining({ namespaceTemplates: ['/summaries/{actorId}/{sessionId}/'] }),
        expect.objectContaining({ namespaceTemplates: ['/preferences/{actorId}/'] }),
      ]),
    })
  );
  expect(actual.agentCoreGateways).toContainEqual(
    expect.objectContaining({
      name: 'FrogBotTools',
      authorizerType: 'AWS_IAM',
      targets: [expect.objectContaining({ connectorId: 'web-search' })],
    })
  );
});
