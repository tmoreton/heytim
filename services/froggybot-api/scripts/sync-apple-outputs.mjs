import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const source = path.join(root, 'apps/froggybot/amplify_outputs.json');
const destination = path.join(root, 'apps/froggybot-apple/Resources/amplify_outputs.json');
const check = process.argv.includes('--check');
const outputs = JSON.parse(await readFile(source, 'utf8'));
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
  },
}, null, 2)}\n`;

if (check) {
  const current = await readFile(destination, 'utf8');
  if (current !== value) throw new Error('Apple amplify_outputs.json is stale. Run npm run outputs:apple.');
} else {
  await mkdir(path.dirname(destination), { recursive: true });
  await writeFile(destination, value);
}
