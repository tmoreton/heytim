import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { renderToString } from 'react-dom/server';
import { execFileSync } from 'node:child_process';
import { Website, pages } from '../src/website';

const output = new URL('../dist/', import.meta.url);
const template = await readFile(new URL('index.html', output), 'utf8');
for (const route of [...Object.keys(pages), '/404']) {
  const html = template.replace('<!--prerender-->', renderToString(<Website pathname={route} />))
    .replace(/<title>[^<]*<\/title>/, `<title>${pages[route] ?? 'Page not found — FroggyBot'}</title>`);
  const path = route === '/' ? 'index.html' : route === '/404' ? '404.html' : `${route.slice(1)}/index.html`;
  await mkdir(new URL('./', new URL(path, output)), { recursive: true });
  await writeFile(new URL(path, output), html);
}
console.log('Prerendered all public routes for direct links, search, and no-JavaScript access.');
await writeFile(new URL('release.json', output), `${JSON.stringify({
  sourceRevision: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
  frontend: 'vite-react', browserChat: false,
}, null, 2)}\n`);
