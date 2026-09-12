import assert from 'node:assert/strict';
import test from 'node:test';

import { createDemoBrowserApi } from './demo-browser-api.ts';

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
