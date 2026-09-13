import { access, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const expoRoot = path.join(root, 'apps/froggybot');
const packageJson = JSON.parse(await readFile(path.join(expoRoot, 'package.json'), 'utf8'));
const eas = JSON.parse(await readFile(path.join(expoRoot, 'eas.json'), 'utf8'));
const workflow = await readFile(path.join(root, '.github/workflows/eas-update.yml'), 'utf8');

const expectedScripts = {
  ios: '../../scripts/apple-app.sh run ios',
  'ios:build': '../../scripts/apple-app.sh build ios',
  'ios:mac': '../../scripts/apple-app.sh run macos',
  'ios:mac:build': '../../scripts/apple-app.sh build macos',
  'eas-build-pre-install': 'node scripts/reject-deprecated-native-build.mjs',
};

for (const [name, command] of Object.entries(expectedScripts)) {
  if (packageJson.scripts?.[name] !== command) {
    throw new Error(`Expo script ${name} must route through the supported SwiftUI/deprecation entry point.`);
  }
}

const buildProfiles = Object.keys(eas.build ?? {});
if (buildProfiles.length === 0 || buildProfiles.some((profile) => !profile.startsWith('archived-'))) {
  throw new Error('Every retained Expo native build profile must be explicitly archived.');
}
if (eas.submit !== undefined) {
  throw new Error('The deprecated Expo client must not define an EAS submit profile.');
}
if (/\beas\s+update\b/.test(workflow)) {
  throw new Error('The browser deployment workflow must not publish a native Expo update.');
}

await Promise.all([
  access(path.join(root, 'scripts/apple-app.sh')),
  access(path.join(root, 'apps/froggybot-apple/scripts/run.sh')),
  access(path.join(root, 'apps/froggybot-apple/scripts/archive.sh')),
  access(path.join(root, 'apps/froggybot-apple/scripts/testflight.sh')),
]);

console.log('Verified SwiftUI is the primary Apple build and TestFlight entry point.');
