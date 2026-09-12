import assert from 'node:assert/strict';
import test from 'node:test';

import { installPrivateViewerStorage, memoryStorage } from './memory-storage.ts';

test('viewer storage supports SDK API and bracket access without persisting between viewers', () => {
  const storage = memoryStorage();
  storage.setItem('setting', 'value');
  storage.other = 'private';
  assert.equal(storage.getItem('other'), 'private');
  assert.equal(storage.setting, 'value');
  assert.equal(storage.length, 2);
  assert.equal(storage.key(0), 'setting');
  assert.equal(memoryStorage().getItem('other'), null);
  storage.removeItem('setting');
  delete storage.other;
  assert.equal(storage.length, 0);
});

test('shadowing a viewer leaves the parent app storage untouched', () => {
  const original = memoryStorage();
  original.setItem('app-login', 'existing');
  const viewer = { localStorage: original, sessionStorage: original };
  installPrivateViewerStorage(viewer);
  viewer.localStorage.setItem('viewer-cache', 'temporary');
  assert.equal(original.getItem('app-login'), 'existing');
  assert.equal(original.getItem('viewer-cache'), null);
  assert.equal(viewer.sessionStorage.getItem('viewer-cache'), null);
});
