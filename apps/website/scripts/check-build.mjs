import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';

const site = new URL('../', import.meta.url);
const output = new URL('dist/', site);
const catalog = JSON.parse(await readFile(new URL('../../../catalog/catalog.json', import.meta.url), 'utf8'));
assert.deepEqual(JSON.parse(await readFile(new URL('catalog.json', output), 'utf8')), catalog);
for (const route of ['index.html', 'features/index.html', 'skills/index.html', 'library/index.html', 'invite/index.html', 'billing/index.html', 'app/index.html', 'download/index.html', 'privacy/index.html', 'terms/index.html', 'sms/index.html', 'contribute/index.html', '404.html']) {
  const html = await readFile(new URL(route, output), 'utf8');
  assert.match(html, /<h1[ >]/, `${route} must be prerendered`);
  assert.doesNotMatch(html, /https:\/\/app\.heytim\.com/, `${route} must not link to retired browser chat`);
  const path = route === 'index.html' ? '/' : route === '404.html' ? '/404/' : `/${route.replace('index.html', '')}`;
  assert(html.includes(`<link rel="canonical" href="https://heytim.ai${path}"`), `${route} needs its own canonical URL`);
  const title = html.match(/<title>([^<]*)<\/title>/)?.[1];
  assert(html.includes(`<meta property="og:title" content="${title}"`), `${route} needs matching share metadata`);
}
const sitemap = await readFile(new URL('sitemap.xml', output), 'utf8');
assert(sitemap.includes('https://heytim.ai/features/'));
assert(!sitemap.includes('https://heytim.ai/invite/'));
for (const route of ['invite', 'app', 'billing']) {
  assert.match(await readFile(new URL(`${route}/index.html`, output), 'utf8'), /name="robots" content="noindex, follow"/);
}
for (const skill of catalog.skills) {
  assert.equal(await readFile(new URL(skill.path, output), 'utf8'),
    await readFile(new URL(`../../../catalog/${skill.path}`, import.meta.url), 'utf8'));
}
const associationSource = await readFile(new URL('.well-known/apple-app-site-association', output), 'utf8');
const association = JSON.parse(associationSource);
assert.equal(await readFile(new URL('apple-app-site-association', output), 'utf8'), associationSource);
assert(association.applinks.details[0].appIDs.includes('GVXC5FQ2RP.com.heytim.app'));
assert(association.applinks.details[0].components.some((component) => component['/'] === '/billing*'));
assert(association.applinks.details[0].components.some((component) => component['/'] === '/plaid-oauth*'));
const assets = await readdir(new URL('assets/', output));
let javascriptBytes = 0;
for (const file of assets.filter((name) => name.endsWith('.js'))) {
  const bytes = await readFile(new URL(`assets/${file}`, output));
  javascriptBytes += bytes.length;
  assert.doesNotMatch(bytes.toString(), /expo-router|USER_AUTH|user_pool_id|demo-thumbnail-preview|aws-amplify/);
}
assert(javascriptBytes < 400_000, `Marketing site JS exceeded 400 KB: ${javascriptBytes}`);
console.log(`Public website checks passed: ${catalog.skills.length} skills, ${javascriptBytes} JS bytes, no chat/auth/Expo bundle.`);
