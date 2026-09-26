import { build } from 'esbuild';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const directory = await mkdtemp(path.join(tmpdir(), 'heytim-plaid-test-'));
try {
  const output = path.join(directory, 'handler-test.cjs');
  await build({
    entryPoints: ['amplify/functions/plaid-webhook/handler.test.ts'],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    outfile: output,
    logLevel: 'warning',
  });
  const result = spawnSync(process.execPath, ['--test', output], { stdio: 'inherit' });
  if (result.status !== 0) process.exitCode = result.status ?? 1;
} finally {
  await rm(directory, { recursive: true, force: true });
}
