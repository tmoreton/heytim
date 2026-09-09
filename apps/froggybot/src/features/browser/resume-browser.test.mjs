import assert from 'node:assert/strict';
import test from 'node:test';

import { resumeBrowserWithProfilePolling } from './resume-browser.ts';

test('polls only confirmed profile saves, preserving explicit consent until one turn is accepted', async () => {
  const calls = [], states = [];
  const api = { resumeBrowser: async (...args) => {
    calls.push(args);
    return calls.length < 3 ? { status: 'resuming', botId: 'b' } : { status: 'ready', botId: 'b', resumedTurnId: 'once' };
  } };
  const result = await resumeBrowserWithProfilePolling({ api, botId: 'b', rememberLogin: true, onState: (value) => states.push(value), wait: async () => {} });
  assert.equal(result.resumedTurnId, 'once');
  assert.equal(calls.length, 3);
  assert.deepEqual(calls, Array.from({ length: 3 }, () => [{ botId: 'b' }, true]));
  assert.deepEqual(states.map((state) => state.status), ['resuming', 'resuming', 'ready']);
});

test('never automatically repeats a request after uncertain network failure', async () => {
  let calls = 0;
  await assert.rejects(resumeBrowserWithProfilePolling({ api: { resumeBrowser: async () => { calls++; throw new Error('timeout'); } }, botId: 'b', rememberLogin: false, onState: () => {}, wait: async () => {} }), /timeout/);
  assert.equal(calls, 1);
});

test('bounds a profile-saving loop and leaves the result pending, not successful', async () => {
  let calls = 0;
  const result = await resumeBrowserWithProfilePolling({ api: { resumeBrowser: async () => { calls++; return { status: 'resuming' }; } }, botId: 'b', rememberLogin: true, onState: () => {}, wait: async () => {} });
  assert.equal(calls, 8);
  assert.equal(result.status, 'resuming');
  assert.equal(result.resumedTurnId, undefined);
});

test('does not retry other states or continue after viewer owner unmounts', async () => {
  let calls = 0;
  const api = { resumeBrowser: async () => { calls++; return { status: 'human_control' }; } };
  const args = { api, botId: 'b', rememberLogin: false, onState: () => {}, wait: async () => {} };
  await resumeBrowserWithProfilePolling(args);
  assert.equal(calls, 1);
  await resumeBrowserWithProfilePolling({ ...args, isActive: () => false });
  assert.equal(calls, 1);
});
