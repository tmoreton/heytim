import { cp, mkdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const site = new URL('../', import.meta.url);
const catalog = new URL('../../../catalog/', import.meta.url);
await mkdir(new URL('public/', site), { recursive: true });
// Explicit allowlist: never copy backend config, credentials, or runtime code.
for (const entry of ['catalog.json', 'skills', 'tools', 'bots']) {
  await rm(new URL(`public/${entry}`, site), { recursive: true, force: true });
  await cp(new URL(entry, catalog), new URL(`public/${entry}`, site), {
    recursive: true,
    filter: (source) => !source.includes('__pycache__') && !source.endsWith('.DS_Store'),
  });
}
console.log(`Prepared public catalog assets in ${fileURLToPath(new URL('public/', site))}`);
