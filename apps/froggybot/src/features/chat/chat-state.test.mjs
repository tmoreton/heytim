import assert from 'node:assert/strict';
import test from 'node:test';

import {
  chooseAvailableSelection,
  composerPrimaryAction,
  isActiveResponse,
  isPendingMessage,
  isRefreshingMessage,
  reconcileBootstrap,
  reconcileMessages,
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

test('shows only one composer action while a response is running', () => {
  assert.equal(composerPrimaryAction(true, '', 0, false), 'stop');
  assert.equal(composerPrimaryAction(true, 'Redirect this response', 0, false), 'send');
  assert.equal(composerPrimaryAction(true, '', 1, false), 'send');
  assert.equal(composerPrimaryAction(true, '', 0, true), 'send');
  assert.equal(composerPrimaryAction(false, '', 0, false), 'send');
});

test('keeps an available selection and otherwise uses the first conversation', () => {
  assert.deepEqual(chooseAvailableSelection(bootstrap, { kind: 'bot', id: 'bot-1' }), {
    kind: 'bot', id: 'bot-1',
  });
  assert.deepEqual(chooseAvailableSelection(bootstrap, { kind: 'bot', id: 'missing' }), {
    kind: 'group', id: 'group-1',
  });
});

test('reuses unchanged message arrays and individual unchanged messages', () => {
  const current = [
    { ...message('complete'), id: 'one', text: 'First' },
    { ...message('running'), id: 'two', text: 'Second', activity: ['Working'] },
  ];
  const unchanged = reconcileMessages(current, structuredClone(current));
  assert.equal(unchanged, current);

  const changedInput = structuredClone(current);
  changedInput[1].activity.push('Still working');
  const changed = reconcileMessages(current, changedInput);
  assert.notEqual(changed, current);
  assert.equal(changed[0], current[0]);
  assert.notEqual(changed[1], current[1]);
});

test('reuses an unchanged bootstrap response', () => {
  const current = {
    bots: [{ id: 'bot-1', toolIds: ['browser'] }],
    groups: [],
    botTemplates: [],
    needsBotOnboarding: false,
    tools: [],
    skills: [],
  };
  assert.equal(reconcileBootstrap(current, structuredClone(current)), current);
  const changed = structuredClone(current);
  changed.bots[0].toolIds.push('search');
  assert.notEqual(reconcileBootstrap(current, changed), current);
});
