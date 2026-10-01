import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const source = path.join(root, 'services/API/amplify_outputs.json');
const destination = path.join(root, 'apps/iOS/Resources/amplify_outputs.json');
const check = process.argv.includes('--check');
const requireProduction = process.argv.includes('--require-production');
const outputs = JSON.parse(await readFile(source, 'utf8'));
if (requireProduction && outputs.custom?.environment !== 'production') {
  throw new Error('Refusing an Apple release with non-production Amplify outputs.');
}
if (requireProduction) {
  const targets = JSON.parse(await readFile(path.join(root, 'agentcore/aws-targets.json'), 'utf8'));
  const production = targets.find((target) => target.name === 'production');
  if (!production?.account || !production?.region) {
    throw new Error('Production AWS target is missing from agentcore/aws-targets.json.');
  }
  const expectedBucket = `heytim-production-user-files-${production.account}-${production.region}`;
  if (outputs.auth?.aws_region !== production.region
      || outputs.custom?.filesBucketName !== expectedBucket
      || !outputs.custom?.alarmTopicArn?.startsWith(`arn:aws:sns:${production.region}:${production.account}:`)
      || !outputs.custom?.githubDeployRoleArn?.startsWith(`arn:aws:iam::${production.account}:role/`)) {
    throw new Error('Refusing an Apple release with Amplify outputs from another AWS account.');
  }
}
const value = `${JSON.stringify({
  auth: {
    user_pool_id: outputs.auth?.user_pool_id,
    aws_region: outputs.auth?.aws_region,
    user_pool_client_id: outputs.auth?.user_pool_client_id,
  },
  version: outputs.version,
  custom: {
    apiUrl: outputs.custom?.apiUrl,
    shareBaseUrl: outputs.custom?.shareBaseUrl,
    environment: outputs.custom?.environment,
  },
}, null, 2)}\n`;

if (check) {
  const current = await readFile(destination, 'utf8');
  if (current !== value) throw new Error('Apple amplify_outputs.json is stale. Run npm run outputs:apple.');
} else {
  await mkdir(path.dirname(destination), { recursive: true });
  await writeFile(destination, value);
}
