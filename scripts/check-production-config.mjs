#!/usr/bin/env node

import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const targets = JSON.parse(await readFile(path.join(root, 'agentcore/aws-targets.json'), 'utf8'));
const spec = JSON.parse(await readFile(path.join(root, 'agentcore/agentcore.json'), 'utf8'));
const development = targets.find(target => target.name === 'development');
const production = targets.find(target => target.name === 'production');
const sharedProductionAccountAllowed = process.env.FROGBOT_ALLOW_SHARED_PRODUCTION_ACCOUNT === 'true';

if (!development || !production) throw new Error('Development and production targets are both required.');
if (production.account === '000000000000') {
  throw new Error('Replace the production AWS account placeholder in agentcore/aws-targets.json.');
}
if (production.account === development.account && !sharedProductionAccountAllowed) {
  throw new Error(
    'Production must use a different AWS account from development unless FROGBOT_ALLOW_SHARED_PRODUCTION_ACCOUNT=true.',
  );
}

const memoryKeyArn = process.env.FROGBOT_AGENTCORE_MEMORY_KMS_KEY_ARN?.trim();
const expectedKeyPrefix = `arn:aws:kms:${production.region}:${production.account}:key/`;
if (!memoryKeyArn?.startsWith(expectedKeyPrefix)) {
  throw new Error(`FROGBOT_AGENTCORE_MEMORY_KMS_KEY_ARN must identify a key in ${production.account}/${production.region}.`);
}

const runtime = spec.runtimes?.find(item => item.name === 'FrogBot');
if (!runtime || runtime.authorizerType !== 'AWS_IAM') {
  throw new Error('The FrogBot production runtime must use AWS_IAM authorization.');
}
if (runtime.instrumentation?.enableOtel !== true) {
  throw new Error('OpenTelemetry must remain enabled for the FrogBot runtime.');
}
const capture = runtime.envVars?.find(
  item => item.name === 'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT',
)?.value;
if (capture !== 'NO_CONTENT') {
  throw new Error('Production tracing must not capture prompt or response content.');
}
const gateway = spec.agentCoreGateways?.find(item => item.name === 'FrogBotTools');
if (!gateway || gateway.authorizerType !== 'AWS_IAM') {
  throw new Error('The FrogBot tools gateway must use AWS_IAM authorization.');
}

const posture =
  production.account === development.account
    ? 'temporarily shares its AWS account with development while retaining target-scoped resources'
    : 'is isolated in its own AWS account';
process.stdout.write(`Production ${posture}: ${production.account}/${production.region}.\n`);
