import assert from 'node:assert/strict';
import test from 'node:test';

import { browserPath, createBrowserApi, createDemoBrowserApi, BROWSER_MUTATION_TIMEOUT_MS } from './browser-api.ts';

test('encodes browser context without silently dropping group IDs', () => {
  const context = { botId: 'bot/a', groupId: 'group?b&c' };
  assert.equal(browserPath(context, '', true), '/bots/bot%2Fa/browser?groupId=group%3Fb%26c');
  assert.equal(browserPath(context, 'profile', true), '/bots/bot%2Fa/browser/profile?groupId=group%3Fb%26c');
});

test('browser API uses agreed methods, explicit consent, no cache and longer mutation timeout', async () => {
  const calls = [];
  const api = createBrowserApi(async (...args) => { calls.push(args); return {}; });
  const context = { botId: 'private' };
  await api.browserStatus(context);
  await api.openBrowser(context);
  await api.resumeBrowser(context, false);
  await api.closeBrowser(context);
  await api.forgetBrowserLogin(context);
  assert.deepEqual(calls.map(([path, init]) => [path, init.method ?? 'GET', init.cache]), [
    ['/bots/private/browser', 'GET', 'no-store'],
    ['/bots/private/browser/open', 'POST', 'no-store'],
    ['/bots/private/browser/resume', 'POST', 'no-store'],
    ['/bots/private/browser/close', 'POST', 'no-store'],
    ['/bots/private/browser/profile', 'DELETE', 'no-store'],
  ]);
  assert.deepEqual(JSON.parse(calls[2][1].body), { rememberLogin: false });
  for (const call of calls.slice(1)) assert.equal(call[2], BROWSER_MUTATION_TIMEOUT_MS);
  assert.ok(BROWSER_MUTATION_TIMEOUT_MS > 29_000);
  await api.resumeBrowser({ ...context, groupId: 'work' }, true);
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body), { groupId: 'work', rememberLogin: true });
  await api.openBrowser(context, { display: 'mobile', url: 'https://example.com/page?q=x#section' });
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body), { display: 'mobile', url: 'https://example.com/page?q=x#section' });
  assert.equal(calls.at(-1)[0], '/bots/private/browser/open', 'Website URLs stay out of request paths and query logs.');
});

test('demo does not claim a real browser, saved login or resumed bot', async () => {
  const api = createDemoBrowserApi();
  const state = await api.browserStatus({ botId: 'demo' });
  assert.equal(state.status, 'closed');
  assert.equal(state.hasSavedLogin, false);
  assert.equal(state.liveViewUrl, undefined);
  for (const method of ['openBrowser', 'resumeBrowser', 'closeBrowser', 'forgetBrowserLogin']) {
    await assert.rejects(api[method]({ botId: 'demo' }, false), /demo mode/i);
  }
});
