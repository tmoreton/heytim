import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { renderToString } from 'react-dom/server';
import { execFileSync } from 'node:child_process';
import { Website, pages } from '../src/website';
import { descriptions, unindexedRoutes } from '../src/metadata';

function escapeHTML(value: string) {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]!);
}

const output = new URL('../dist/', import.meta.url);
const template = await readFile(new URL('index.html', output), 'utf8');
for (const route of [...Object.keys(pages), '/404']) {
  const title = escapeHTML(pages[route] ?? 'Page not found — HeyTim');
  const description = escapeHTML(descriptions[route] ?? 'Find your way back to HeyTim’s bots, skills, and app.');
  const canonical = `https://heytim.ai${route === '/' ? '/' : `${route}/`}`;
  const html = template.replace('<!--prerender-->', renderToString(<Website pathname={route} />))
    .replace(/<title>[^<]*<\/title>/, `<title>${title}</title>`)
    .replace(/<meta name="description"[^>]*>/, `<meta name="description" content="${description}" />`)
    .replace(/<meta property="og:title"[^>]*>/, `<meta property="og:title" content="${title}" />`)
    .replace(/<meta property="og:description"[^>]*>/, `<meta property="og:description" content="${description}" />`)
    .replace(/<meta property="og:url"[^>]*>/, `<meta property="og:url" content="${canonical}" />`)
    .replace(/<link rel="canonical"[^>]*>/, `<link rel="canonical" href="${canonical}" />`)
    .replace('<!--robots-->', unindexedRoutes.has(route) ? '<meta name="robots" content="noindex, follow" />' : '');
  const path = route === '/' ? 'index.html' : route === '/404' ? '404.html' : `${route.slice(1)}/index.html`;
  await mkdir(new URL('./', new URL(path, output)), { recursive: true });
  await writeFile(new URL(path, output), html);
}
const publicURLs = Object.keys(pages).filter((route) => !unindexedRoutes.has(route))
  .map((route) => `  <url><loc>https://heytim.ai${route === '/' ? '/' : `${route}/`}</loc></url>`);
await writeFile(new URL('sitemap.xml', output), `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${publicURLs.join('\n')}\n</urlset>\n`);
await writeFile(new URL('robots.txt', output), 'User-agent: *\nAllow: /\nSitemap: https://heytim.ai/sitemap.xml\n');
console.log('Prerendered all public routes for direct links, search, and no-JavaScript access.');
await writeFile(new URL('release.json', output), `${JSON.stringify({
  sourceRevision: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
  frontend: 'vite-react', browserChat: false,
}, null, 2)}\n`);
