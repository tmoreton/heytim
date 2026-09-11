import assert from 'node:assert/strict';
import test from 'node:test';

import { nextPollingDelay } from './polling.ts';

test('keeps the normal cadence after a successful poll', () => {
  assert.equal(nextPollingDelay(900, 0, () => 0), 900);
});

test('backs off failed polls with bounded jitter', () => {
  assert.equal(nextPollingDelay(1_000, 1, () => 0), 1_600);
  assert.equal(nextPollingDelay(1_000, 3, () => 0.5), 8_000);
  assert.equal(nextPollingDelay(1_000, 20, () => 0.5), 30_000);
  assert.equal(nextPollingDelay(1_000, 20, () => 1), 30_000);
});
