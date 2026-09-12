import { cp, mkdir, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(app, '../froggybot-browser-viewer/dist');
const target = resolve(app, 'public');

await mkdir(target, { recursive: true });
for (const directory of ['bot-browser', 'nice-dcv-web-client-sdk']) {
  await rm(resolve(target, directory), { recursive: true, force: true });
  await cp(resolve(source, directory), resolve(target, directory), { recursive: true });
}

console.log('Copied the independently built browser viewer into Expo web assets.');
