import assert from 'node:assert/strict';
import test from 'node:test';

import { formatElapsed, messageTimingLabel } from './message-timing.ts';

const clock = () => '2:00 PM';
const assistant = (overrides = {}) => ({
  id: 'answer-1', role: 'assistant', text: '', createdAt: '2026-09-09T18:00:00Z',
  startedAt: '2026-09-09T18:00:00Z', status: 'running', ...overrides,
});

test('formats useful elapsed durations without false precision', () => {
  assert.equal(formatElapsed(42_900), '42s');
  assert.equal(formatElapsed(20 * 60_000 + 14_000), '20m 14s');
  assert.equal(formatElapsed(2 * 3_600_000 + 12 * 60_000), '2h 12m');
});

test('describes live and completed assistant timing', () => {
  assert.equal(
    messageTimingLabel(assistant(), Date.parse('2026-09-09T18:20:14Z'), clock),
    'Started 2:00 PM · Running 20m 14s',
  );
  assert.equal(
    messageTimingLabel(assistant({ status: 'complete', completedAt: '2026-09-09T18:03:09Z' }), 0, clock),
    'Started 2:00 PM · Ran 3m 9s',
  );
});

test('labels sent, queued, cancelled, and failed messages clearly', () => {
  assert.equal(messageTimingLabel({ ...assistant(), role: 'user', status: 'complete' }, 0, clock), 'Sent 2:00 PM');
  assert.match(messageTimingLabel(assistant({ status: 'pending' }), Date.parse('2026-09-09T18:00:05Z'), clock), /Queued 5s$/);
  assert.match(messageTimingLabel(assistant({ status: 'cancelled', completedAt: '2026-09-09T18:00:08Z' }), 0, clock), /Stopped after 8s$/);
  assert.match(messageTimingLabel(assistant({ status: 'error', completedAt: '2026-09-09T18:00:11Z' }), 0, clock), /Failed after 11s$/);
});

test('shows how stale the latest progress update is', () => {
  const message = assistant({ activityUpdatedAt: '2026-09-09T18:17:00Z' });
  assert.match(
    messageTimingLabel(message, Date.parse('2026-09-09T18:20:14Z'), clock),
    /Updated 3m 14s ago$/,
  );
});
