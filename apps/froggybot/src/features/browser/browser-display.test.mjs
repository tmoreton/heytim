import assert from 'node:assert/strict';
import test from 'node:test';
import { viewerViewport } from './browser-display.ts';

test('viewer dimensions match mobile/desktop remote screens, with safe legacy fallback', () => {
  assert.deepEqual(viewerViewport({ width: 390, height: 780 }), { width: 390, height: 780 });
  for (const value of [undefined, null, {}, { width: 1e9, height: -1 }, { width: '390', height: 780 }]) {
    assert.deepEqual(viewerViewport(value), { width: 1440, height: 900 });
  }
});
