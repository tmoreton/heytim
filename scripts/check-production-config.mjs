#!/usr/bin/env node

import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const targets = JSON.parse(await readFile(path.join(root, 'agentcore/aws-targets.json'), 'utf8'));
const spec = JSON.parse(await readFile(path.join(root, 'agentcore/agentcore.json'), 'utf8'));
const development = targets.find(target => target.name === 'development');
const production = targets.find(target => target.name === 'production');

if (!development || !production) throw new Error('Development and production targets are both required.');
if (production.account === '000000000000') {
  throw new Error('Replace the production AWS account placeholder in agentcore/aws-targets.json.');
}
if (production.account === development.account) {
  throw new Error('Production must use a different AWS account from development.');
}

const memoryKeyArn = process.env.HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN?.trim();
const expectedKeyPrefix = `arn:aws:kms:${production.region}:${production.account}:key/`;
if (!memoryKeyArn?.startsWith(expectedKeyPrefix)) {
  throw new Error(`HEYTIM_AGENTCORE_MEMORY_KMS_KEY_ARN must identify a key in ${production.account}/${production.region}.`);
}

// AgentCore keeps the original physical runtime name so production updates in
// place instead of replacing the deployed runtime and its attached resources.
const runtime = spec.runtimes?.find(item => item.name === 'HeyTim');
if (!runtime || runtime.authorizerType !== 'AWS_IAM') {
  throw new Error('The HeyTim production runtime must use AWS_IAM authorization.');
}
if (runtime.instrumentation?.enableOtel !== true) {
  throw new Error('OpenTelemetry must remain enabled for the HeyTim runtime.');
}
const capture = runtime.envVars?.find(
  item => item.name === 'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT',
)?.value;
if (capture !== 'NO_CONTENT') {
  throw new Error('Production tracing must not capture prompt or response content.');
}
const gateway = spec.agentCoreGateways?.find(item => item.name === 'HeyTimTools');
if (!gateway || gateway.authorizerType !== 'AWS_IAM') {
  throw new Error('The HeyTim tools gateway must use AWS_IAM authorization.');
}

process.stdout.write(
  `Production is isolated in its own AWS account: ${production.account}/${production.region}.\n`,
);
