import assert from 'node:assert/strict';
import test from 'node:test';

import { describeSchedule, parseTimeInput } from './schedules.ts';

test('normalizes supported 12-hour and 24-hour times', () => {
  assert.equal(parseTimeInput('9:05 am'), '09:05');
  assert.equal(parseTimeInput('12 pm'), '12:00');
  assert.equal(parseTimeInput('12 am'), '00:00');
  assert.equal(parseTimeInput('23:59'), '23:59');
  assert.equal(parseTimeInput('25:00'), undefined);
  assert.equal(parseTimeInput('9:99'), undefined);
});

test('describes recurring schedules in user-facing terms', () => {
  assert.equal(describeSchedule({ frequency: 'weekly', dayOfWeek: 'FRI', time: '16:30' }), 'Every Friday at 4:30 PM');
  assert.equal(describeSchedule({ frequency: 'monthly', dayOfMonth: 15, time: '08:00' }), 'Monthly on day 15 at 8:00 AM');
});
