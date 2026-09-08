import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { ConfigIO } from '@aws/agentcore-cdk';
import * as fs from 'fs';
import * as path from 'path';
import { AgentCoreStack } from '../lib/cdk-stack';

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
  expect(actual.credentials.map(item => item.name)).toEqual(['FrogBot_OpenRouter']);
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
