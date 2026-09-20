import { access, readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    const location = path.join(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(location) : [location];
  }));
  return files.flat();
}

const website = JSON.parse(await readFile(path.join(root, 'apps/website/package.json'), 'utf8'));
const dependencies = { ...website.dependencies, ...website.devDependencies };
if (Object.keys(dependencies).some((name) => /expo|react-native|amplify|heytim\/(client|preview)/.test(name))) {
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

const productSources = [
  ...(await sourceFiles(path.join(root, 'apps/website/src'))),
  path.join(root, 'apps/website/index.html'),
  ...(await sourceFiles(path.join(root, 'apps/iOS/App'))),
  ...(await sourceFiles(path.join(root, 'apps/iOS/Sources'))),
  ...(await sourceFiles(path.join(root, 'apps/iOS/Resources'))),
].filter((file) => /\.(?:css|entitlements|html|js|json|plist|swift|ts|tsx)$/.test(file));
for (const file of productSources) {
  const content = await readFile(file, 'utf8');
  if (/\bfrog[\s_-]*bot\b/i.test(content)) {
    throw new Error(`Legacy FrogBot product branding found in ${path.relative(root, file)}`);
  }
}

console.log('Verified HeyTim branding, Vite public site, SwiftUI releases, API, runtime, and local catalog boundaries.');
