import assert from 'node:assert/strict';
import test from 'node:test';

import { invitationFromParams, invitationFromUrl, invitationUrl } from './invitation-url.ts';

test('parses web and app invitation URLs', () => {
  assert.deepEqual(invitationFromUrl('https://froggybot.com/group/team-token'), { kind: 'group', token: 'team-token' });
  assert.deepEqual(invitationFromUrl('frogbot://skill/shared%20skill'), { kind: 'skill', token: 'shared%20skill' });
  assert.deepEqual(invitationFromUrl('frogbot://invite?kind=chat&token=chat-token'), { kind: 'chat', token: 'chat-token' });
});

test('normalizes router params and rejects incomplete invitations', () => {
  assert.deepEqual(invitationFromParams(['bot', 'chat'], ['first-token', 'second-token']), { kind: 'bot', token: 'first-token' });
  assert.equal(invitationFromParams('unknown', 'token'), undefined);
  assert.equal(invitationFromParams('group', undefined), undefined);
});

test('builds an encoded app invitation URL', () => {
  assert.equal(invitationUrl({ kind: 'skill', token: 'a token&more' }), 'frogbot://invite?kind=skill&token=a%20token%26more');
});
