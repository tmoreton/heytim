import { readdir, stat } from 'node:fs/promises';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(app, 'src');
const forbiddenTrees = [
  'amplify',
  'modules',
  'src/lib/api',
  'src/lib/demo',
  'src/features/browser/viewer',
];
const allowedLogicFiles = new Set([
  'src/components/markdown-table-layout.ts',
  'src/components/use-modal-focus.ts',
  'src/features/browser/browser-handoff.styles.ts',
  'src/features/chat/chat-app.styles.ts',
  'src/features/chat/chat-scroll-policy.ts',
  'src/features/chat/skill-library.styles.ts',
  'src/features/chat/use-chat-scroll.ts',
  'src/lib/api.ts',
  'src/lib/cloud.ts',
  'src/lib/preview/preview-api.disabled.ts',
  'src/lib/preview/preview-api.enabled.ts',
  'src/lib/theme.ts',
]);

const exists = async (path) => stat(path).then(() => true, () => false);
const files = async (directory) => (await Promise.all(
  (await readdir(directory, { withFileTypes: true })).map((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? files(path) : [path];
  }),
)).flat();

const violations = [];
for (const tree of forbiddenTrees) {
  if (await exists(resolve(app, tree))) violations.push(`${tree} must live outside the Expo app`);
}
const sourceFiles = await files(source);
for (const path of sourceFiles) {
  const name = relative(app, path);
  if (path.endsWith('.ts') && !path.endsWith('.test.ts') && !allowedLogicFiles.has(name)) {
    violations.push(`${name} is non-view code; move it to a package or backend service`);
  }
}

if (violations.length) {
  console.error(`Expo view boundary failed:\n- ${violations.join('\n- ')}`);
  process.exit(1);
}
console.log('Expo view boundary passed.');
