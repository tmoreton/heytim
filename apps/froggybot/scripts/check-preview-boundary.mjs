import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';

const bundleDirectory = join(process.cwd(), 'dist', '_expo', 'static', 'js');
const previewMarkers = [
  'demo-thumbnail-preview',
  'FroggyBot preview attachment',
  'Weekend in Portland',
];

const javascriptFiles = async (directory) => {
  const entries = await readdir(directory, { withFileTypes: true });
  return (await Promise.all(entries.map(async (entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? javascriptFiles(path) : path.endsWith('.js') ? [path] : [];
  }))).flat();
};

const files = await javascriptFiles(bundleDirectory);
for (const file of files) {
  const source = await readFile(file, 'utf8');
  const marker = previewMarkers.find((candidate) => source.includes(candidate));
  if (marker) {
    throw new Error(`Production bundle ${file} contains local preview marker: ${marker}`);
  }
}

console.log(`Verified ${files.length} production bundles contain no local preview engine markers.`);
