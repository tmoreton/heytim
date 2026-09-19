import assert from 'node:assert/strict';
import test from 'node:test';

import { apiRoutes } from './routes.ts';

test('encodes every dynamic API path segment', () => {
  assert.equal(apiRoutes.botMessages('bot/a b'), '/bots/bot%2Fa%20b/messages');
  assert.equal(apiRoutes.groupMember('group/one', 'member two'), '/groups/group%2Fone/members/member%20two');
  assert.equal(
    apiRoutes.groupMemoryRecord('group/one', 'memory?two'),
    '/groups/group%2Fone/memory/memory%3Ftwo',
  );
  assert.equal(apiRoutes.botScheduleRun('bot/one', 'schedule?two'), '/bots/bot%2Fone/schedules/schedule%3Ftwo/run');
  assert.equal(
    apiRoutes.connectionAuthorization('provider/one'),
    '/connections/provider%2Fone/authorization',
  );
  assert.equal(
    apiRoutes.groupDecision('group/one', 'decision?two'),
    '/groups/group%2Fone/decisions/decision%3Ftwo',
  );
});

test('encodes opaque pagination cursors as query values', () => {
  assert.equal(
    apiRoutes.botMessages('bot/one', 'page+/='),
    '/bots/bot%2Fone/messages?cursor=page%2B%2F%3D',
  );
});
