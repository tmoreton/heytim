import assert from 'node:assert/strict';
import test from 'node:test';
import { DictationSession } from './dictation-session.ts';

test('Send clears the draft permanently even if native speech returns a final result', () => {
  const session = new DictationSession();
  const token = session.begin('Already typed ', 'personal');
  assert.equal(session.start(token, 'personal'), true);
  assert.equal(session.result('dictated text', 'personal'), 'Already typed dictated text');
  session.cancel();
  assert.equal(session.result('dictated text.', 'personal'), undefined);
});

test('pending permissions cannot restart dictation after sending or switching conversations', () => {
  const session = new DictationSession();
  const old = session.begin('', 'personal');
  session.cancel();
  assert.equal(session.start(old, 'personal'), false);
  const next = session.begin('', 'work');
  assert.equal(session.start(next, 'personal'), false);
  assert.equal(session.start(next, 'work'), true);
  assert.equal(session.result('private text', 'personal'), undefined);
  assert.equal(session.result('new words', 'work'), 'new words');
});
