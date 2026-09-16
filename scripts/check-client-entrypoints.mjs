import { access, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const website = JSON.parse(await readFile(path.join(root, 'apps/website/package.json'), 'utf8'));
const dependencies = { ...website.dependencies, ...website.devDependencies };
if (Object.keys(dependencies).some((name) => /expo|react-native|amplify|froggybot\/(client|preview)/.test(name))) {
  throw new Error('The public website must not depend on the retired chat/native/auth stack.');
}
if (!dependencies.vite || !dependencies.react || !website.scripts.build.includes('vite build')) {
  throw new Error('The public website must use Vite and React.');
}
const apps = (await readdir(path.join(root, 'apps'), { withFileTypes: true }))
  .filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort();
if (JSON.stringify(apps) !== JSON.stringify(['iOS', 'website'])) {
  throw new Error(`Unexpected app directories: ${apps.join(', ')}. Expo belongs in the local reference archive.`);
}
for (const retired of ['apps/website/amplify_outputs.json', 'apps/website/eas.json', '.easignore']) {
  try { await access(path.join(root, retired)); } catch (error) {
    if (error.code === 'ENOENT') continue;
    throw error;
  }
  throw new Error(`Retired or private client configuration found at ${retired}`);
}

await Promise.all([
  access(path.join(root, 'scripts/apple-app.sh')),
  access(path.join(root, 'apps/iOS/scripts/run.sh')),
  access(path.join(root, 'apps/iOS/scripts/archive.sh')),
  access(path.join(root, 'apps/iOS/scripts/testflight.sh')),
  access(path.join(root, 'services/API/amplify_outputs.json')),
  access(path.join(root, 'services/runtime/runtime/main.py')),
  access(path.join(root, 'catalog/catalog.json')),
]);

console.log('Verified Vite public site, SwiftUI releases, API, runtime, and local catalog boundaries.');
