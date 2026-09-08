import assert from 'node:assert/strict';
import test from 'node:test';

import { messagePreview } from './message-preview.ts';

test('removes common markdown without losing its readable content', () => {
  assert.equal(
    messagePreview('**Decision:** use [`Option A`](https://example.com)\n- Owner: Jordan'),
    'Decision: use Option A Owner: Jordan',
  );
});

test('collapses code fences and bounds long previews', () => {
  assert.equal(messagePreview('```js\nconst answer = 42;\n```'), 'const answer = 42;');
  assert.equal(messagePreview('abcdefghijk', 8), 'abcdefg…');
});
