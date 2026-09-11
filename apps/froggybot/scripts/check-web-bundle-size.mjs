import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';

const budgets = [
  { label: 'app entry', pattern: /_expo\/static\/js\/web\/entry-[^/]+\.js$/, bytes: 2_150_000 },
  { label: 'private browser viewer', pattern: /bot-browser\/viewer\.js$/, bytes: 3_200_000 },
];
const root = path.resolve('dist');

async function files(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  return (await Promise.all(entries.map(async (entry) => {
    const item = path.join(directory, entry.name);
    return entry.isDirectory() ? files(item) : [item];
  }))).flat();
}

const outputFiles = await files(root);
for (const budget of budgets) {
  const file = outputFiles.find((candidate) => budget.pattern.test(candidate));
  if (!file) throw new Error(`The ${budget.label} bundle was not produced.`);
  const bytes = (await stat(file)).size;
  console.log(`${budget.label}: ${path.relative(root, file)} (${bytes.toLocaleString()} bytes)`);
  if (bytes > budget.bytes) {
    throw new Error(`${budget.label} exceeds the ${budget.bytes.toLocaleString()} byte production budget.`);
  }
}
