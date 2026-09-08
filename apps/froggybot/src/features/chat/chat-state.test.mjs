import assert from 'node:assert/strict';
import test from 'node:test';

import {
  chooseAvailableSelection,
  isActiveResponse,
  isPendingMessage,
  isRefreshingMessage,
} from './chat-state.ts';

const message = (status) => ({ id: status, role: 'assistant', text: '', createdAt: '', status });
const bootstrap = { bots: [{ id: 'bot-1' }], groups: [{ id: 'group-1' }] };

test('classifies message lifecycle states consistently', () => {
  assert.equal(isActiveResponse(message('running')), true);
  assert.equal(isActiveResponse(message('waiting')), false);
  assert.equal(isRefreshingMessage(message('waiting')), true);
  assert.equal(isPendingMessage(message('awaiting_approval')), true);
  assert.equal(isPendingMessage(message('complete')), false);
});

test('keeps an available selection and otherwise uses the first conversation', () => {
  assert.deepEqual(chooseAvailableSelection(bootstrap, { kind: 'bot', id: 'bot-1' }), {
    kind: 'bot', id: 'bot-1',
  });
  assert.deepEqual(chooseAvailableSelection(bootstrap, { kind: 'bot', id: 'missing' }), {
    kind: 'group', id: 'group-1',
  });
});
